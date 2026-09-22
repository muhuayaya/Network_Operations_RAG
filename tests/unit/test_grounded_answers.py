"""证据问答编排和模型降级契约测试。"""

from __future__ import annotations

import unittest

from netops_copilot.application.grounded_answers import (
    GroundedAnswerService,
    KeywordReranker,
)
from netops_copilot.application.ports.models import (
    LLMRequest,
    LLMResult,
    ModelStatus,
)
from netops_copilot.application.ports.search import (
    SearchCandidate,
    SearchChannel,
    SearchFilters,
    SearchResult,
)
from netops_copilot.application.query import QueryMode, QueryService
from netops_copilot.infrastructure.providers.model_factory import create_answer_models
from netops_copilot.settings import ProfileName, load_profile


class _Search:
    def __init__(self, result: SearchResult) -> None:
        self.result = result

    def search(self, *args: object, **kwargs: object) -> SearchResult:
        del args, kwargs
        return self.result


class _LLM:
    def __init__(self, result: LLMResult) -> None:
        self.result = result
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest, timeout_seconds: float = 30.0) -> LLMResult:
        del timeout_seconds
        self.requests.append(request)
        return self.result


def _candidate(channel: SearchChannel, chunk_id: str, text: str) -> SearchCandidate:
    return SearchCandidate(
        chunk_id,
        channel,
        1,
        1.0,
        {"source_id": "sop-1", "source_locator": "ospf.md#chunk:0"},
        text,
    )


class GroundedAnswerTests(unittest.TestCase):
    def test_answer_prompt_contains_only_retrieved_evidence_and_citations(self) -> None:
        dense = _Search(SearchResult.matches([_candidate(SearchChannel.DENSE, "c-1", "检查 MTU 与邻居状态。")]))
        lexical = _Search(SearchResult.matches([_candidate(SearchChannel.LEXICAL, "c-1", "检查 MTU 与邻居状态。")]))
        llm = _LLM(LLMResult(ModelStatus.SUCCESS, text="先检查接口 MTU [1]。"))
        service = GroundedAnswerService(
            QueryService(dense, lexical),
            lambda query: [1.0],
            {"dashscope": llm},
        )

        result = service.answer(
            question="OSPF ExStart 怎么排查？",
            filters=SearchFilters(),
            mode=QueryMode.HYBRID,
            model_source="dashscope",
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["citations"][0]["chunk_id"], "c-1")
        self.assertIn("ospf.md#chunk:0", llm.requests[0].prompt)
        self.assertIn("<evidence>", llm.requests[0].prompt)

    def test_no_evidence_does_not_call_model(self) -> None:
        empty = _Search(SearchResult.empty())
        llm = _LLM(LLMResult(ModelStatus.SUCCESS, text="不应出现"))
        service = GroundedAnswerService(QueryService(empty, empty), lambda query: [1.0], {"dashscope": llm})

        result = service.answer(question="没有资料的问题", model_source="dashscope")

        self.assertEqual(result["status"], "no-evidence")
        self.assertEqual(llm.requests, [])
        self.assertEqual(result["citations"], [])

    def test_model_unavailable_preserves_evidence(self) -> None:
        dense = _Search(SearchResult.matches([_candidate(SearchChannel.DENSE, "c-2", "设备日志显示邻居重置。")]))
        lexical = _Search(SearchResult.empty())
        service = GroundedAnswerService(QueryService(dense, lexical), lambda query: [1.0], {})

        result = service.answer(question="邻居为什么重置？", model_source="local")

        self.assertEqual(result["status"], "model-unavailable")
        self.assertEqual(result["citations"][0]["chunk_id"], "c-2")

    def test_keyword_reranker_returns_stable_scores(self) -> None:
        result = KeywordReranker().rerank(
            type("Request", (), {"query": "MTU OSPF", "candidates": (("a", "检查 OSPF MTU"), ("b", "检查电源"))})()
        )

        self.assertEqual(result.status, ModelStatus.SUCCESS)
        self.assertEqual(result.scores[0][0], "a")

    def test_local_model_missing_configuration_is_safe(self) -> None:
        model = create_answer_models(load_profile(ProfileName.LOCAL_MILVUS), {})["local"]

        result = model.complete(LLMRequest("q"))

        self.assertEqual(result.status, ModelStatus.UNAVAILABLE)
        self.assertEqual(result.error_code.value, "unavailable")


if __name__ == "__main__":
    unittest.main()
