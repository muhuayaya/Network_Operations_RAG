"""CLI 使用的确定性演示数据生成、重置和摄取操作。"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from netops_copilot.infrastructure.ingestion import (
    chunk_record,
    normalize_record,
    parse_path,
    protect_record,
)


@dataclass(frozen=True, slots=True)
class IngestSummary:
    """演示数据成功摄取后写出的稳定摘要。"""

    source_count: int
    record_count: int
    chunk_count: int
    content_hash: str


def reset_runtime(runtime_dir: Path) -> None:
    """只删除明确指定范围内的生成运行时目录。"""
    if runtime_dir.exists():
        if not runtime_dir.is_dir() or runtime_dir.is_symlink():
            raise ValueError("运行时路径必须是目录")
        shutil.rmtree(runtime_dir)


def ingest_dataset(dataset_root: Path, runtime_dir: Path) -> IngestSummary:
    """根据来源文件重建确定性清单，但不编辑来源文件。"""
    if not dataset_root.is_dir():
        raise ValueError(f"dataset directory does not exist: {dataset_root}")
    ingestable_roots = {"knowledge", "inventory", "topology", "observations", "tickets", "scenarios"}
    paths = sorted(
        path
        for path in dataset_root.rglob("*")
        if path.is_file()
        and ".runtime" not in path.parts
        and path.relative_to(dataset_root).parts[0] in ingestable_roots
    )
    records = []
    chunk_count = 0
    for path in paths:
        parsed_records = parse_path(path)
        for parsed in parsed_records:
            protected = protect_record(parsed)
            normalized = normalize_record(protected)
            chunks = chunk_record(protected)
            chunk_count += len(chunks)
            records.append(
                {
                    "source_id": normalized.source_id,
                    "source_type": normalized.source_type.value,
                    "source_path": path.relative_to(dataset_root).as_posix(),
                    "source_locator": normalized.source_locator,
                    "content_hash": normalized.content_hash,
                    "chunk_ids": [chunk.chunk_id for chunk in chunks],
                }
            )
    records.sort(key=lambda item: (item["source_path"], item["source_id"], item["source_locator"]))
    canonical = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    summary = IngestSummary(
        source_count=len(paths),
        record_count=len(records),
        chunk_count=chunk_count,
        content_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "ingestion_manifest.json").write_text(
        json.dumps({"summary": asdict(summary), "records": records}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary
