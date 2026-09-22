"""身份和权限级别值对象。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SecurityLevel(StrEnum):
    """概念验证支持的证据权限级别。"""

    BASIC = "basic"
    RESTRICTED = "restricted"


@dataclass(frozen=True, slots=True)
class Principal:
    """已认证调用方及其可读取的证据范围。"""

    subject_id: str
    security_level: SecurityLevel
    allowed_site_ids: frozenset[str]

    def can_access(self, site_id: str, security_level: SecurityLevel) -> bool:
        """返回该主体是否可以检索给定范围内的证据。"""
        return site_id in self.allowed_site_ids and (
            self.security_level is SecurityLevel.RESTRICTED
            or security_level is SecurityLevel.BASIC
        )
