"""使用现有 demo-lite 活动索引运行在线 Golden Set 检索评测。"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from netops_copilot.application.authorization import QueryAuthorizationError
from netops_copilot.application.demo_runtime import DEMO_MINIMUM_DENSE_SCORE, create_demo_services
from netops_copilot.application.evaluation import (
    GoldenCase,
    latency_percentile,
    load_golden_set,
    mrr,
    ndcg,
    recall_at_k,
)
from netops_copilot.application.indexing import VersionedIndexManager
from netops_copilot.application.ports.search import SearchFilters
from netops_copilot.domain.shared.identity import Principal, SecurityLevel
from netops_copilot.infrastructure.persistence.sqlite import SqliteMetadataRepository
from netops_copilot.settings import ProfileName, load_profile


def active_index_snapshot(runtime_dir: Path) -> dict[str, Any]:
    """读取当前活动版本；缺失时中止评测，不创建新索引。"""
    database = runtime_dir / "metadata.sqlite3"
    if not database.is_file():
        raise RuntimeError(f"活动索引元数据库不存在：{database}")
    repository = SqliteMetadataRepository(database)
    try:
        active = VersionedIndexManager(repository).active()
        return {
            "alias": active.alias,
            "version_id": active.version.version_id,
            "collection_name": active.collection_name,
            "embedding_fingerprint": active.version.embedding_fingerprint,
            "schema_version": active.version.schema_version,
        }
    finally:
        repository.close()


def source_by_chunk(manifest: dict[str, Any]) -> dict[str, str]:
    """用摄取清单还原来源；词法检索候选未携带 source_id。"""
    mapping: dict[str, str] = {}
    for record in manifest["records"]:
        source_id = record["source_id"]
        for chunk_id in record["chunk_ids"]:
            if chunk_id in mapping and mapping[chunk_id] != source_id:
                raise ValueError(f"Chunk 映射到多个来源：{chunk_id}")
            mapping[chunk_id] = source_id
    return mapping


def rank_sources(candidates: list[dict[str, Any]], mapping: dict[str, str]) -> tuple[list[str], list[str]]:
    """按候选顺序去重来源，并记录未能追溯来源的 Chunk。"""
    ranked: list[str] = []
    unmapped: list[str] = []
    for candidate in candidates:
        chunk_id = str(candidate["chunk_id"])
        source_id = mapping.get(chunk_id)
        if source_id is None:
            unmapped.append(chunk_id)
        elif source_id not in ranked:
            ranked.append(source_id)
    return ranked, unmapped


def execute_case(case: GoldenCase, services: Any, principals: dict[str, Any], limit: int) -> dict[str, Any]:
    """对受限请求使用真实授权用例，其余问题使用常规演示检索入口。"""
    if case.expected_behavior != "forbidden":
        return services.query({"query": case.question, "mode": "hybrid", "limit": limit})
    principal_data = principals[case.principal_id]
    principal = Principal(
        principal_data["principal_id"],
        SecurityLevel(principal_data["security_level"]),
        frozenset(principal_data["allowed_site_ids"]),
    )
    if services.query_service is None:
        raise RuntimeError("授权检索服务未配置")
    try:
        result = services.query_service.search(
            query=case.question,
            query_vector=(0.0,),
            filters=SearchFilters(site_id=case.site_id, security_level=case.security_level),
            principal=principal,
            limit=limit,
        )
    except QueryAuthorizationError:
        return {"state": "forbidden", "candidates": [], "degradation": [], "denied": True}
    return {
        "state": result.state.value,
        "candidates": [{"chunk_id": item.chunk_id} for item in result.candidates],
        "degradation": list(result.degradation),
        "denied": False,
    }


def behavior_passed(case: GoldenCase, response: dict[str, Any]) -> bool | None:
    """只评分当前检索/授权链路能够直接证明的行为。"""
    if case.expected_behavior == "no_evidence":
        return response["state"] == "zero-evidence" and not response["candidates"]
    if case.expected_behavior == "forbidden":
        return bool(response.get("denied", False))
    return None


def run(dataset_root: Path, runtime_dir: Path, limit: int) -> dict[str, Any]:
    if limit < 5:
        raise ValueError("limit 必须至少为 5，才能计算 Hit@5")
    before = active_index_snapshot(runtime_dir)
    golden_path = dataset_root / "evals" / "golden_set.json"
    cases = load_golden_set(golden_path)
    manifest = json.loads((runtime_dir / "ingestion_manifest.json").read_text(encoding="utf-8"))
    mapping = source_by_chunk(manifest)
    principals = {
        item["principal_id"]: item
        for item in json.loads((dataset_root / "access" / "principals.json").read_text(encoding="utf-8"))
    }
    settings = load_profile(ProfileName.DEMO_LITE)
    services = create_demo_services(ProfileName.DEMO_LITE, runtime_dir, dataset_root=dataset_root)

    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        started = time.perf_counter()
        try:
            response = execute_case(case, services, principals, limit)
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            ranked, unmapped = rank_sources(response["candidates"], mapping)
            expected = set(case.expected_source_ids)
            hit_at_5 = bool(expected & set(ranked[:5])) if case.expected_behavior == "cite" else None
            behavior_pass = behavior_passed(case, response)
            result = {
                "case_id": case.case_id,
                "category": case.category,
                "expected_behavior": case.expected_behavior,
                "expected_source_ids": list(case.expected_source_ids),
                "principal_id": case.principal_id,
                "ranked_source_ids": ranked,
                "unmapped_chunk_ids": unmapped,
                "candidate_count": len(response["candidates"]),
                "state": response["state"],
                "degradation": response["degradation"],
                "latency_ms": elapsed_ms,
                "scoring": case.expected_behavior,
                "behavior_pass": behavior_pass,
                "hit_at_5": hit_at_5,
                "recall_at_5": recall_at_k(expected, ranked, 5) if case.expected_behavior == "cite" else None,
                "mrr": mrr(expected, ranked) if case.expected_behavior == "cite" else None,
                "ndcg_at_5": ndcg(expected, ranked, 5) if case.expected_behavior == "cite" else None,
            }
        except (ConnectionError, KeyError, OSError, PermissionError, RuntimeError, TimeoutError, TypeError, ValueError) as error:
            result = {
                "case_id": case.case_id,
                "category": case.category,
                "expected_behavior": case.expected_behavior,
                "expected_source_ids": list(case.expected_source_ids),
                "state": "error",
                "error_type": type(error).__name__,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "scoring": case.expected_behavior,
                "behavior_pass": False if case.expected_behavior in {"no_evidence", "forbidden"} else None,
                "hit_at_5": False if case.expected_behavior == "cite" else None,
                "recall_at_5": 0.0 if case.expected_behavior == "cite" else None,
                "mrr": 0.0 if case.expected_behavior == "cite" else None,
                "ndcg_at_5": 0.0 if case.expected_behavior == "cite" else None,
            }
        results.append(result)
        if index % 10 == 0 or index == len(cases):
            print(f"已评测 {index}/{len(cases)} 条", flush=True)

    after = active_index_snapshot(runtime_dir)
    if after != before:
        raise RuntimeError("评测期间活动索引发生变化，结果不可用于基线")

    scored = [item for item in results if item["scoring"] == "cite"]
    no_evidence = [item for item in results if item["scoring"] == "no_evidence"]
    forbidden = [item for item in results if item["scoring"] == "forbidden"]
    latencies = [item["latency_ms"] for item in results]
    states = Counter(item["state"] for item in results)
    degradations = Counter(reason for item in results for reason in item.get("degradation", []))
    return {
        "kind": "online_golden_retrieval",
        "profile": "demo-lite",
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "hybrid",
        "limit": limit,
        "minimum_dense_score": DEMO_MINIMUM_DENSE_SCORE,
        "active_index": before,
        "active_index_unchanged": True,
        "embedding_model": settings.embedding.model,
        "llm_model_configured_but_not_called": settings.llm.model,
        "dataset_content_hash": manifest["summary"]["content_hash"],
        "golden_set_sha256": hashlib.sha256(golden_path.read_bytes()).hexdigest(),
        "summary": {
            "case_count": len(results),
            "state_counts": dict(sorted(states.items())),
            "degradation_counts": dict(sorted(degradations.items())),
            "cite_case_count": len(scored),
            "hit_at_5": round(sum(bool(item["hit_at_5"]) for item in scored) / len(scored), 4),
            "mean_recall_at_5": round(mean(item["recall_at_5"] for item in scored), 4),
            "mean_mrr": round(mean(item["mrr"] for item in scored), 4),
            "mean_ndcg_at_5": round(mean(item["ndcg_at_5"] for item in scored), 4),
            "no_evidence_case_count": len(no_evidence),
            "no_evidence_accuracy": round(
                sum(bool(item["behavior_pass"]) for item in no_evidence) / len(no_evidence), 4
            ) if no_evidence else None,
            "forbidden_case_count": len(forbidden),
            "forbidden_accuracy": round(
                sum(bool(item["behavior_pass"]) for item in forbidden) / len(forbidden), 4
            ) if forbidden else None,
            "behavior_unscored_count": len(results) - len(scored) - len(no_evidence) - len(forbidden),
            "p50_latency_ms": latency_percentile(latencies, 50),
            "p95_latency_ms": latency_percentile(latencies, 95),
            "unmapped_chunk_count": sum(len(item.get("unmapped_chunk_ids", [])) for item in results),
        },
        "limitations": [
            "来源排序指标只对 cite 题目评分；no_evidence 要求零候选且状态为 zero-evidence；forbidden 要求基础身份在检索前被拒绝。",
            "受限请求通过应用层 QueryService 的身份授权路径评测，未经过 REST 的身份认证层。",
            "当前服务只返回候选证据，不生成最终答案，因此不能据此评价回答或引用准确率。",
            "引用题和无证据题的延迟包含远程 Embedding 与本地检索；受限请求在授权阶段本地拒绝，不调用 Embedding。均不包含 FastAPI 网络传输或 LLM 生成。",
        ],
        "cases": results,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# demo-lite 在线 Golden Set 检索评测",
        "",
        f"- 生成时间（UTC）：{report['generated_at']}",
        f"- 活动索引版本：`{report['active_index']['version_id']}`（评测前后未变化）",
        f"- 数据哈希：`{report['dataset_content_hash']}`",
        f"- Embedding：`{report['embedding_model']}`；检索模式：`{report['mode']}`；返回上限：{report['limit']}",
        f"- 无证据门槛：Dense raw score `< {report['minimum_dense_score']}` 且 Lexical 无命中时返回 `zero-evidence`",
        "",
        "## 结果",
        "",
        "| 指标 | 结果 |",
        "| --- | ---: |",
        f"| 实际查询数 | {summary['case_count']} |",
        f"| 查询状态 | {json.dumps(summary['state_counts'], ensure_ascii=False)} |",
        f"| 降级原因 | {json.dumps(summary['degradation_counts'], ensure_ascii=False)} |",
        f"| 来源 / 无证据 / 权限题数 | {summary['cite_case_count']} / {summary['no_evidence_case_count']} / {summary['forbidden_case_count']} |",
        f"| 来源命中率 Hit@5 | {summary['hit_at_5']:.1%} |",
        f"| 平均来源 Recall@5 | {summary['mean_recall_at_5']:.1%} |",
        f"| 平均 MRR | {summary['mean_mrr']:.4f} |",
        f"| 平均 nDCG@5 | {summary['mean_ndcg_at_5']:.4f} |",
        f"| 无证据识别率 | {summary['no_evidence_accuracy']:.1%} |",
        f"| 基础身份受限请求拒绝率 | {summary['forbidden_accuracy']:.1%} |",
        f"| 未评分行为题 | {summary['behavior_unscored_count']} |",
        f"| 延迟 p50 / p95 | {summary['p50_latency_ms']:.2f} / {summary['p95_latency_ms']:.2f} ms |",
        f"| 未能映射来源的候选 Chunk | {summary['unmapped_chunk_count']} |",
        "",
        "来源指标按候选顺序去重 source_id 后计算；出错的引用题计为未命中。",
        "本次评测的无证据题使用当前 demo-lite 校准门槛；若更换 Embedding 模型、距离度量或检索后端，需要重新校准并复跑评测。",
        "",
        "## 评测边界",
        "",
    ]
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend([
        "",
        "## 逐题结果",
        "",
        "| 题号 | 类型 | 预期行为 | 状态 | Hit@5 | 行为通过 | 耗时 ms | 首位来源 |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | --- |",
    ])
    for item in report["cases"]:
        ranked = item.get("ranked_source_ids", [])
        hit = "—" if item["hit_at_5"] is None else ("是" if item["hit_at_5"] else "否")
        passed = "—" if item["behavior_pass"] is None else ("是" if item["behavior_pass"] else "否")
        lines.append(
            f"| {item['case_id']} | {item['category']} | {item['expected_behavior']} | "
            f"{item['state']} | {hit} | {passed} | {item['latency_ms']:.2f} | "
            f"{ranked[0] if ranked else '—'} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=root / "datasets" / "demo")
    parser.add_argument("--runtime-dir", type=Path, default=root / "datasets" / "demo" / ".runtime")
    parser.add_argument("--report-dir", type=Path, default=root / "reports" / "evaluation")
    parser.add_argument("--limit", type=int, default=10)
    arguments = parser.parse_args()
    report = run(arguments.dataset_root, arguments.runtime_dir, arguments.limit)
    arguments.report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stem = f"demo-lite-hybrid-{stamp}"
    json_path = arguments.report_dir / f"{stem}.json"
    markdown_path = arguments.report_dir / f"{stem}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"report": str(markdown_path), "details": str(json_path), "summary": report["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
