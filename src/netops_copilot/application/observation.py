"""有边界且可审计的设备观测编排。"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from enum import StrEnum


class ObservationStatus(StrEnum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    ERROR = "error"
    OUTPUT_LIMIT = "output-limit"


@dataclass(frozen=True, slots=True)
class ObservationLimits:
    max_targets: int = 8
    max_concurrency: int = 4
    timeout_seconds: float = 3.0
    max_output_chars: int = 20_000

    def __post_init__(self) -> None:
        if min(self.max_targets, self.max_concurrency, self.max_output_chars) < 1 or self.timeout_seconds <= 0:
            raise ValueError("observation limits must be positive")


@dataclass(frozen=True, slots=True)
class ObservationResult:
    target_id: str
    status: ObservationStatus
    facts: object | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ObservationAudit:
    target_id: str
    operation: str
    status: ObservationStatus


class ObservationCoordinator:
    """只执行有边界的读取操作，并为每个目标保留可审计结果。"""

    def __init__(self, limits: ObservationLimits | None = None) -> None:
        self._limits = limits or ObservationLimits()

    def collect(
        self,
        target_ids: Sequence[str],
        reader: Callable[[str], object],
        *,
        operation: str = "read",
    ) -> tuple[tuple[ObservationResult, ...], tuple[ObservationAudit, ...]]:
        if not target_ids or len(target_ids) > self._limits.max_targets:
            raise ValueError("target count exceeds observation limit")
        if any(not target.strip() for target in target_ids) or len(set(target_ids)) != len(target_ids):
            raise ValueError("targets must be unique and non-blank")
        results: list[ObservationResult] = []
        audits: list[ObservationAudit] = []
        with ThreadPoolExecutor(max_workers=min(self._limits.max_concurrency, len(target_ids))) as executor:
            futures = {target: executor.submit(reader, target) for target in target_ids}
            for target in target_ids:
                result = self._resolve(target, futures[target])
                results.append(result)
                audits.append(ObservationAudit(target, operation, result.status))
        return tuple(results), tuple(audits)

    def _resolve(self, target: str, future: Future[object]) -> ObservationResult:
        try:
            facts = future.result(timeout=self._limits.timeout_seconds)
        except FutureTimeoutError:
            future.cancel()
            return ObservationResult(target, ObservationStatus.TIMEOUT, error_code="timeout")
        except TimeoutError:
            return ObservationResult(target, ObservationStatus.TIMEOUT, error_code="timeout")
        except (OSError, RuntimeError, ValueError):
            return ObservationResult(target, ObservationStatus.ERROR, error_code="observation-error")
        try:
            encoded = json.dumps(facts, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return ObservationResult(target, ObservationStatus.ERROR, error_code="invalid-output")
        if len(encoded) > self._limits.max_output_chars:
            return ObservationResult(target, ObservationStatus.OUTPUT_LIMIT, error_code="output-limit")
        return ObservationResult(target, ObservationStatus.SUCCESS, facts=facts)
