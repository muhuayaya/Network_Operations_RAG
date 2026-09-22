"""将外部参考知识库导入项目，但不修改来源。

导入器会规范化目录/文件名，将绝对路径替换为项目相对路径，
并脱敏赋值形式的凭据值。导入内容仍会标记为外部来源且尚未完成许可校验。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path(r"D:\text\network_ops_rag_kb")
DEFAULT_DESTINATION = PROJECT_ROOT / "datasets" / "reference-import" / "v1"
CATEGORY_NAMES = {
    "01_network_devices": "network-devices",
    "02_linux_ops": "linux-operations",
    "03_sdn_virtualization": "sdn-virtualization",
    "04_enterprise_ops": "enterprise-operations",
}
NAME_PREFIXES = (
    "infra-networking-", "infra-platform-", "infra-linux-", "infra-ha-",
    "ops-linux-", "cn-ops-", "sdn-", "ops-",
)
CREDENTIAL_LINE = re.compile(
    r"(?im)^(\s*(?:password|passwd|pwd|token|api[_-]?key|secret[_-]?key)\s*[:=]\s*)(?!\[REDACTED\])(\S+)"
)
BEARER_VALUE = re.compile(r"(?im)(authorization\s*:\s*bearer\s+)(?!\[REDACTED\])(\S+)")
PRIVATE_KEY_BLOCK = re.compile(r"(?is)-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.+?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
UNREDACTED_SECRET = re.compile(
    r"^(?:\s*)(?:password|passwd|pwd|token|api[_-]?key|secret[_-]?key)\s*[:=]\s*(?!\[REDACTED\])\S+|"
    r"authorization\s*:\s*bearer\s+(?!\[REDACTED\])\S+|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    re.IGNORECASE | re.MULTILINE,
)


def json_dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def normalized_name(filename: str) -> str:
    stem = Path(filename).stem.lower()
    for prefix in NAME_PREFIXES:
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return f"{stem}.md"


def redact(content: str) -> tuple[str, int]:
    count = 0

    def replace_assignment(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"{match.group(1)}[REDACTED]"

    def replace_bearer(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"{match.group(1)}[REDACTED]"

    def replace_key(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return "[REDACTED PRIVATE KEY]"

    content = CREDENTIAL_LINE.sub(replace_assignment, content)
    content = BEARER_VALUE.sub(replace_bearer, content)
    content = PRIVATE_KEY_BLOCK.sub(replace_key, content)
    return content, count


def require_safe_destination(destination: Path) -> None:
    datasets_root = (PROJECT_ROOT / "datasets").resolve()
    resolved = destination.resolve()
    if datasets_root not in resolved.parents:
        raise ValueError(f"destination must be inside {datasets_root}: {resolved}")


def import_kb(source: Path, destination: Path) -> None:
    source = source.resolve()
    destination = destination.resolve()
    require_safe_destination(destination)
    if not (source / "docs").is_dir():
        raise ValueError(f"source docs directory is missing: {source / 'docs'}")
    manifest_path = source / "manifest.json"
    test_set_path = source / "test_set.json"
    if not manifest_path.is_file() or not test_set_path.is_file():
        raise ValueError("来源目录必须包含 manifest.json 和 test_set.json")

    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_tests = json.loads(test_set_path.read_text(encoding="utf-8"))
    source_by_path = {Path(entry["path"]).resolve(): entry for entry in source_manifest}
    mapping: dict[str, str] = {}
    normalized_manifest: list[dict] = []
    redaction_count = 0

    if destination.exists():
        shutil.rmtree(destination)
    for category, normalized_category in CATEGORY_NAMES.items():
        category_dir = source / "docs" / category
        if not category_dir.is_dir():
            raise ValueError(f"unknown or missing source category: {category}")
        for original_path in sorted(category_dir.glob("*.md")):
            normalized_path = destination / "documents" / normalized_category / normalized_name(original_path.name)
            if normalized_path.exists():
                raise ValueError(f"normalized name collision: {normalized_path.name}")
            raw = original_path.read_text(encoding="utf-8")
            content, changes = redact(raw)
            redaction_count += changes
            normalized_path.parent.mkdir(parents=True, exist_ok=True)
            normalized_path.write_text(content, encoding="utf-8")
            relative_input = original_path.relative_to(source).as_posix()
            relative_output = normalized_path.relative_to(destination).as_posix()
            mapping[relative_input] = relative_output
            entry = source_by_path.get(original_path.resolve())
            if entry is None:
                raise ValueError(f"source document missing from manifest: {relative_input}")
            normalized_manifest.append({
                "document_id": f"external-{Path(relative_output).stem}",
                "relative_path": relative_output,
                "category": normalized_category,
                "source_repository": entry["source_repo"],
                "source_url": entry["source_url"],
                "origin_relative_path": relative_input,
                "origin_sha256": sha256(raw),
                "imported_sha256": sha256(content),
                "license_status": "unverified",
                "usage_boundary": "local reference and evaluation only until license review is recorded",
                "redacted_assignments": changes,
            })

    if len(normalized_manifest) != len(source_manifest):
        raise ValueError("来源清单与导入文档数量不一致")
    normalized_tests = []
    for case in source_tests:
        source_docs = case.get("source_docs", [])
        if not source_docs or any(path not in mapping for path in source_docs):
            raise ValueError(f"test case has an unmapped source document: {case.get('id')}")
        normalized_tests.append({
            **case,
            "category": case["category"].replace("_", "-"),
            "source_docs": [mapping[path] for path in source_docs],
            "dataset_origin": "external-reference-import-v1",
        })

    json_dump(destination / "metadata" / "documents.json", normalized_manifest)
    json_dump(destination / "evaluations" / "external-qa-baseline.json", normalized_tests)
    json_dump(destination / "import-manifest.json", {
        "import_id": "external-network-ops-reference-v1",
        "source_root_label": "external-network-ops-rag-kb",
        "source_document_count": len(source_manifest),
        "imported_document_count": len(normalized_manifest),
        "external_qa_case_count": len(normalized_tests),
        "credential_assignments_redacted": redaction_count,
        "license_status": "unverified",
        "default_ingestion_status": "blocked_pending_license_review",
        "naming_convention": "lowercase kebab-case paths; category names use lowercase kebab-case",
        "source_categories": CATEGORY_NAMES,
    })
    validate(destination)


def validate(destination: Path) -> None:
    manifest_path = destination / "metadata" / "documents.json"
    tests_path = destination / "evaluations" / "external-qa-baseline.json"
    if not manifest_path.is_file() or not tests_path.is_file():
        raise ValueError("缺少规范化清单或 QA 基线")
    documents = json.loads(manifest_path.read_text(encoding="utf-8"))
    tests = json.loads(tests_path.read_text(encoding="utf-8"))
    if len(documents) != 67 or len(tests) != 42:
        raise ValueError(f"unexpected import count: {len(documents)} docs, {len(tests)} tests")
    available_paths = {entry["relative_path"] for entry in documents}
    for entry in documents:
        path = destination / entry["relative_path"]
        if not path.is_file():
            raise ValueError(f"missing imported document: {entry['relative_path']}")
        if path.name != normalized_name(path.name):
            raise ValueError(f"non-normalized file name: {path.name}")
        if UNREDACTED_SECRET.search(path.read_text(encoding="utf-8")):
            raise ValueError(f"unredacted credential pattern: {entry['relative_path']}")
    for case in tests:
        if not set(case["source_docs"]).issubset(available_paths):
            raise ValueError(f"test references missing normalized document: {case['id']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser._positionals.title = "位置参数"
    parser._optionals.title = "选项"
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--check", action="store_true", help="校验现有的导入包")
    args = parser.parse_args()
    if args.check:
        validate(args.destination.resolve())
    else:
        import_kb(args.source, args.destination)
    print(f"已校验参考资料导入包：{args.destination.resolve()}")
