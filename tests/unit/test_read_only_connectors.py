"""只读连接器允许列表和默认禁用测试。"""

from __future__ import annotations

import unittest

from netops_copilot.infrastructure.connectors.read_only import (
    ConnectorDisabledError,
    NetconfReadAdapter,
    OperationNotAllowed,
    ReadOnlyTarget,
    SnmpGetAdapter,
    SshReadOnlyAdapter,
)


class ReadOnlyConnectorTests(unittest.TestCase):
    def test_disabled_connectors_do_not_call_transport(self) -> None:
        calls: list[object] = []
        target = ReadOnlyTarget("router-1")
        snmp = SnmpGetAdapter(lambda *_: calls.append("snmp"), allowed_oids=frozenset({"1.3"}))
        netconf = NetconfReadAdapter(lambda *_: calls.append("netconf"))
        ssh = SshReadOnlyAdapter(lambda *_: calls.append("ssh"), allowed_commands=frozenset({"display version"}))
        for call in (
            lambda: snmp.get(target, "1.3"),
            lambda: netconf.read(target, "get"),
            lambda: ssh.run_read_command(target, "display version"),
        ):
            with self.assertRaises(ConnectorDisabledError):
                call()
        self.assertEqual(calls, [])

    def test_mutating_or_unknown_operations_are_rejected_before_transport(self) -> None:
        calls: list[object] = []
        target = ReadOnlyTarget("router-1")
        snmp = SnmpGetAdapter(lambda *_: calls.append("snmp"), enabled=True, allowed_oids=frozenset({"1.3"}))
        netconf = NetconfReadAdapter(lambda *_: calls.append("netconf"), enabled=True)
        ssh = SshReadOnlyAdapter(lambda *_: calls.append("ssh"), enabled=True, allowed_commands=frozenset({"display version"}))
        with self.assertRaises(OperationNotAllowed):
            snmp.get(target, "1.4")
        with self.assertRaises(OperationNotAllowed):
            netconf.read(target, "edit-config")
        with self.assertRaises(OperationNotAllowed):
            ssh.run_read_command(target, "configure terminal")
        self.assertEqual(calls, [])
