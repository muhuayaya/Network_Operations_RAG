"""可运行的 demo-lite 索引和检索服务组合。

本模块是本地概念验证的组合边界。provider 凭据保存在环境变量中，
先构建带版本的 Dense 和 Lexical 索引，验证完成后才切换 SQLite 的 ``active`` 别名。
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sqlite3
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netops_copilot.application.demo_services import (
    DemoApplicationServices,
    Handler,
    QueryVectorizer,
)
from netops_copilot.application.evaluation import load_golden_set
from netops_copilot.application.indexing import VersionedIndexManager
from netops_copilot.application.indexing_service import CoordinatedIndexer
from netops_copilot.application.ports.indexing import IndexableChunk
from netops_copilot.application.ports.models import EmbeddingPort, EmbeddingRequest
from netops_copilot.application.ports.repositories import IndexVersion, RepositoryNotFoundError
from netops_copilot.application.query import QueryService
from netops_copilot.application.startup import IndexDescriptor, embedding_fingerprint
from netops_copilot.bootstrap import bootstrap
from netops_copilot.infrastructure.ingestion import (
    chunk_record,
    normalize_record,
    parse_path,
    protect_record,
)
from netops_copilot.infrastructure.persistence.sqlite import SqliteMetadataRepository
from netops_copilot.infrastructure.providers.http_transport import OpenAICompatibleHttpTransport
from netops_copilot.infrastructure.providers.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleEmbeddingAdapter,
)
from netops_copilot.infrastructure.retrieval.chroma import (
    ChromaDenseIndexWriter,
    ChromaDenseSearchAdapter,
)
from netops_copilot.infrastructure.retrieval.sqlite_fts import (
    SqliteFts5IndexWriter,
    SqliteFts5SearchAdapter,
)
from netops_copilot.settings import ProfileName, ProfileSettings, load_profile


class DemoRuntimeDependencyError(RuntimeError):
    """必需的本地运行时依赖未安装或未配置。"""


# text-embedding-v4 + Chroma cosine distance 的 demo-lite 校准门槛。
# 仅在 Lexical 没有命中时使用，避免把有明确词法证据的问题误判为无证据。
DEMO_MINIMUM_DENSE_SCORE = -0.4


@dataclass(frozen=True, slots=True)
class DemoBuildReport:
    """活动索引验证构建完成后返回的安全摘要。"""

    profile: ProfileName
    version_id: str
    collection_name: str
    embedding_fingerprint: str
    source_count: int
    chunk_count: int
    dense_count: int
    lexical_count: int
    active_alias: str


@dataclass(frozen=True, slots=True)
class DemoIndexInputs:
    """运行时和测试使用的已解析分块及来源数量。"""

    chunks: tuple[IndexableChunk, ...]
    source_count: int


def build_demo_runtime(
    profile: ProfileName,
    dataset_root: Path,
    runtime_dir: Path,
    version_id: str | None = None,
    *,
    embedding: EmbeddingPort | None = None,
    chroma_client: Any | None = None,
    environment: Mapping[str, str] | None = None,
) -> DemoBuildReport:
    """构建并激活一个 demo-lite 索引版本。

    可选的 ``embedding`` 和 ``chroma_client`` 参数用于测试替身；
    正常调用保持为空，使用已配置的百炼适配器和持久化 Chroma 客户端。
    """

    settings = load_profile(profile)
    _require_demo_profile(settings)
    inputs = load_demo_index_inputs(dataset_root)
    if not inputs.chunks:
        raise ValueError("demo dataset produced no indexable chunks")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    repository = SqliteMetadataRepository(runtime_dir / "metadata.sqlite3")
    manager = VersionedIndexManager(repository)
    lexical: SqliteFts5IndexWriter | None = None
    try:
        selected_embedding = embedding or _create_embedding(settings, environment)
        descriptor = next(
            provider for provider in bootstrap(profile).providers if provider.kind.value == "embedding"
        )
        fingerprint = embedding_fingerprint(descriptor)
        selected_version = version_id or _new_version_id(inputs.chunks)
        index_version = IndexVersion(selected_version, fingerprint, settings.index_schema_version)
        collection = manager.register(index_version)
        client = chroma_client or _persistent_chroma_client(runtime_dir / "chroma")
        dense = ChromaDenseIndexWriter(
            client,
            selected_embedding,
            collection_name_factory=lambda _: collection,
        )
        lexical = SqliteFts5IndexWriter(
            runtime_dir / "metadata.sqlite3",
            table_name_factory=lambda _: collection,
        )
        report = CoordinatedIndexer(dense, lexical, manager).index_and_activate(
            selected_version,
            inputs.chunks,
        )
    finally:
        if lexical is not None:
            lexical.close()
        repository.close()
    return DemoBuildReport(
        profile=profile,
        version_id=report.version_id,
        collection_name=collection,
        embedding_fingerprint=fingerprint,
        source_count=inputs.source_count,
        chunk_count=report.expected_count,
        dense_count=report.dense_count,
        lexical_count=report.lexical_count,
        active_alias=report.active.alias,
    )


def create_demo_services(
    profile: ProfileName,
    runtime_dir: Path,
    *,
    dataset_root: Path | None = None,
    embedding: EmbeddingPort | None = None,
    chroma_client: Any | None = None,
    environment: Mapping[str, str] | None = None,
) -> DemoApplicationServices:
    """为 REST 和 Streamlit 注入已配置的只读 QueryService。"""

    settings = load_profile(profile)
    _require_demo_profile(settings)
    repository = SqliteMetadataRepository(runtime_dir / "metadata.sqlite3")
    manager = VersionedIndexManager(repository)
    try:
        active = manager.active()
    finally:
        repository.close()
    selected_embedding = embedding or _create_embedding(settings, environment)
    client = chroma_client or _persistent_chroma_client(runtime_dir / "chroma")
    dense = ChromaDenseSearchAdapter(
        client.get_or_create_collection(name=active.collection_name, metadata={"hnsw:space": "cosine"})
    )
    lexical = SqliteFts5SearchAdapter(
        runtime_dir / "metadata.sqlite3",
        table_name=active.collection_name,
    )
    selected_dataset_root = dataset_root or runtime_dir.parent
    source_summary = _load_source_summary(runtime_dir / "ingestion_manifest.json")
    diagnose_handler = _load_demo_diagnosis_handler(selected_dataset_root)
    device_context_handler = _load_device_context_handler(selected_dataset_root)
    evaluation_summary = _load_evaluation_summary(selected_dataset_root / "evals" / "golden_set.json")
    trace_handler = _create_demo_trace_handler(source_summary, active)
    return DemoApplicationServices(
        query_service=QueryService(
            dense,
            lexical,
            minimum_dense_score=DEMO_MINIMUM_DENSE_SCORE,
        ),
        vectorizer=_EmbeddingVectorizer(selected_embedding),
        diagnose_handler=diagnose_handler,
        device_context_handler=device_context_handler,
        trace_handler=trace_handler,
        sources_handler=lambda _: source_summary,
        ingestion_handler=lambda payload: _confirm_demo_ingestion(payload, source_summary, active),
        evaluation_handler=lambda _: evaluation_summary,
        dependencies={
            "embedding": True,
            "dense-search": True,
            "lexical-search": True,
            "active-index": True,
        },
    )


def _load_source_summary(manifest_path: Path) -> dict[str, Any]:
    """读取确定性的摄取清单，并转换为安全的来源元数据。"""

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"unable to load ingestion manifest: {manifest_path}") from error
    records = payload.get("records")
    summary = payload.get("summary")
    if not isinstance(records, list) or not isinstance(summary, dict):
        raise TypeError("ingestion manifest has an invalid structure")
    sources: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            raise TypeError("ingestion manifest has an invalid record")
        chunk_ids = record.get("chunk_ids")
        if not isinstance(chunk_ids, list):
            raise TypeError("ingestion manifest record is missing chunk ids")
        sources.append(
            {
                "source_id": str(record.get("source_id", "")),
                "source_type": str(record.get("source_type", "")),
                "source_path": str(record.get("source_path", "")),
                "source_locator": str(record.get("source_locator", "")),
                "content_hash": str(record.get("content_hash", "")),
                "chunk_count": len(chunk_ids),
            }
        )
    return {
        "summary": {
            "source_count": int(summary.get("source_count", 0)),
            "record_count": int(summary.get("record_count", 0)),
            "chunk_count": int(summary.get("chunk_count", 0)),
            "content_hash": str(summary.get("content_hash", "")),
        },
        "sources": sources,
    }


def _load_evaluation_summary(golden_set_path: Path) -> dict[str, Any]:
    """描述随项目提供的 Golden Set，但不虚报尚未运行的指标。"""

    cases = load_golden_set(golden_set_path)
    return {
        "status": "not_run",
        "message": "Golden Set 已加载；尚未执行在线评测。",
        "golden_set": {
            "case_count": len(cases),
            "category_counts": dict(sorted(Counter(case.category for case in cases).items())),
            "expected_behavior_counts": dict(
                sorted(Counter(case.expected_behavior for case in cases).items())
            ),
        },
    }


def _load_demo_diagnosis_handler(dataset_root: Path) -> Handler:
    """创建由固定演示数据驱动的确定性事故研判处理器。"""

    scenarios = _read_json_array(dataset_root / "scenarios" / "incidents.json")
    alarms = _read_json_lines(dataset_root / "observations" / "alarms.jsonl")
    tickets = _read_json_lines(dataset_root / "tickets" / "tickets.jsonl")
    scenario_by_id = {str(scenario.get("scenario_id", "")): scenario for scenario in scenarios}

    def diagnose(payload: Mapping[str, Any]) -> dict[str, Any]:
        incident = payload.get("incident")
        if not isinstance(incident, Mapping):
            raise TypeError("incident must be an object")
        scenario_id = str(incident.get("scenario_id", "")).strip()
        scenario = scenario_by_id.get(scenario_id)
        if scenario is None:
            raise ValueError("场景 ID 在演示数据中不存在")
        expected_code = str(scenario.get("expected_alarm_code", ""))
        device_id = str(scenario.get("primary_device_id", ""))
        site_id = str(scenario.get("site_id", ""))
        matching_alarms = [
            _alarm_summary(alarm)
            for alarm in alarms
            if alarm.get("scenario_id") == scenario_id and alarm.get("device_id") == device_id
        ]
        matching_tickets = [
            _ticket_summary(ticket)
            for ticket in tickets
            if ticket.get("scenario_id") == scenario_id and ticket.get("device_id") == device_id
        ]
        if not matching_alarms:
            raise RuntimeError("demo dataset has no alarm evidence for the scenario")
        expected_evidence = scenario.get("expected_evidence")
        if not isinstance(expected_evidence, Mapping):
            raise TypeError("demo scenario has invalid expected evidence")
        candidates = payload.get("candidates", [])
        candidate_count = len(candidates) if isinstance(candidates, list) else 0
        return {
            "status": "analyzed",
            "read_only": True,
            "incident": {
                "scenario_id": scenario_id,
                "site_id": site_id,
                "primary_device_id": device_id,
                "alarm_code": expected_code,
                "title": str(scenario.get("title", "")),
            },
            "facts": [
                f"场景 {scenario_id} 的主设备为 {device_id}，站点为 {site_id}。",
                f"确定性告警代码为 {expected_code}，匹配告警 {len(matching_alarms)} 条。",
                f"匹配历史工单 {len(matching_tickets)} 条；请求携带候选证据 {candidate_count} 条。",
            ],
            "evidence": {
                "alarms": matching_alarms,
                "tickets": matching_tickets,
                "expected_snapshot_ids": {
                    "baseline": str(expected_evidence.get("baseline_snapshot_id", "")),
                    "current": str(expected_evidence.get("current_snapshot_id", "")),
                },
            },
            "verification_steps": [
                "收集设备和接口的只读状态，不下发配置。",
                "比对指定的基线与当前配置快照。",
                "将确认的事实和证据交由网络值班工程师人工处置。",
            ],
            "outcome": str(scenario.get("expected_outcome", "")),
        }

    return diagnose


def _load_device_context_handler(dataset_root: Path) -> Handler:
    """创建只读的设备、站点和拓扑上下文处理器。"""

    devices = _read_json_array(dataset_root / "inventory" / "devices.json")
    sites = _read_json_array(dataset_root / "inventory" / "sites.json")
    links = _read_json_array(dataset_root / "topology" / "links.json")
    device_by_id = {str(device.get("device_id", "")): device for device in devices}
    site_by_id = {str(site.get("site_id", "")): site for site in sites}

    def device_context(payload: Mapping[str, Any]) -> dict[str, Any]:
        device_id = str(payload.get("device_id", "")).strip()
        device = device_by_id.get(device_id)
        if device is None:
            raise ValueError("设备 ID 在演示清单中不存在")
        site_id = str(device.get("site_id", ""))
        site = site_by_id.get(site_id)
        if site is None:
            raise RuntimeError("demo device has no matching site")
        related_links = [
            dict(link)
            for link in links
            if link.get("a_device_id") == device_id or link.get("b_device_id") == device_id
        ]
        return {
            "read_only": True,
            "device": dict(device),
            "site": dict(site),
            "topology_links": related_links,
        }

    return device_context


def _create_demo_trace_handler(source_summary: Mapping[str, Any], active: Any) -> Handler:
    """将活动演示索引暴露为稳定的只读 Trace 记录。"""

    summary = source_summary.get("summary")
    if not isinstance(summary, Mapping):
        raise TypeError("active source summary is invalid")
    trace = {
        "trace_id": "demo-index-active",
        "trace_type": "index_activation",
        "profile": "demo-lite",
        "read_only": True,
        "versions": {
            "index_version": active.version.version_id,
            "embedding_fingerprint": active.version.embedding_fingerprint,
            "collection_name": active.collection_name,
        },
        "stages": [
            {
                "name": "source_manifest",
                "source_count": int(summary.get("source_count", 0)),
                "record_count": int(summary.get("record_count", 0)),
                "chunk_count": int(summary.get("chunk_count", 0)),
            },
            {"name": "active_alias", "alias": active.alias, "status": "active"},
        ],
        "degradation": [],
    }

    def get_trace(payload: Mapping[str, Any]) -> dict[str, Any]:
        trace_id = str(payload.get("trace_id", "demo-index-active")).strip()
        if trace_id != trace["trace_id"]:
            raise ValueError("Trace ID 在演示运行时中不存在")
        return trace

    return get_trace


def _read_json_array(path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"unable to load demo fixture: {path}") from error
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise TypeError(f"demo fixture must be an array of objects: {path}")
    return value


def _read_json_lines(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        values = [json.loads(line) for line in lines if line.strip()]
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"unable to load demo fixture: {path}") from error
    if not all(isinstance(item, dict) for item in values):
        raise TypeError(f"demo fixture must contain JSON objects: {path}")
    return values


def _alarm_summary(alarm: Mapping[str, Any]) -> dict[str, str]:
    return {
        "alarm_id": str(alarm.get("alarm_id", "")),
        "code": str(alarm.get("code", "")),
        "interface": str(alarm.get("interface", "")),
        "raised_at": str(alarm.get("raised_at", "")),
        "severity": str(alarm.get("severity", "")),
        "summary": str(alarm.get("summary", "")),
    }


def _ticket_summary(ticket: Mapping[str, Any]) -> dict[str, Any]:
    actions = ticket.get("actions", [])
    return {
        "ticket_id": str(ticket.get("ticket_id", "")),
        "status": str(ticket.get("status", "")),
        "symptoms": str(ticket.get("symptoms", "")),
        "cause": str(ticket.get("cause", "")),
        "actions": [str(action) for action in actions] if isinstance(actions, list) else [],
        "outcome": str(ticket.get("outcome", "")),
    }


def _confirm_demo_ingestion(
    payload: Mapping[str, Any],
    source_summary: Mapping[str, Any],
    active: Any,
) -> dict[str, Any]:
    """在保持演示只读的前提下，报告已有来源已经进入索引。"""

    source_id = str(payload.get("source_id", "")).strip()
    if not source_id:
        raise ValueError("来源 ID 不能为空")
    sources = source_summary.get("sources")
    if not isinstance(sources, list):
        raise TypeError("active source summary is invalid")
    source = next(
        (
            item
            for item in sources
            if isinstance(item, dict) and item.get("source_id") == source_id
        ),
        None,
    )
    if source is None:
        raise ValueError("来源 ID 在活动摄取清单中不存在")
    return {
        "status": "already_indexed",
        "message": "该来源已进入活动索引；demo 不会通过 API 重建或修改索引。",
        "source": source,
        "active_index": {
            "alias": active.alias,
            "version_id": active.version.version_id,
            "collection_name": active.collection_name,
        },
    }


def load_active_index_descriptor(runtime_dir: Path) -> IndexDescriptor | None:
    """读取活动演示索引绑定，供启动检查和 doctor 校验使用。"""

    database = runtime_dir / "metadata.sqlite3"
    if not database.exists():
        return None
    repository = SqliteMetadataRepository(database)
    try:
        active = VersionedIndexManager(repository).active()
    except (RepositoryNotFoundError, OSError, sqlite3.DatabaseError):
        return None
    finally:
        repository.close()
    return IndexDescriptor(
        collection_name=active.collection_name,
        schema_version=active.version.schema_version,
        embedding_fingerprint=active.version.embedding_fingerprint,
    )


def load_demo_index_inputs(dataset_root: Path) -> DemoIndexInputs:
    """以确定性方式解析、保护、规范化并切分演示数据。"""

    if not dataset_root.is_dir():
        raise ValueError(f"dataset directory does not exist: {dataset_root}")
    roots = {"knowledge", "inventory", "topology", "observations", "tickets", "scenarios"}
    paths = sorted(
        path
        for path in dataset_root.rglob("*")
        if path.is_file()
        and ".runtime" not in path.parts
        and path.relative_to(dataset_root).parts
        and path.relative_to(dataset_root).parts[0] in roots
    )
    chunks: list[IndexableChunk] = []
    for path in paths:
        for parsed in parse_path(path):
            protected = protect_record(parsed)
            normalized = normalize_record(protected)
            for chunk in chunk_record(protected):
                metadata = dict(normalized.metadata)
                metadata.update(
                    {
                        "source_id": normalized.source_id,
                        "source_locator": chunk.source_locator,
                        "content_hash": chunk.content_hash,
                        "security_level": normalized.security_level.value,
                    }
                )
                chunks.append(IndexableChunk(chunk.chunk_id, chunk.text, metadata))
    chunks.sort(key=lambda item: item.chunk_id)
    return DemoIndexInputs(tuple(chunks), len(paths))


class _EmbeddingVectorizer(QueryVectorizer):
    def __init__(self, embedding: EmbeddingPort) -> None:
        self._embedding = embedding

    def __call__(self, query: str) -> Sequence[float]:
        result = self._embedding.embed(EmbeddingRequest((query,)))
        if result.status.value != "success" or not result.vectors:
            code = result.error_code.value if result.error_code is not None else "unknown"
            raise DemoRuntimeDependencyError(f"Embedding 服务调用失败：{code}")
        return result.vectors[0]


def _create_embedding(settings: ProfileSettings, environment: Mapping[str, str] | None) -> EmbeddingPort:
    if settings.embedding.api_key_env is None or settings.embedding.base_url is None:
        raise DemoRuntimeDependencyError("Embedding 服务缺少 api_key_env 或 base_url 配置")
    transport = OpenAICompatibleHttpTransport(settings.embedding.base_url)
    config = OpenAICompatibleConfig(settings.embedding.model, settings.embedding.api_key_env)
    return OpenAICompatibleEmbeddingAdapter(transport, config, environment=environment)


def _persistent_chroma_client(path: Path) -> Any:
    try:
        chromadb = importlib.import_module("chromadb")
    except ImportError as error:
        raise DemoRuntimeDependencyError(
            "Chroma 运行时不可用，请先执行 `uv sync --extra demo-index`"
        ) from error
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path))


def _require_demo_profile(settings: ProfileSettings) -> None:
    if settings.profile is not ProfileName.DEMO_LITE:
        raise ValueError("the local runtime builder currently supports only the demo-lite profile")


def _new_version_id(chunks: Sequence[IndexableChunk]) -> str:
    digest = hashlib.sha256("\n".join(item.chunk_id for item in chunks).encode("utf-8")).hexdigest()[:10]
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    return f"v{timestamp}_{digest}"


__all__ = [
    "DemoBuildReport",
    "DemoIndexInputs",
    "DemoRuntimeDependencyError",
    "build_demo_runtime",
    "create_demo_services",
    "load_active_index_descriptor",
    "load_demo_index_inputs",
]
