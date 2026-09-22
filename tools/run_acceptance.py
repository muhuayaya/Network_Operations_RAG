"""运行 clean-room 验收流程，并归档带版本的证据报告。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from netops_copilot.application.config_diff import diff_configurations
from netops_copilot.application.doctor import doctor_report
from netops_copilot.application.evaluation import load_golden_set
from netops_copilot.application.local_milvus_runtime import (
    create_local_milvus_services,
    local_milvus_doctor,
)
from netops_copilot.bootstrap import bootstrap
from netops_copilot.interfaces.api import create_app
from netops_copilot.interfaces.cli.lifecycle import ingest_dataset, reset_runtime
from netops_copilot.interfaces.mcp import create_mcp_server
from netops_copilot.settings import ProfileName


def run(profile: str) -> dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    dataset = root / "datasets" / "demo"
    runtime = dataset / ".runtime"
    reset_runtime(runtime)
    subprocess.run([sys.executable, str(root / "tools" / "generate_demo_dataset.py")], cwd=root, check=True)
    ingest = ingest_dataset(dataset, runtime)
    selected_profile = ProfileName(profile)
    if selected_profile is ProfileName.LOCAL_MILVUS:
        doctor = local_milvus_doctor()
        if doctor.status.value != "healthy":
            raise RuntimeError(
                "local-milvus dependencies are not ready: "
                + "; ".join(item.detail for item in doctor.dependencies if not item.ready)
            )
    else:
        doctor = doctor_report(bootstrap(selected_profile))
    golden = load_golden_set(dataset / "evals" / "golden_set.json")
    scenario_ids = [item["scenario_id"] for item in json.loads((dataset / "scenarios" / "incidents.json").read_text(encoding="utf-8"))]
    if len(scenario_ids) != 5:
        raise RuntimeError("验收要求数据包中包含 5 个场景")
    acl_diff = diff_configurations(
        "acl number 3001\n rule 10 permit ip\n",
        "acl number 3001\n rule 10 deny ip\n",
        vendor="Huawei",
    )
    app_paths = sorted(route.path for route in create_app().routes)
    mcp_tools = sorted(tool["name"] for tool in create_mcp_server().list_tools())
    local_query: dict[str, object] | None = None
    if selected_profile is ProfileName.LOCAL_MILVUS:
        services = create_local_milvus_services(selected_profile, runtime)
        local_query = services.query(
            {"query": "OSPF ExStart", "vendor": "H3C", "mode": "hybrid", "limit": 5}
        )
        if not isinstance(local_query, dict) or not local_query.get("candidates"):
            raise RuntimeError("local-milvus query returned no candidates")
    return {
        "status": "passed",
        "profile": profile,
        "generated_at": datetime.now(UTC).isoformat(),
        "doctor_status": doctor.status.value,
        "ingest": {
            "source_count": ingest.source_count,
            "record_count": ingest.record_count,
            "chunk_count": ingest.chunk_count,
            "content_hash": ingest.content_hash,
        },
        "scenario_count": len(scenario_ids),
        "golden_case_count": len(golden),
        "acl_diff_change_count": len(acl_diff.changes),
        "rest_paths": app_paths,
        "mcp_tools": mcp_tools,
        **({"local_query": local_query} if local_query is not None else {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser._positionals.title = "位置参数"
    parser._optionals.title = "选项"
    parser.add_argument("--profile", choices=("demo-lite", "local-milvus"), default="demo-lite")
    parser.add_argument("--report-dir", type=Path, default=Path("reports") / "acceptance")
    arguments = parser.parse_args()
    arguments.report_dir.mkdir(parents=True, exist_ok=True)
    target = arguments.report_dir / f"{arguments.profile}.json"
    try:
        report = run(arguments.profile)
    except (RuntimeError, ValueError) as error:
        report = {
            "status": "failed",
            "profile": arguments.profile,
            "generated_at": datetime.now(UTC).isoformat(),
            "error": str(error),
        }
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": report["status"], "report": str(target)}, ensure_ascii=False))
        return 1
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
