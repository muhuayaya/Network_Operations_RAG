"""加载 Golden Set，并明确引用、无证据和禁止行为。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class GoldenCase:
    case_id: str
    category: str
    question: str
    expected_source_ids: tuple[str, ...]
    expected_vendor: str
    expected_behavior: str
    principal_id: str | None = None
    site_id: str | None = None
    security_level: str | None = None


def load_golden_set(path: str | Path) -> tuple[GoldenCase, ...]:
    """加载并校验包含 15--80 项的确定性评测集。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not 15 <= len(payload) <= 80:
        raise ValueError("golden set must contain between 15 and 80 cases")
    cases = tuple(_case(item) for item in payload)
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("golden set case ids must be unique")
    return cases


def _case(value: Any) -> GoldenCase:
    if not isinstance(value, dict):
        raise TypeError("golden case must be an object")
    behavior = str(value.get("expected_behavior", ""))
    if behavior not in {"cite", "refuse_or_filter", "forbidden", "no_evidence"}:
        raise ValueError(f"unsupported expected behavior: {behavior}")
    source_ids = value.get("expected_source_ids", [])
    if not isinstance(source_ids, list):
        raise TypeError("expected_source_ids must be a list")
    if behavior == "no_evidence" and source_ids:
        raise ValueError("no_evidence cases cannot expect a source")
    if behavior == "forbidden" and not all(
        value.get(field) for field in ("principal_id", "site_id", "security_level")
    ):
        raise ValueError("forbidden cases require principal_id, site_id and security_level")
    return GoldenCase(
        case_id=_required(value, "case_id"),
        category=_required(value, "category"),
        question=_required(value, "question"),
        expected_source_ids=tuple(str(item) for item in source_ids),
        expected_vendor=_required(value, "expected_vendor"),
        expected_behavior=behavior,
        principal_id=str(value["principal_id"]) if value.get("principal_id") else None,
        site_id=str(value["site_id"]) if value.get("site_id") else None,
        security_level=str(value["security_level"]) if value.get("security_level") else None,
    )


def _required(value: dict[str, Any], field: str) -> str:
    result = str(value.get(field, "")).strip()
    if not result:
        raise ValueError(f"golden case field is required: {field}")
    return result
