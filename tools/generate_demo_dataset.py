"""生成确定性的网络运维参考数据集。

生成的文件仅用于测试资产，不包含客户数据、设备凭据或可执行变更指令。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "datasets" / "demo"
DATASET_VERSION = "1.0.0"
BASE_TIME = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
SECRET_PATTERN = re.compile(
    r"(?i)(BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|"
    r"\b(password|passwd|pwd|api[_-]?key|secret[_-]?key)\s*[:=]\s*\S+)"
)


def dump_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dump_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def utc(hours: int) -> str:
    return (BASE_TIME + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def inventory() -> tuple[list[dict], list[dict], list[dict]]:
    sites = [
        {"site_id": "site-sz-hq", "name": "深圳总部", "security_level": "internal"},
        {"site_id": "site-gz-dc", "name": "广州数据中心", "security_level": "restricted"},
        {"site_id": "site-sh-branch", "name": "上海分支", "security_level": "internal"},
    ]
    devices = [
        ("hw-sz-core-01", "Huawei", "S6730-H", "VRP", "V200R022", "core", "site-sz-hq"),
        ("hw-sz-core-02", "Huawei", "S6730-H", "VRP", "V200R022", "core", "site-sz-hq"),
        ("hw-gz-edge-01", "Huawei", "AR6140", "VRP", "V300R023", "edge", "site-gz-dc"),
        ("hw-gz-access-01", "Huawei", "S5735-L", "VRP", "V200R021", "access", "site-gz-dc"),
        ("hw-sh-access-01", "Huawei", "S5735-L", "VRP", "V200R021", "access", "site-sh-branch"),
        ("h3c-sz-dist-01", "H3C", "S5560X", "Comware", "V7", "distribution", "site-sz-hq"),
        ("h3c-sz-dist-02", "H3C", "S5560X", "Comware", "V7", "distribution", "site-sz-hq"),
        ("h3c-gz-core-01", "H3C", "S12508X", "Comware", "V7", "core", "site-gz-dc"),
        ("h3c-gz-access-01", "H3C", "S5130S", "Comware", "V7", "access", "site-gz-dc"),
        ("h3c-sh-access-01", "H3C", "S5130S", "Comware", "V7", "access", "site-sh-branch"),
        ("rg-sz-access-01", "Ruijie", "RG-S5760C", "RGOS", "11.4", "access", "site-sz-hq"),
        ("rg-sz-access-02", "Ruijie", "RG-S5760C", "RGOS", "11.4", "access", "site-sz-hq"),
        ("rg-gz-dist-01", "Ruijie", "RG-S7800C", "RGOS", "11.4", "distribution", "site-gz-dc"),
        ("rg-sh-core-01", "Ruijie", "RG-S7800C", "RGOS", "11.4", "core", "site-sh-branch"),
        ("rg-sh-access-01", "Ruijie", "RG-S5760C", "RGOS", "11.4", "access", "site-sh-branch"),
    ]
    inventory_records = [
        {
            "device_id": device_id,
            "vendor": vendor,
            "model": model,
            "os_family": os_family,
            "os_version": os_version,
            "role": role,
            "site_id": site_id,
            "interfaces": ["GE1/0/1", "GE1/0/2", "XGE1/0/49", "XGE1/0/50"],
            "compatible_concepts": ["Cisco IOS interface", "Cisco IOS OSPF", "Cisco IOS ACL"],
        }
        for device_id, vendor, model, os_family, os_version, role, site_id in devices
    ]
    topology_pairs = [
        ("hw-sz-core-01", "h3c-sz-dist-01"), ("hw-sz-core-02", "h3c-sz-dist-02"),
        ("h3c-sz-dist-01", "rg-sz-access-01"), ("h3c-sz-dist-02", "rg-sz-access-02"),
        ("hw-sz-core-01", "hw-gz-edge-01"), ("hw-gz-edge-01", "h3c-gz-core-01"),
        ("h3c-gz-core-01", "hw-gz-access-01"), ("h3c-gz-core-01", "h3c-gz-access-01"),
        ("h3c-gz-core-01", "rg-gz-dist-01"), ("rg-gz-dist-01", "rg-sh-core-01"),
        ("rg-sh-core-01", "hw-sh-access-01"), ("rg-sh-core-01", "h3c-sh-access-01"),
        ("rg-sh-core-01", "rg-sh-access-01"), ("hw-sz-core-02", "rg-sz-access-01"),
    ]
    links = [
        {
            "link_id": f"link-{index:02d}", "a_device_id": left, "a_interface": "XGE1/0/49",
            "b_device_id": right, "b_interface": "XGE1/0/50", "link_type": "ethernet",
            "valid_from": utc(0), "valid_to": None,
        }
        for index, (left, right) in enumerate(topology_pairs, 1)
    ]
    return sites, inventory_records, links


def config_text(device: dict, revision: str) -> str:
    vendor = device["vendor"]
    incident_change = {
        "hw-sz-core-01": "interface Eth-Trunk10\n lacp timeout short",
        "h3c-gz-core-01": "ospf 1\n peer 10.0.0.2 mtu-enable",
        "rg-sz-access-01": "interface GigabitEthernet 1/0/1\n loopback-detect enable",
        "hw-gz-access-01": "acl number 3001\n rule 10 deny ip source 10.20.30.0 0.0.0.255",
        "rg-sh-core-01": "interface TenGigabitEthernet 1/0/49\n transceiver monitor enable",
    }
    base = {
        "Huawei": f"sysname {device['device_id']}\ninterface GE1/0/1\n description UPLINK\n ospf enable 1 area 0.0.0.0",
        "H3C": f"sysname {device['device_id']}\ninterface GigabitEthernet1/0/1\n description UPLINK\n ospf 1 area 0.0.0.0",
        "Ruijie": f"hostname {device['device_id']}\ninterface GigabitEthernet 1/0/1\n description UPLINK\n ip ospf 1 area 0",
    }[vendor]
    suffix = incident_change.get(device["device_id"], "interface GE1/0/2\n description ACCESS") if revision == "current" else "interface GE1/0/2\n description ACCESS"
    return f"# REFERENCE CONFIGURATION — DO NOT DEPLOY\n# revision: {revision}\n{base}\n{suffix}\n"


def configurations(devices: list[dict]) -> list[dict]:
    snapshots = []
    for index, device in enumerate(devices, 1):
        baseline_id = f"cfg-{device['device_id']}-baseline"
        baseline = config_text(device, "baseline")
        snapshots.append({
            "snapshot_id": baseline_id, "device_id": device["device_id"], "site_id": device["site_id"],
            "vendor": device["vendor"], "captured_at": utc(index), "parent_snapshot_id": None,
            "revision": "baseline", "security_level": "internal", "content": baseline,
            "content_hash": sha256(baseline),
        })
        current = config_text(device, "current")
        snapshots.append({
            "snapshot_id": f"cfg-{device['device_id']}-current", "device_id": device["device_id"],
            "site_id": device["site_id"], "vendor": device["vendor"], "captured_at": utc(24 + index),
            "parent_snapshot_id": baseline_id, "revision": "current", "security_level": "internal",
            "content": current, "content_hash": sha256(current),
        })
    return snapshots


SCENARIO_DEFS = [
    ("inc-l2-loop", "L2 loop", "rg-sz-access-01", "site-sz-hq", "L2_LOOP_DETECTED", "critical", "广播流量异常与 MAC 地址抖动"),
    ("inc-ospf-exstart", "OSPF ExStart/MTU", "h3c-gz-core-01", "site-gz-dc", "OSPF_NEIGHBOR_EXSTART", "major", "OSPF 邻居停留在 ExStart"),
    ("inc-lacp-mismatch", "Cross-vendor LACP mismatch", "hw-sz-core-01", "site-sz-hq", "LACP_STATE_MISMATCH", "major", "链路聚合成员状态不一致"),
    ("inc-acl-outage", "ACL outage", "hw-gz-access-01", "site-gz-dc", "ACL_DENY_SPIKE", "critical", "业务网段访问被 ACL 拒绝"),
    ("inc-optical-flap", "Optical uplink flapping", "rg-sh-core-01", "site-sh-branch", "OPTICAL_RX_LOW", "major", "上联光模块接收功率波动"),
]


def alarms() -> list[dict]:
    records = []
    for scenario_index, (scenario_id, _, device_id, site_id, code, severity, summary) in enumerate(SCENARIO_DEFS):
        for event_index in range(30):
            records.append({
                "alarm_id": f"alarm-{scenario_index + 1:02d}-{event_index + 1:03d}", "scenario_id": scenario_id,
                "device_id": device_id, "site_id": site_id, "interface": "XGE1/0/49",
                "code": code, "severity": severity, "raised_at": utc(72 + scenario_index * 40 + event_index),
                "cleared_at": None if event_index % 5 == 0 else utc(73 + scenario_index * 40 + event_index),
                "summary": f"参考告警：{summary}（样本 {event_index + 1}）", "synthetic": True,
            })
    return records


def tickets() -> list[dict]:
    records = []
    for scenario_index, (scenario_id, title, device_id, site_id, _, _, summary) in enumerate(SCENARIO_DEFS):
        for ticket_index in range(6):
            records.append({
                "ticket_id": f"ticket-{scenario_index + 1:02d}-{ticket_index + 1:02d}", "scenario_id": scenario_id,
                "site_id": site_id, "device_id": device_id, "opened_at": utc(300 + scenario_index * 12 + ticket_index),
                "status": "closed", "symptoms": summary,
                "cause": f"记录根因：{title} 的可验证配置或链路状态不一致。",
                "actions": ["收集只读状态", "比对基线与当前快照", "升级至网络值班工程师人工处理"],
                "outcome": "仅记录参考处置闭环；未执行设备变更。", "synthetic": True,
            })
    return records


def knowledge_documents() -> list[dict]:
    topics = [
        ("huawei-vrp-ospf-readonly", "Huawei", "VRP", "OSPF 邻居只读检查", "使用 display ospf peer 与 display interface 读取邻居状态；MTU、区域和认证参数必须人工复核。"),
        ("huawei-vrp-acl-review", "Huawei", "VRP", "ACL 影响评审", "比较 ACL 规则顺序、源目地址和命中计数；任何修改都必须先评审并保留回滚方案。"),
        ("huawei-vrp-lacp-review", "Huawei", "VRP", "链路聚合检查", "读取 Eth-Trunk 成员状态、协商模式和速率；成员不一致时仅给出检查路径。"),
        ("h3c-comware-ospf-readonly", "H3C", "Comware", "OSPF ExStart 研判", "读取 OSPF 邻居状态、接口 MTU 和网络类型；ExStart 仅表示需要进一步基于证据诊断。"),
        ("h3c-comware-vlan-review", "H3C", "Comware", "VLAN 一致性检查", "读取端口 VLAN、Trunk 允许列表和对端配置；未知行应原样保留。"),
        ("h3c-comware-interface-health", "H3C", "Comware", "接口健康检查", "读取接口管理状态、运行状态、错误计数和协商信息，不执行 shutdown 或 reset。"),
        ("ruijie-rgos-loop-detection", "Ruijie", "RGOS", "二层环路证据收集", "读取 MAC 变动、广播统计、STP 状态和环路检测事件；优先定位接口与时间窗。"),
        ("ruijie-rgos-optical-health", "Ruijie", "RGOS", "光链路波动检查", "读取收发光功率、接口 flap 计数和错误计数；阈值需结合具体型号和现场标准。"),
        ("ruijie-rgos-lacp-review", "Ruijie", "RGOS", "LACP 协商检查", "读取聚合组成员、状态和对端协商信息；跨厂商结果需按统一字段比对。"),
        ("cisco-concept-acl", "Cisco-compatible", "IOS concept", "ACL 概念对照", "Cisco ACL 的顺序匹配概念用于跨厂商语义对照，不作为华为、华三或锐捷命令替代。"),
        ("cisco-concept-ospf", "Cisco-compatible", "IOS concept", "OSPF 概念对照", "Area、邻居状态和 MTU 一致性是跨厂商共同诊断概念，但具体命令需匹配厂商与版本。"),
        ("cisco-concept-lacp", "Cisco-compatible", "IOS concept", "LACP 概念对照", "聚合成员、协商模式和链路属性属于跨厂商可比证据；不要混用可执行命令。"),
        ("sop-alarm-triage", "Generic", "SOP", "告警初步研判 SOP", "按站点、设备、接口、时间窗、拓扑邻接和近期快照变化构造证据包，再解释候选原因。"),
        ("sop-config-diff", "Generic", "SOP", "配置 Diff SOP", "先生成结构化差异和风险标签，再检索资料解释影响；模型不得替代差异计算。"),
        ("sop-evidence-citation", "Generic", "SOP", "证据引用 SOP", "事实结论必须关联已授权来源；资料不足时明确拒答或标记推断。"),
        ("sop-readonly-device-access", "Generic", "SOP", "只读设备观察 SOP", "只允许白名单读取操作，记录操作者、目标、时间和 Trace ID；禁止任意命令。"),
        ("sop-secret-redaction", "Generic", "SOP", "导入前脱敏 SOP", "发现凭据样式内容时拒绝索引并保留不含原文的错误记录。"),
        ("sop-site-access-filter", "Generic", "SOP", "站点访问过滤 SOP", "在召回前按站点和安全等级过滤；不能在生成阶段补救已泄露内容。"),
        ("sop-incident-escalation", "Generic", "SOP", "事故升级 SOP", "影响路由、VLAN、ACL 或链路状态的建议统一标记高风险，交由人工评审。"),
        ("sop-index-versioning", "Generic", "SOP", "索引版本 SOP", "Embedding、维度或归一化变化时重建索引版本，通过评测后再切换活动别名。"),
        ("sop-retrieval-degradation", "Generic", "SOP", "检索降级 SOP", "区分零结果、单路降级和整体不可用；不能把系统故障伪装为未找到资料。"),
        ("sop-golden-set", "Generic", "SOP", "Golden Set 维护 SOP", "样本必须包含厂商、错误码、语义故障、无答案和安全案例，并记录期望证据。"),
        ("sop-topology-correlation", "Generic", "SOP", "拓扑关联 SOP", "仅使用版本化拓扑和一跳邻接关系形成关联证据；不推测未建模链路。"),
        ("sop-ticket-similarity", "Generic", "SOP", "相似工单 SOP", "工单只作为补充证据，需显示其来源属性、时间和适用站点。"),
        ("sop-demo-safety", "Generic", "SOP", "只读安全边界", "流程仅执行只读分析，不连接真实设备、不下发配置、不自动修复。"),
    ]
    documents = [
        {
            "source_id": f"doc-{slug}", "title": title, "source_type": "sop" if vendor == "Generic" else "vendor_reference",
            "vendor": vendor, "os_family": os_family, "site_id": None, "security_level": "internal",
            "effective_at": "2026-09-01", "synthetic": True,
            "content": f"# {title}\n\n> 参考资料；用于本地检索与流程验证，不能替代厂商官方文档或生产变更流程。\n\n{body}\n",
        }
        for slug, vendor, os_family, title, body in topics
    ]
    documents.extend(
        {
            "source_id": f"doc-{slug}",
            "title": title,
            "source_type": "sop",
            "vendor": "Generic",
            "os_family": "SOP",
            "site_id": "site-gz-dc",
            "security_level": "restricted",
            "effective_at": "2026-09-01",
            "synthetic": True,
            "content": (
                f"# {title}\n\n> 受限参考证据；用于权限过滤验证。\n\n{body}\n"
            ),
        }
        for slug, title, body in (
            (
                "sop-restricted-gz-access",
                "广州数据中心受限访问核验",
                "只读核验 site-gz-dc 的站点范围和证据授权；basic 身份不得读取本文档。",
            ),
            (
                "sop-restricted-gz-maintenance",
                "广州数据中心维护窗口记录",
                "仅 restricted 身份可查看受限维护窗口证据，所有建议仍需人工评审。",
            ),
            (
                "sop-restricted-gz-topology",
                "广州数据中心拓扑核对",
                "受限拓扑证据仅用于授权后的只读关联，不得作为设备写操作指令。",
            ),
        )
    )
    return documents


def scenarios() -> list[dict]:
    result = []
    for index, (scenario_id, title, device_id, site_id, code, _, _) in enumerate(SCENARIO_DEFS, 1):
        result.append({
            "scenario_id": scenario_id, "title": title, "site_id": site_id, "primary_device_id": device_id,
            "expected_alarm_code": code, "expected_evidence": {
                "alarm_id": f"alarm-{index:02d}-001", "ticket_id": f"ticket-{index:02d}-01",
                "baseline_snapshot_id": f"cfg-{device_id}-baseline", "current_snapshot_id": f"cfg-{device_id}-current",
            }, "expected_outcome": "返回确定性事实、只读验证步骤、风险标记和可追溯引用；不执行修复。",
        })
    return result


def principals() -> list[dict]:
    """返回用于测试检索前访问过滤的固定身份。"""
    return [
        {
            "principal_id": "principal-basic-demo",
            "security_level": "basic",
            "allowed_site_ids": ["site-sz-hq", "site-gz-dc", "site-sh-branch"],
        },
        {
            "principal_id": "principal-restricted-demo",
            "security_level": "restricted",
            "allowed_site_ids": ["site-sz-hq", "site-gz-dc", "site-sh-branch"],
        },
    ]


def golden_set(documents: list[dict]) -> list[dict]:
    vendor_docs = [doc for doc in documents if doc["vendor"] in {"Huawei", "H3C", "Ruijie"}]
    restricted_docs = [doc for doc in documents if doc["security_level"] == "restricted"]
    records = []
    for index in range(50):
        doc = vendor_docs[index % len(vendor_docs)] if index < 30 else documents[index % len(documents)]
        category = ["vendor_command", "error_code", "semantic_fault", "filter", "incident", "no_answer", "security"][index % 7]
        if category == "no_answer":
            records.append({
                "case_id": f"golden-{index + 1:03d}", "category": category,
                "question": f"未登记设备 QX-{index + 1:04d} 的量子链路恢复命令是什么？",
                "expected_source_ids": [], "expected_vendor": "Generic",
                "expected_behavior": "no_evidence",
            })
        elif category == "security":
            protected = restricted_docs[(index // 7) % len(restricted_docs)]
            records.append({
                "case_id": f"golden-{index + 1:03d}", "category": category,
                "question": f"如何核对 {protected['title']}？",
                "expected_source_ids": [protected["source_id"]], "expected_vendor": "Generic",
                "expected_behavior": "forbidden", "principal_id": "principal-basic-demo",
                "site_id": "site-gz-dc", "security_level": "restricted",
            })
        else:
            records.append({
                "case_id": f"golden-{index + 1:03d}", "category": category,
                "question": f"评测问题 {index + 1}：如何在 {doc['vendor']} 场景核对 {doc['title']}？",
                "expected_source_ids": [doc["source_id"]], "expected_vendor": doc["vendor"],
                "expected_behavior": "cite",
            })
    return records


def render_documents(documents: list[dict]) -> None:
    directory = OUT / "knowledge"
    directory.mkdir(parents=True, exist_ok=True)
    for document in documents:
        front_matter = {
            key: document[key]
            for key in ("source_id", "source_type", "vendor", "os_family", "site_id", "security_level", "effective_at", "synthetic")
        }
        metadata = "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in front_matter.items())
        (directory / f"{document['source_id']}.md").write_text(
            f"---\n{metadata}\n---\n\n{document['content']}", encoding="utf-8"
        )


def validate(output: Path) -> None:
    required = {
        "inventory/sites.json": 3, "inventory/devices.json": 15, "topology/links.json": 14,
        "observations/config_snapshots.jsonl": 30, "observations/alarms.jsonl": 150,
        "tickets/tickets.jsonl": 30, "scenarios/incidents.json": 5, "evals/golden_set.json": 50,
    }
    collections: dict[str, list[dict]] = {}
    for relative, expected_count in required.items():
        path = output / relative
        if not path.exists():
            raise ValueError(f"missing required data file: {relative}")
        text = path.read_text(encoding="utf-8")
        value = [json.loads(line) for line in text.splitlines() if line] if path.suffix == ".jsonl" else json.loads(text)
        if len(value) != expected_count:
            raise ValueError(f"{relative}: expected {expected_count}, got {len(value)}")
        collections[relative] = value
    knowledge = list((output / "knowledge").glob("*.md"))
    if len(knowledge) != 28:
        raise ValueError(f"knowledge: expected 28 docs, got {len(knowledge)}")
    devices = collections["inventory/devices.json"]
    device_ids = {device["device_id"] for device in devices}
    if Counter(device["vendor"] for device in devices) != Counter({"Huawei": 5, "H3C": 5, "Ruijie": 5}):
        raise ValueError("设备清单必须为每个要求的厂商包含 5 台设备")
    snapshot_ids = {snapshot["snapshot_id"] for snapshot in collections["observations/config_snapshots.jsonl"]}
    alarm_ids = {alarm["alarm_id"] for alarm in collections["observations/alarms.jsonl"]}
    ticket_ids = {ticket["ticket_id"] for ticket in collections["tickets/tickets.jsonl"]}
    for snapshot in collections["observations/config_snapshots.jsonl"]:
        if snapshot["device_id"] not in device_ids:
            raise ValueError(f"snapshot references unknown device: {snapshot['snapshot_id']}")
        if snapshot["parent_snapshot_id"] and snapshot["parent_snapshot_id"] not in snapshot_ids:
            raise ValueError(f"snapshot references unknown parent: {snapshot['snapshot_id']}")
        if snapshot["content_hash"] != sha256(snapshot["content"]):
            raise ValueError(f"snapshot hash mismatch: {snapshot['snapshot_id']}")
    for scenario in collections["scenarios/incidents.json"]:
        evidence = scenario["expected_evidence"]
        if scenario["primary_device_id"] not in device_ids:
            raise ValueError(f"scenario references unknown device: {scenario['scenario_id']}")
        if evidence["alarm_id"] not in alarm_ids or evidence["ticket_id"] not in ticket_ids:
            raise ValueError(f"scenario references missing alarm or ticket: {scenario['scenario_id']}")
        if evidence["baseline_snapshot_id"] not in snapshot_ids or evidence["current_snapshot_id"] not in snapshot_ids:
            raise ValueError(f"scenario references missing snapshot: {scenario['scenario_id']}")
    source_ids = {path.stem for path in knowledge}
    for case in collections["evals/golden_set.json"]:
        if not set(case["expected_source_ids"]).issubset(source_ids):
            raise ValueError(f"golden set references unknown knowledge source: {case['case_id']}")
    access_path = output / "access" / "principals.json"
    access_principals = json.loads(access_path.read_text(encoding="utf-8"))
    if {principal["principal_id"] for principal in access_principals} != {
        "principal-basic-demo",
        "principal-restricted-demo",
    }:
        raise ValueError("访问测试数据必须包含固定的基础权限和受限权限主体")
    for path in output.rglob("*"):
        if ".runtime" in path.relative_to(output).parts:
            continue
        if path.is_file() and SECRET_PATTERN.search(path.read_text(encoding="utf-8")):
            raise ValueError(f"potential secret detected in {path.relative_to(output)}")


def generate() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    sites, devices, links = inventory()
    docs = knowledge_documents()
    dump_json(OUT / "schema" / "dataset_contract.json", {
        "dataset_version": DATASET_VERSION, "seed": "fixed-v1", "synthetic_only": True,
        "required_collections": ["sites", "devices", "links", "config_snapshots", "alarms", "tickets", "knowledge", "incidents", "golden_set"],
        "prohibited_content": ["customer data", "credentials", "private keys", "production change commands"],
    })
    dump_json(OUT / "inventory" / "sites.json", sites)
    dump_json(OUT / "inventory" / "devices.json", devices)
    dump_json(OUT / "topology" / "links.json", links)
    dump_jsonl(OUT / "observations" / "config_snapshots.jsonl", configurations(devices))
    dump_jsonl(OUT / "observations" / "alarms.jsonl", alarms())
    dump_jsonl(OUT / "tickets" / "tickets.jsonl", tickets())
    dump_json(OUT / "scenarios" / "incidents.json", scenarios())
    dump_json(OUT / "evals" / "golden_set.json", golden_set(docs))
    dump_json(OUT / "access" / "principals.json", principals())
    render_documents(docs)
    dump_json(OUT / "manifest.json", {
        "dataset_id": "netops-reference-data", "version": DATASET_VERSION, "generated_at": BASE_TIME.isoformat(),
        "synthetic_only": True, "generator": "tools/generate_demo_dataset.py",
        "counts": {"sites": len(sites), "devices": len(devices), "links": len(links), "config_snapshots": 30, "alarms": 150, "tickets": 30, "knowledge_documents": len(docs), "incidents": 5, "golden_set": 50},
        "inventory_sha256": sha256({"sites": sites, "devices": devices, "links": links}),
    })
    validate(OUT)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser._positionals.title = "位置参数"
    parser._optionals.title = "选项"
    parser.add_argument("--check", action="store_true", help="校验现有的已生成数据")
    args = parser.parse_args()
    if args.check:
        validate(OUT)
    else:
        generate()
    print(f"已校验演示数据集：{OUT}")
