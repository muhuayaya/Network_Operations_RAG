"""透明的告警与事故关联规则。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class IncidentSignal:
    """确定性关联使用的规范化事故事实。"""

    incident_id: str
    device_id: str
    occurred_at: datetime
    interface: str | None = None
    protocol_state: str | None = None
    topology_neighbors: frozenset[str] = frozenset()
    recent_change_paths: frozenset[str] = frozenset()
    text: str = ""


@dataclass(frozen=True, slots=True)
class CorrelationMatch:
    """一个候选项及其得分所依据的明确规则。"""

    incident_id: str
    score: int
    reasons: tuple[str, ...]


class AlarmCorrelator:
    """使用固定规则对信号评分，并以确定性规则打破平局。"""

    def __init__(self, *, time_window_seconds: int = 900) -> None:
        if time_window_seconds < 1:
            raise ValueError("time window must be positive")
        self._time_window_seconds = time_window_seconds

    def correlate(
        self,
        primary: IncidentSignal,
        candidates: Iterable[IncidentSignal],
    ) -> tuple[CorrelationMatch, ...]:
        matches: list[CorrelationMatch] = []
        for candidate in candidates:
            if candidate.incident_id == primary.incident_id:
                continue
            score = 0
            reasons: list[str] = []
            if candidate.device_id == primary.device_id:
                score += 5
                reasons.append("same-device")
            if primary.interface and candidate.interface == primary.interface:
                score += 4
                reasons.append("same-interface")
            if abs((candidate.occurred_at - primary.occurred_at).total_seconds()) <= self._time_window_seconds:
                score += 3
                reasons.append("within-time-window")
            if primary.protocol_state and candidate.protocol_state == primary.protocol_state:
                score += 3
                reasons.append("same-protocol-state")
            if primary.topology_neighbors & candidate.topology_neighbors:
                score += 2
                reasons.append("shared-topology-neighbor")
            if primary.recent_change_paths & candidate.recent_change_paths:
                score += 2
                reasons.append("shared-recent-change")
            if _similar_terms(primary.text, candidate.text):
                score += 1
                reasons.append("similar-ticket-text")
            if score:
                matches.append(CorrelationMatch(candidate.incident_id, score, tuple(reasons)))
        matches.sort(key=lambda match: (-match.score, match.incident_id))
        return tuple(matches)


def _similar_terms(left: str, right: str) -> bool:
    left_terms = {term.lower() for term in left.split() if len(term) >= 4}
    right_terms = {term.lower() for term in right.split() if len(term) >= 4}
    return bool(left_terms & right_terms)
