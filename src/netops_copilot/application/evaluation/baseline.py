"""带版本的基线执行，不作未经验证的改进声明。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class EvaluationVersion(StrEnum):
    """已知的基线模式。"""

    DENSE_ONLY = "dense-only"
    LEXICAL_ONLY = "lexical-only"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid-rerank"


@dataclass(frozen=True, slots=True)
class BaselineReport:
    profile: str
    data_version: str
    model_version: str
    prompt_version: str
    index_version: str
    code_version: str
    results: Mapping[str, Any]

    def __post_init__(self) -> None:
        for field_name in ("profile", "data_version", "model_version", "prompt_version", "index_version", "code_version"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"baseline {field_name} cannot be empty")


class BaselineRunner:
    """运行每个可用检索模式，并保留全部版本标签。"""

    def run(
        self,
        *,
        profile: str,
        versions: Mapping[str, str],
        execute: Callable[[str], Any],
        modes: tuple[str, ...] | None = None,
    ) -> BaselineReport:
        required = ("data", "model", "prompt", "index", "code")
        missing = [name for name in required if not str(versions.get(name, "")).strip()]
        if missing:
            raise ValueError(f"baseline versions missing: {', '.join(missing)}")
        selected_modes = modes or tuple(item.value for item in EvaluationVersion)
        results = {mode: execute(mode) for mode in selected_modes}
        return BaselineReport(
            profile=profile,
            data_version=versions["data"],
            model_version=versions["model"],
            prompt_version=versions["prompt"],
            index_version=versions["index"],
            code_version=versions["code"],
            results=results,
        )
