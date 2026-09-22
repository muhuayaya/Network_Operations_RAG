"""索引前秘密检测和确定性脱敏策略。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType

from netops_copilot.infrastructure.ingestion.parsers import ParsedRecord


class SensitiveAction(StrEnum):
    """检测到敏感字段后的策略动作。"""

    REJECT = "reject"
    MASK = "mask"


@dataclass(frozen=True, slots=True)
class RedactionPolicy:
    """针对常见网络凭据形式的小型可审计规则集。"""

    action: SensitiveAction = SensitiveAction.REJECT
    replacement: str = "[REDACTED]"

    def __post_init__(self) -> None:
        if not self.replacement.strip():
            raise ValueError("redaction replacement cannot be blank")


@dataclass(frozen=True, slots=True)
class SensitiveFinding:
    """可安全记录日志的非秘密发现元数据。"""

    field: str
    line: int | None = None


class SensitiveDataError(ValueError):
    """记录违反索引前策略时抛出的异常。"""

    def __init__(self, record: ParsedRecord, findings: tuple[SensitiveFinding, ...]) -> None:
        self.source_id = record.source_id
        self.findings = findings
        fields = ", ".join(sorted({finding.field for finding in findings}))
        super().__init__(f"sensitive data rejected for source {record.source_id}: {fields}")


_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("password", re.compile(r"(?im)\bpassword\s*[:=]\s*[^\s,;]+")),
    ("secret", re.compile(r"(?im)\b(?:secret|client_secret)\s*[:=]\s*[^\s,;]+")),
    ("token", re.compile(r"(?im)\b(?:token|api[_-]?key|access[_-]?key)\s*[:=]\s*[^\s,;]+")),
    ("authorization", re.compile(r"(?im)\bauthorization\s*:\s*bearer\s+[^\s]+")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("snmp_community", re.compile(r"(?im)\b(?:snmp[_-]?community|community)\s*[:=]\s*[^\s,;]+")),
)


def protect_record(record: ParsedRecord, policy: RedactionPolicy | None = None) -> ParsedRecord:
    """检测内容/元数据中的秘密，并在索引前拒绝或掩码。"""
    policy = policy or RedactionPolicy()
    metadata_text = "\n".join(f"{key}: {value}" for key, value in record.metadata.items())
    findings = _findings(record.content + "\n" + metadata_text)
    if not findings:
        return record
    if policy.action is SensitiveAction.REJECT:
        raise SensitiveDataError(record, findings)
    redacted_content = _mask(record.content, policy.replacement)
    redacted_metadata = {
        key: _mask(value, policy.replacement) for key, value in record.metadata.items()
    }
    digest = hashlib.sha256(redacted_content.encode("utf-8")).hexdigest()
    return replace(
        record,
        content=redacted_content,
        metadata=MappingProxyType(redacted_metadata),
        content_hash=digest,
    )


def _findings(text: str) -> tuple[SensitiveFinding, ...]:
    findings: list[SensitiveFinding] = []
    for field, pattern in _RULES:
        for match in pattern.finditer(text):
            findings.append(SensitiveFinding(field, text.count("\n", 0, match.start()) + 1))
    return tuple(findings)


def _mask(text: str, replacement: str) -> str:
    masked = text
    for _, pattern in _RULES:
        masked = pattern.sub(lambda match: _mask_match(match, replacement), masked)
    return masked


def _mask_match(match: re.Match[str], replacement: str) -> str:
    value = match.group(0)
    separator = "=" if "=" in value else ":"
    prefix = value.split(separator, 1)[0]
    if value.startswith("-----BEGIN"):
        return replacement
    return f"{prefix}{separator} {replacement}"
