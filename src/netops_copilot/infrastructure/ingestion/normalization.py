"""面向厂商的运维记录元数据规范化。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from netops_copilot.domain.inventory import DataSecurityLevel, OsFamily, Vendor
from netops_copilot.domain.knowledge import SourceType
from netops_copilot.infrastructure.ingestion.parsers import ParsedRecord


class NormalizationError(ValueError):
    """来源元数据无法符合领域一致性时抛出的异常。"""


@dataclass(frozen=True, slots=True)
class NormalizedRecord:
    """由索引和引用层共享的规范记录元数据。"""

    source_id: str
    content: str
    source_type: SourceType
    vendor: Vendor | None
    model: str | None
    os_family: OsFamily | None
    os_version: str | None
    site_id: str | None
    device_id: str | None
    security_level: DataSecurityLevel
    effective_at: datetime
    source_locator: str
    content_hash: str
    metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
            raise ValueError("normalized effective_at must be timezone-aware")
        object.__setattr__(self, "effective_at", self.effective_at.astimezone(UTC))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


def normalize_record(record: ParsedRecord) -> NormalizedRecord:
    """规范化别名，同时保留所有安全来源元数据。"""
    metadata = dict(record.metadata)
    vendor = _normalize_vendor(metadata.get("vendor"))
    os_family = _normalize_os(metadata.get("os_family"), vendor)
    source_type = _normalize_source_type(metadata.get("source_type"))
    security_level = _normalize_security(metadata.get("security_level"))
    effective_at = _normalize_datetime(metadata.get("effective_at"))
    canonical = dict(metadata)
    if vendor is not None:
        canonical["vendor"] = vendor.value
    if os_family is not None:
        canonical["os_family"] = os_family.value
    canonical["source_type"] = source_type.value
    canonical["security_level"] = security_level.value
    canonical["effective_at"] = effective_at.isoformat()
    return NormalizedRecord(
        source_id=record.source_id,
        content=record.content,
        source_type=source_type,
        vendor=vendor,
        model=metadata.get("model"),
        os_family=os_family,
        os_version=metadata.get("os_version"),
        site_id=metadata.get("site_id"),
        device_id=metadata.get("device_id"),
        security_level=security_level,
        effective_at=effective_at,
        source_locator=record.location.locator,
        content_hash=record.content_hash,
        metadata=canonical,
    )


def _normalize_vendor(value: str | None) -> Vendor | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized == "generic":
        return None
    aliases = {
        "huawei": Vendor.HUAWEI,
        "华为": Vendor.HUAWEI,
        "h3c": Vendor.H3C,
        "hpe": Vendor.H3C,
        "ruijie": Vendor.RUIJIE,
        "锐捷": Vendor.RUIJIE,
        "cisco": Vendor.CISCO,
        "cisco-compatible": Vendor.CISCO,
    }
    try:
        return aliases[normalized]
    except KeyError as error:
        raise NormalizationError(f"unsupported vendor alias: {value}") from error


def _normalize_os(value: str | None, vendor: Vendor | None) -> OsFamily | None:
    if value is None and vendor is None:
        return None
    normalized = (value or "").strip().lower().removesuffix(" concept")
    if normalized in {"", "generic", "unknown", "n/a", "sop", "manual"}:
        return None
    aliases = {
        "vrp": OsFamily.VRP,
        "huawei vrp": OsFamily.VRP,
        "comware": OsFamily.COMWARE,
        "h3c comware": OsFamily.COMWARE,
        "rgos": OsFamily.RGOS,
        "ruijie rgos": OsFamily.RGOS,
        "ios": OsFamily.IOS,
        "ios-xe": OsFamily.IOS,
    }
    if normalized:
        try:
            return aliases[normalized]
        except KeyError as error:
            raise NormalizationError(f"unsupported OS family alias: {value}") from error
    defaults = {
        Vendor.HUAWEI: OsFamily.VRP,
        Vendor.H3C: OsFamily.COMWARE,
        Vendor.RUIJIE: OsFamily.RGOS,
        Vendor.CISCO: OsFamily.IOS,
    }
    return defaults.get(vendor) if vendor is not None else None


def _normalize_source_type(value: str | None) -> SourceType:
    aliases = {
        "manual": SourceType.MANUAL,
        "markdown": SourceType.MANUAL,
        "vendor_reference": SourceType.MANUAL,
        "sop": SourceType.SOP,
        "ticket": SourceType.TICKET,
        "alarm": SourceType.ALARM,
        "configuration": SourceType.CONFIGURATION,
        "config": SourceType.CONFIGURATION,
        "topology": SourceType.TOPOLOGY,
    }
    normalized = (value or "manual").strip().lower()
    try:
        return aliases[normalized]
    except KeyError as error:
        raise NormalizationError(f"unsupported source type: {value}") from error


def _normalize_security(value: str | None) -> DataSecurityLevel:
    normalized = (value or DataSecurityLevel.INTERNAL.value).strip().lower()
    try:
        return DataSecurityLevel(normalized)
    except ValueError as error:
        raise NormalizationError(f"unsupported security level: {value}") from error


def _normalize_datetime(value: str | None) -> datetime:
    if value is None:
        return datetime(1970, 1, 1, tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise NormalizationError("effective_at must be ISO-8601") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
