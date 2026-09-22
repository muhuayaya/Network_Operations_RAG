"""针对场景命令族的确定性无损规范化。

规范化器只理解概念验证所需的小型命令词汇表。
每一行输入都会被返回，包括注释和词汇表之外的命令，
因此后续差异比较不会静默丢失来源内容。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from netops_copilot.domain.inventory import Vendor


class ConfigurationNormalizationError(ValueError):
    """配置无法安全规范化时抛出的异常。"""


class CommandFamily(StrEnum):
    """概念验证覆盖的厂商无关命令族。"""

    INTERFACE = "interface"
    VLAN = "vlan"
    LACP = "lacp"
    OSPF = "ospf"
    ACL = "acl"
    RAW = "raw"


@dataclass(frozen=True, slots=True)
class NormalizedConfigLine:
    """一行来源配置及其规范解释。"""

    line_no: int
    raw: str
    canonical: str
    section: str
    path: str
    command_family: CommandFamily
    known: bool
    parent_section: str | None = None

    @property
    def normalized(self) -> str:
        """供调用方使用的兼容别名，指向规范文本。"""
        return self.canonical

    @property
    def family(self) -> CommandFamily:
        """规范化命令族的短别名。"""
        return self.command_family

    @property
    def is_known(self) -> bool:
        """判断确定性规则是否识别了这一行。"""
        return self.known


@dataclass(frozen=True, slots=True)
class NormalizedConfiguration:
    """适合确定性差异比较的无损规范化配置。"""

    vendor: Vendor
    lines: tuple[NormalizedConfigLine, ...]

    @property
    def canonical_lines(self) -> tuple[str, ...]:
        return tuple(line.canonical for line in self.lines)

    @property
    def unknown_lines(self) -> tuple[NormalizedConfigLine, ...]:
        return tuple(line for line in self.lines if not line.known)

    @property
    def content(self) -> str:
        """生成规范行，同时保留来源行数。"""
        return "\n".join(self.canonical_lines)


_VENDOR_ALIASES = {
    "huawei": Vendor.HUAWEI,
    "华为": Vendor.HUAWEI,
    "h3c": Vendor.H3C,
    "comware": Vendor.H3C,
    "ruijie": Vendor.RUIJIE,
    "锐捷": Vendor.RUIJIE,
    "cisco": Vendor.CISCO,
    "ios": Vendor.CISCO,
    "cisco-compatible": Vendor.CISCO,
}


class ConfigurationNormalizer:
    """规范化华为、H3C、锐捷和思科的概念语法。"""

    def normalize(self, vendor: Vendor | str, content: str) -> NormalizedConfiguration:
        canonical_vendor = _normalize_vendor(vendor)
        if not content.strip():
            raise ConfigurationNormalizationError("configuration content cannot be empty")

        current_section: str | None = None
        normalized_lines: list[NormalizedConfigLine] = []
        for line_no, raw in enumerate(content.splitlines(), start=1):
            result = _normalize_line(canonical_vendor, line_no, raw, current_section)
            normalized_lines.append(result)
            if result.known and result.section not in {"raw", ""} and _is_section_header(result):
                current_section = result.section
        return NormalizedConfiguration(canonical_vendor, tuple(normalized_lines))


def normalize_configuration(vendor: Vendor | str, content: str) -> NormalizedConfiguration:
    """执行一次性规范化的便捷函数。"""
    return ConfigurationNormalizer().normalize(vendor, content)


def _normalize_vendor(value: Vendor | str) -> Vendor:
    if isinstance(value, Vendor):
        return value
    normalized = value.strip().lower()
    try:
        return _VENDOR_ALIASES[normalized]
    except KeyError as error:
        raise ConfigurationNormalizationError(f"unsupported vendor: {value}") from error


def _normalize_line(
    vendor: Vendor,
    line_no: int,
    raw: str,
    parent_section: str | None,
) -> NormalizedConfigLine:
    text = _collapse(raw)
    if not text or text.startswith(("#", "!")):
        return _raw_line(line_no, raw, text, parent_section)

    header = _header(vendor, text)
    if header is not None:
        canonical, section, path, family = header
        return NormalizedConfigLine(
            line_no=line_no,
            raw=raw,
            canonical=canonical,
            section=section,
            path=path,
            command_family=family,
            known=True,
            parent_section=parent_section,
        )

    command = _subcommand(vendor, text, parent_section)
    if command is not None:
        canonical, path, family = command
        return NormalizedConfigLine(
            line_no=line_no,
            raw=raw,
            canonical=canonical,
            section=parent_section or family.value,
            path=path,
            command_family=family,
            known=True,
            parent_section=parent_section,
        )
    return _raw_line(line_no, raw, text, parent_section)


def _raw_line(line_no: int, raw: str, text: str, parent_section: str | None) -> NormalizedConfigLine:
    return NormalizedConfigLine(
        line_no=line_no,
        raw=raw,
        canonical=text,
        section="raw",
        path=f"raw/{line_no}",
        command_family=CommandFamily.RAW,
        known=False,
        parent_section=parent_section,
    )


def _header(
    vendor: Vendor,
    text: str,
) -> tuple[str, str, str, CommandFamily] | None:
    interface = re.match(r"^interface\s+(.+)$", text, flags=re.IGNORECASE)
    if interface:
        name = _interface_name(interface.group(1))
        return f"interface {name}", f"interface/{name}", f"interface/{name}", CommandFamily.INTERFACE

    # 华为/H3C 使用全局 OSPF 进程配置段；思科使用 router ospf。
    ospf = re.match(r"^(?:router\s+ospf|ospf)\s+(\S+)$", text, flags=re.IGNORECASE)
    if ospf:
        process = ospf.group(1)
        return f"ospf process {process}", f"ospf/{process}", f"ospf/{process}", CommandFamily.OSPF

    acl = re.match(r"^(?:acl\s+(?:number\s+)?|ip\s+access-list\s+\S+\s+)(\S+)$", text, flags=re.IGNORECASE)
    if acl:
        identifier = acl.group(1)
        return f"acl {identifier}", f"acl/{identifier}", f"acl/{identifier}", CommandFamily.ACL

    vlan = re.match(r"^vlan(?:\s+batch)?\s+(.+)$", text, flags=re.IGNORECASE)
    if vlan:
        identifier = _collapse(vlan.group(1))
        return f"vlan {identifier}", f"vlan/{identifier}", f"vlan/{identifier}", CommandFamily.VLAN
    return None


def _subcommand(
    vendor: Vendor,
    text: str,
    parent_section: str | None,
) -> tuple[str, str, CommandFamily] | None:
    del vendor  # 这些模式有意将不同厂商的等价概念映射到一起。
    lower = text.lower()
    if parent_section and parent_section.startswith("interface/"):
        if lower in {"shutdown", "no shutdown", "undo shutdown"}:
            return "interface shutdown" if lower != "no shutdown" else "interface no-shutdown", "interface/shutdown", CommandFamily.INTERFACE
        if lower.startswith("description "):
            return f"interface {text}", "interface/description", CommandFamily.INTERFACE
        mtu = re.match(r"^(?:mtu|ip mtu)\s+(\d+)$", text, flags=re.IGNORECASE)
        if mtu:
            return f"interface mtu {mtu.group(1)}", "interface/mtu", CommandFamily.INTERFACE
        if re.match(r"^(?:ospf\s+enable\s+\S+\s+area|ospf\s+\S+\s+area|ip\s+ospf\s+\S+\s+area)\s+\S+$", text, flags=re.IGNORECASE):
            area = text.split()[-1]
            return f"ospf area {area}", "ospf/area", CommandFamily.OSPF
        if re.match(r"^(?:link-aggregation|port\s+link-aggregation)\s+group\s+\S+$", text, flags=re.IGNORECASE):
            group = text.split()[-1]
            return f"lacp group {group}", f"lacp/group/{group}", CommandFamily.LACP
        channel = re.match(r"^channel-group\s+(\S+)(?:\s+mode\s+(\S+))?$", text, flags=re.IGNORECASE)
        if channel:
            suffix = f" mode {channel.group(2).lower()}" if channel.group(2) else ""
            return f"lacp group {channel.group(1)}{suffix}", f"lacp/group/{channel.group(1)}", CommandFamily.LACP
        if re.match(r"^lacp\s+timeout\s+\S+$", text, flags=re.IGNORECASE):
            return f"lacp {_collapse(text.split(maxsplit=1)[1]).lower()}", "lacp/timeout", CommandFamily.LACP
        if re.match(r"^(?:port\s+trunk\s+allow-pass\s+vlan|switchport\s+trunk\s+allowed\s+vlan)\s+.+$", text, flags=re.IGNORECASE):
            vlans = text.split()[-1]
            return f"vlan trunk allowed {vlans}", "vlan/trunk-allowed", CommandFamily.VLAN
        if re.match(r"^(?:port\s+default\s+vlan|switchport\s+access\s+vlan)\s+\S+$", text, flags=re.IGNORECASE):
            vlan = text.split()[-1]
            return f"vlan access {vlan}", "vlan/access", CommandFamily.VLAN
        acl_apply = re.match(r"^(?:ip\s+access-group|traffic-filter)\s+(\S+)\s+(?:in|out)$", text, flags=re.IGNORECASE)
        if acl_apply:
            direction = text.split()[-1].lower()
            return f"acl apply {acl_apply.group(1)} {direction}", f"acl/apply/{direction}", CommandFamily.ACL
        if lower in {"loopback-detect enable", "transceiver monitor enable"}:
            return f"interface {lower}", f"interface/{lower.split()[0]}", CommandFamily.INTERFACE

    if parent_section and parent_section.startswith("ospf/"):
        peer = re.match(r"^(?:peer\s+\S+\s+)?mtu-enable$|^peer\s+\S+\s+mtu-enable$", text, flags=re.IGNORECASE)
        if peer:
            return f"ospf {_collapse(text)}", "ospf/peer-mtu", CommandFamily.OSPF
        if lower.startswith(("network ", "area ", "passive-interface ", "router-id ", "default-information ")):
            return f"ospf {_collapse(text)}", f"ospf/{_path_token(text)}", CommandFamily.OSPF

    if parent_section and parent_section.startswith("acl/"):
        rule = re.match(r"^(?:rule\s+)?(\d+)\s+(.+)$", text, flags=re.IGNORECASE)
        if rule:
            return f"acl rule {rule.group(1)} {rule.group(2)}", f"acl/rule/{rule.group(1)}", CommandFamily.ACL
        if lower.startswith(("permit ", "deny ")):
            return f"acl {text}", f"acl/rule/{_path_token(text)}", CommandFamily.ACL

    # 少量思科概念行即使没有解析出的配置段标题也具有明确含义。
    if lower.startswith("channel-group "):
        group = text.split()[1]
        mode = text.split()[-1] if len(text.split()) >= 4 and text.split()[-2].lower() == "mode" else None
        suffix = f" mode {mode.lower()}" if mode else ""
        return f"lacp group {group}{suffix}", f"lacp/group/{group}", CommandFamily.LACP
    if lower.startswith("ip access-group "):
        tokens = text.split()
        return f"acl apply {tokens[1]} {tokens[2].lower()}", f"acl/apply/{tokens[2].lower()}", CommandFamily.ACL
    return None


def _is_section_header(line: NormalizedConfigLine) -> bool:
    return line.path == line.section or line.command_family in {CommandFamily.INTERFACE, CommandFamily.OSPF, CommandFamily.ACL, CommandFamily.VLAN}


def _interface_name(value: str) -> str:
    token = _collapse(value).lower()
    if re.match(r"^(?:eth-trunk|bridge-aggregation|aggregateport|port-channel)\s*", token):
        token = re.sub(r"^(?:eth-trunk|bridge-aggregation|aggregateport|port-channel)\s*", "port-channel", token)
    elif re.match(r"^(?:tengigabitethernet|ten-gigabit-ethernet|te)\s*", token):
        token = re.sub(r"^(?:tengigabitethernet|ten-gigabit-ethernet|te)\s*", "ten-ethernet", token)
    elif re.match(r"^(?:gigabitethernet|gigabit-ethernet|gi|ge)\s*", token):
        token = re.sub(r"^(?:gigabitethernet|gigabit-ethernet|gi|ge)\s*", "ethernet", token)
    elif re.match(r"^(?:eth|ethernet)\s*", token):
        token = re.sub(r"^(?:eth|ethernet)\s*", "ethernet", token)
    return token.replace(" ", "")


def _collapse(value: str) -> str:
    return " ".join(value.strip().split())


def _path_token(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value.lower()).strip("-") or "line"
