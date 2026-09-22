"""在线评测的来源映射与授权评分边界。"""

from __future__ import annotations

import unittest
from typing import Any

from netops_copilot.application.authorization import QueryAuthorizationError
from netops_copilot.application.evaluation import GoldenCase
from tools.run_online_golden_eval import behavior_passed, execute_case, rank_sources


class _RejectingQueryService:
    def __init__(self) -> None:
        self.filters: Any = None

    def search(self, **kwargs: Any) -> Any:
        self.filters = kwargs["filters"]
        raise QueryAuthorizationError("denied")


class _Services:
    def __init__(self) -> None:
        self.query_service = _RejectingQueryService()

    def vectorizer(self, query: str) -> Any:
        raise AssertionError("受限请求不应调用远程 Embedding")


class OnlineGoldenEvaluationTests(unittest.TestCase):
    def test_forbidden_case_uses_identity_without_embedding(self) -> None:
        case = GoldenCase(
            "restricted-1", "security", "受限资料", ("restricted-doc",), "Generic",
            "forbidden", "principal-basic-demo", "site-gz-dc", "restricted",
        )
        services = _Services()
        principals = {
            "principal-basic-demo": {
                "principal_id": "principal-basic-demo",
                "security_level": "basic",
                "allowed_site_ids": ["site-gz-dc"],
            }
        }

        response = execute_case(case, services, principals, 10)

        self.assertEqual(response["state"], "forbidden")
        self.assertTrue(behavior_passed(case, response))
        self.assertEqual(services.query_service.filters.security_level, "restricted")

    def test_no_evidence_requires_zero_candidates_and_state(self) -> None:
        case = GoldenCase("missing-1", "no_answer", "不存在的资料", (), "Generic", "no_evidence")
        self.assertFalse(behavior_passed(case, {"state": "healthy", "candidates": [{"chunk_id": "x"}]}))
        self.assertTrue(behavior_passed(case, {"state": "zero-evidence", "candidates": []}))

    def test_source_ranking_deduplicates_chunks(self) -> None:
        ranked, unmapped = rank_sources(
            [{"chunk_id": "a1"}, {"chunk_id": "a2"}, {"chunk_id": "b1"}],
            {"a1": "source-a", "a2": "source-a", "b1": "source-b"},
        )
        self.assertEqual(ranked, ["source-a", "source-b"])
        self.assertEqual(unmapped, [])
