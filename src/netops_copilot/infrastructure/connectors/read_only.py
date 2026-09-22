"""默认禁用且受允许列表约束的只读协议连接器外壳。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


class ConnectorDisabledError(PermissionError):
    """连接器必须显式启用后才能执行任何网络 I/O。"""


class OperationNotAllowed(PermissionError):
    """请求的操作不在只读允许列表中。"""


@dataclass(frozen=True, slots=True)
class ReadOnlyTarget:
    """受调用方策略约束的命名目标。"""

    target_id: str

    def __post_init__(self) -> None:
        if not self.target_id.strip():
            raise ValueError("target id cannot be blank")


class SnmpGetAdapter:
    """SNMP GET 外壳；绝不委托 SET 或未知 OID。"""

    def __init__(
        self,
        transport: Callable[[ReadOnlyTarget, str], object],
        *,
        enabled: bool = False,
        allowed_oids: frozenset[str] = frozenset(),
    ) -> None:
        self._transport = transport
        self._enabled = enabled
        self._allowed_oids = allowed_oids

    def get(self, target: ReadOnlyTarget, oid: str) -> object:
        self._check_enabled()
        if oid not in self._allowed_oids:
            raise OperationNotAllowed("SNMP OID is not allow-listed")
        return self._transport(target, oid)

    def _check_enabled(self) -> None:
        if not self._enabled:
            raise ConnectorDisabledError("SNMP connector is disabled")


class NetconfReadAdapter:
    """仅允许 get/get-config 操作的 NETCONF 只读 RPC 外壳。"""

    def __init__(
        self,
        transport: Callable[[ReadOnlyTarget, str, str], object],
        *,
        enabled: bool = False,
        allowed_rpcs: frozenset[str] = frozenset({"get", "get-config"}),
    ) -> None:
        self._transport = transport
        self._enabled = enabled
        self._allowed_rpcs = allowed_rpcs

    def read(self, target: ReadOnlyTarget, rpc: str, filter_xml: str = "") -> object:
        if not self._enabled:
            raise ConnectorDisabledError("NETCONF connector is disabled")
        if rpc not in self._allowed_rpcs:
            raise OperationNotAllowed("NETCONF RPC is not read-only or allow-listed")
        return self._transport(target, rpc, filter_xml)


class SshReadOnlyAdapter:
    """只允许执行经过预审的精确 show 命令的 SSH 外壳。"""

    def __init__(
        self,
        transport: Callable[[ReadOnlyTarget, str], object],
        *,
        enabled: bool = False,
        allowed_commands: frozenset[str] = frozenset(),
    ) -> None:
        self._transport = transport
        self._enabled = enabled
        self._allowed_commands = allowed_commands

    def run_read_command(self, target: ReadOnlyTarget, command: str) -> object:
        if not self._enabled:
            raise ConnectorDisabledError("SSH connector is disabled")
        if command not in self._allowed_commands:
            raise OperationNotAllowed("SSH command is not allow-listed")
        return self._transport(target, command)
