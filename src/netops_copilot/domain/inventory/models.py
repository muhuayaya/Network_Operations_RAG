"""不可变的资产实体和拓扑不变量。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from netops_copilot.domain.shared.time import require_utc


class Vendor(StrEnum):
    """确定性演示数据中表示的厂商。"""

    HUAWEI = "Huawei"
    H3C = "H3C"
    RUIJIE = "Ruijie"
    CISCO = "Cisco"


class OsFamily(StrEnum):
    """过滤和规范化使用的厂商操作系统族。"""

    VRP = "VRP"
    COMWARE = "Comware"
    RGOS = "RGOS"
    IOS = "IOS"


class DeviceRole(StrEnum):
    """网络设备的运维角色。"""

    CORE = "core"
    DISTRIBUTION = "distribution"
    EDGE = "edge"
    ACCESS = "access"


class DataSecurityLevel(StrEnum):
    """站点和证据附带的安全级别。"""

    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"


class InterfaceState(StrEnum):
    """管理或运维接口状态。"""

    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"


class LinkType(StrEnum):
    """拓扑链路类别。"""

    ETHERNET = "ethernet"
    LOOPBACK = "loopback"


@dataclass(frozen=True, slots=True)
class SiteId:
    """稳定的站点标识。"""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("site id cannot be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class DeviceId:
    """稳定的设备标识。"""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("device id cannot be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class InterfaceName:
    """厂商无关的接口名称包装类型。"""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("interface name cannot be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Site:
    """具有安全边界的运维站点。"""

    site_id: SiteId
    name: str
    security_level: DataSecurityLevel

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("site name cannot be empty")


@dataclass(frozen=True, slots=True)
class Interface:
    """设备内部不可变的接口观测记录。"""

    device_id: DeviceId
    name: InterfaceName
    peer_device_id: DeviceId | None = None
    admin_state: InterfaceState = InterfaceState.UNKNOWN
    oper_state: InterfaceState = InterfaceState.UNKNOWN


@dataclass(frozen=True, slots=True)
class Device:
    """设备身份及其稳定的接口资产清单。"""

    device_id: DeviceId
    vendor: Vendor
    model: str
    os_family: OsFamily
    os_version: str
    role: DeviceRole
    site_id: SiteId
    interfaces: tuple[InterfaceName, ...]
    compatible_concepts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.model.strip() or not self.os_version.strip():
            raise ValueError("device model and OS version cannot be empty")
        if len(set(self.interfaces)) != len(self.interfaces):
            raise ValueError("device interfaces must be unique")


@dataclass(frozen=True, slots=True)
class TopologyLink:
    """两个不同设备接口之间带时间范围的链路。"""

    link_id: str
    a_device_id: DeviceId
    a_interface: InterfaceName
    b_device_id: DeviceId
    b_interface: InterfaceName
    link_type: LinkType
    valid_from: datetime
    valid_to: datetime | None = None

    def __post_init__(self) -> None:
        if not self.link_id.strip():
            raise ValueError("link id cannot be empty")
        if self.a_device_id == self.b_device_id and self.a_interface == self.b_interface:
            raise ValueError("topology link endpoints must be distinct")
        valid_from = require_utc(self.valid_from)
        object.__setattr__(self, "valid_from", valid_from)
        if self.valid_to is not None:
            valid_to = require_utc(self.valid_to)
            if valid_to < valid_from:
                raise ValueError("topology link valid_to cannot precede valid_from")
            object.__setattr__(self, "valid_to", valid_to)

    def contains(self, instant: datetime) -> bool:
        """返回链路在指定 UTC 时刻是否处于活动状态。"""
        point = require_utc(instant)
        return self.valid_from <= point and (self.valid_to is None or point <= self.valid_to)
