"""Inventory task assets, agent visibility, and mount write-back risks.

This is an audit, not an automatic unused-file deleter: native logs, dynamically
loaded modules, provenance and cross-architecture packages may be required even
without an exact filename reference in an instruction.

Agent visibility is determined by Dockerfile COPY destinations (Harbor does not
bind-mount environment/assets into the agent container). Build-only copies into
/tmp are not agent-visible in the final image.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import shlex
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".sh", ".md", ".json", ".toml", ".yaml", ".yml", ".txt", ".sha256", ".csv"}
GENERATED_DIRECTORIES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", ".git"}
GENERATED_FILES = {".DS_Store", "reward.txt", "reward.json", "verification.json"}
BUILD_ONLY_PREFIXES = ("/tmp", "/var/tmp")
PRIVATE_DEST_PREFIXES = ("/opt/", "/trusted/", "/root/")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def managed_assets(root: Path) -> dict[str, dict[str, Any]]:
    files = {}
    for store in ("asset-store", "wheelhouse"):
        manifest = json.loads((root / "shared" / store / "manifest.json").read_text())
        for relative, digest in manifest["files"].items():
            if "/environment/assets/" not in relative:
                continue
            details = manifest["blobs"][digest]
            files[relative] = {"store": store, "sha256": digest, "size": details["size"]}
    return files


def copy_directives(dockerfile: Path) -> list[tuple[str, str]]:
    if not dockerfile.is_file():
        return []
    source = dockerfile.read_text().replace("\\\n", " ")
    directives = []
    for line in source.splitlines():
        if not re.match(r"(?i)^\s*COPY\s+", line):
            continue
        if re.search(r"(?i)--from(?:=|\s)", line):
            continue
        rest = line.strip().split(None, 1)[1]
        while rest.startswith("--"):
            rest = rest.split(None, 1)[1] if " " in rest else ""
        if not rest:
            continue
        parts = json.loads(rest) if rest.startswith("[") else shlex.split(rest)
        if len(parts) < 2:
            continue
        destination = parts[-1]
        for item in parts[:-1]:
            if item.startswith(("https://", "http://", "<<")):
                continue
            directives.append((item.removeprefix("./"), destination))
    return directives


def matches_copy(relative: str, source: str) -> bool:
    source = source.removeprefix("./").rstrip("/")
    return (
        source in {".", "assets"}
        or relative == source
        or relative.startswith(source + "/")
        or fnmatch.fnmatchcase(relative, source)
    )


def visibility_for(destinations: list[str]) -> str:
    if not destinations:
        return "unreferenced"
    if all(any(dest == prefix or dest.startswith(prefix + "/") for prefix in BUILD_ONLY_PREFIXES) for dest in destinations):
        return "build_only"
    if any(any(dest == prefix.rstrip("/") or dest.startswith(prefix) for prefix in PRIVATE_DEST_PREFIXES) for dest in destinations):
        if all(
            any(dest == prefix.rstrip("/") or dest.startswith(prefix) for prefix in PRIVATE_DEST_PREFIXES)
            or any(dest == p or dest.startswith(p + "/") for p in BUILD_ONLY_PREFIXES)
            for dest in destinations
        ):
            return "private_runtime"
    return "agent_visible"


def text_files(directory: Path) -> dict[Path, str]:
    texts = {}
    for path in directory.rglob("*"):
        if (
            not path.is_file()
            or path.is_symlink()
            or any(part in GENERATED_DIRECTORIES for part in path.parts)
            or (path.suffix not in TEXT_SUFFIXES and path.name != "Dockerfile")
            or path.stat().st_size > 5_000_000
        ):
            continue
        try:
            texts[path] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
    return texts


def compose_mount_issues(root: Path) -> list[dict[str, Any]]:
    issues = []
    for path in (root / "tasks").rglob("docker-compose.yaml"):
        text = path.read_text(encoding="utf-8")
        if not re.search(r"(?m)^\s*volumes:\s*$", text) and "volumes:" not in text:
            continue
        # Flag any bind that mentions environment/assets without an explicit read_only: true nearby.
        for match in re.finditer(
            r"(?ms)type:\s*bind.*?source:\s*([^\n]+).*?target:\s*([^\n]+)(?:.*?)(?=\n\s*-\s*type:|\n\s*\w|\Z)",
            text,
        ):
            block = match.group(0)
            source = match.group(1).strip()
            target = match.group(2).strip()
            mentions_assets = "assets" in source or "environment/assets" in source or "/assets" in target
            if not mentions_assets:
                continue
            read_only = re.search(r"read_only:\s*true", block) is not None
            if not read_only:
                issues.append(
                    {
                        "kind": "assets_bind_not_read_only",
                        "path": path.relative_to(root).as_posix(),
                        "source": source,
                        "target": target,
                    }
                )
    return issues


def inventory(root: Path) -> dict[str, Any]:
    managed = managed_assets(root)
    report: dict[str, Any] = {"version": 2, "tasks": [], "files": [], "issues": []}
    report["issues"].extend(compose_mount_issues(root))
    for task in sorted((root / "tasks").iterdir()):
        if not (task / "task.toml").is_file():
            continue
        assets, environment = task / "environment/assets", task / "environment"
        paths = {p.relative_to(root).as_posix() for p in assets.rglob("*") if p.is_file() or p.is_symlink()}
        paths.update(p for p in managed if p.startswith(assets.relative_to(root).as_posix() + "/"))
        texts = text_files(task)
        for relative in sorted(paths):
            path = root / relative
            metadata = managed.get(relative)
            if path in texts or not metadata or path.suffix not in TEXT_SUFFIXES or metadata["size"] > 5_000_000:
                continue
            extension = ".whl" if metadata["store"] == "wheelhouse" else ".blob"
            blob = root / "shared" / metadata["store"] / (metadata["sha256"] + extension)
            try:
                texts[path] = blob.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
        directives = copy_directives(environment / "Dockerfile")
        sources = [source for source, _ in directives]
        logical_environment = {p.relative_to(environment).as_posix() for p in environment.rglob("*") if p.is_file()}
        logical_environment.update(Path(p).relative_to(environment.relative_to(root)).as_posix() for p in paths)
        for source in sources:
            if not any(matches_copy(p, source) for p in logical_environment):
                report["issues"].append({"task": task.name, "kind": "missing_build_source", "path": source})
        wholesale = any(source.rstrip("/") in {".", "assets"} for source, _ in directives)
        for relative in sorted(paths):
            path = root / relative
            if path.is_symlink():
                report["issues"].append({"kind": "asset_symlink", "path": relative})
                continue
            metadata = managed.get(relative)
            digest = metadata["sha256"] if metadata else sha256(path)
            size = metadata["size"] if metadata else path.stat().st_size
            names = [path.name, path.stem] if path.suffix == ".py" else [path.name]
            pattern = re.compile(
                r"(?<![A-Za-z0-9_.-])(?:" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z0-9_.-])"
            )
            references = [p.relative_to(task).as_posix() for p, text in texts.items() if p != path and pattern.search(text)]
            rel_from_env = Path(*Path(relative).parts[3:]).as_posix()
            copies = [source for source, _ in directives if matches_copy(rel_from_env, source)]
            destinations = [dest for source, dest in directives if matches_copy(rel_from_env, source)]
            visibility = visibility_for(destinations)
            parts = set(Path(rel_from_env).parts)
            if path.name in GENERATED_FILES or path.suffix in {".pyc", ".pyo"} or parts & GENERATED_DIRECTORIES:
                report["issues"].append({"kind": "generated_file_in_assets", "path": relative})
            if parts & {"vendor", "dependencies", "wheels", "wheelhouse", "runtime-deps", "runtime-tools", "model-cache", "build"}:
                role = "environment_dependency"
            elif parts & {"science", "harbor", "tools", "runtime", "runtime-source", "scripts", "_runtime"} or path.suffix in {".py", ".sh"}:
                role = "runtime_or_public_tool"
            elif (
                path.name.startswith(("README", "NOTICE", "LICENSE"))
                or path.suffix in {".md", ".sha256"}
                or "provenance" in path.name.lower()
                or "manifest" in path.name.lower()
            ):
                role = "method_contract_or_provenance"
            else:
                role = "scientific_input"
            writable_host = path.is_file() and bool(path.stat().st_mode & 0o222)
            if writable_host and relative.startswith(assets.relative_to(root).as_posix() + "/"):
                report["issues"].append({"kind": "writable_restored_asset", "path": relative})
            report["files"].append(
                {
                    "path": relative,
                    "size": size,
                    "sha256": digest,
                    "role": role,
                    "visibility": visibility,
                    "storage": metadata["store"] if metadata else "task",
                    "present": path.is_file(),
                    "writable_host": writable_host,
                    "wholesale_assets_copy": wholesale,
                    "image_copy_sources": copies,
                    "image_copy_destinations": destinations,
                    "reference_evidence": sorted(references),
                }
            )
        report["tasks"].append(
            {
                "task": task.name,
                "asset_paths": len(paths),
                "has_assets": bool(paths),
                "wholesale_assets_copy": wholesale,
            }
        )
    visibility_bytes = Counter()
    visibility_count = Counter()
    for item in report["files"]:
        visibility_count[item["visibility"]] += 1
        visibility_bytes[item["visibility"]] += item["size"]
    report["summary"] = {
        "task_count": len(report["tasks"]),
        "asset_tasks": sum(t["has_assets"] for t in report["tasks"]),
        "asset_paths": len(report["files"]),
        "roles": dict(Counter(f["role"] for f in report["files"])),
        "visibility_counts": dict(visibility_count),
        "visibility_mib": {key: round(value / (1024**2), 1) for key, value in visibility_bytes.items()},
        "wholesale_copy_tasks": sum(t["wholesale_assets_copy"] for t in report["tasks"]),
        "issues": len(report["issues"]),
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output/task-assets-audit.json")
    args = parser.parse_args()
    report = inventory(ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    for issue in report["issues"][:50]:
        print(json.dumps(issue, ensure_ascii=False))
    if len(report["issues"]) > 50:
        print(f"... {len(report['issues']) - 50} more issues")
    print(f"Audit: {args.output}")
    raise SystemExit(bool(report["issues"]))


if __name__ == "__main__":
    main()
