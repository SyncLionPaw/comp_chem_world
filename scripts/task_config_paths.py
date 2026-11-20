"""Parse Harbor job configs for task path prefixes (no PyYAML required for simple configs)."""

from __future__ import annotations

from pathlib import Path


def matches_task_prefix(relative: str, prefixes: list[str]) -> bool:
    return any(
        relative == prefix or relative.startswith(prefix.rstrip("/") + "/")
        for prefix in prefixes
    )


def task_prefixes_from_config(config_path: Path) -> list[str]:
    """Parse task paths from a Harbor job YAML.

    Supports entries shaped like ``- path: tasks/NNN-name`` (optionally with a
    trailing comment). Falls back to PyYAML when available for richer configs.
    """
    text = config_path.read_text(encoding="utf-8")
    prefixes: list[str] = []
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped.startswith("-"):
            continue
        body = stripped[1:].strip()
        if body.startswith("path:"):
            path = body[len("path:") :].strip().strip("'\"")
        elif body.startswith("tasks/"):
            path = body.strip("'\"")
        else:
            continue
        path = path.rstrip("/")
        if not path.startswith("tasks/"):
            raise ValueError(f"Task path must start with tasks/: {path}")
        prefixes.append(path)
    if prefixes:
        return prefixes

    try:
        import yaml
    except ImportError as exc:
        raise SystemExit(
            f"No '- path: tasks/...' entries found in {config_path}; "
            "install PyYAML or pass explicit task paths"
        ) from exc

    data = yaml.safe_load(text)
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        raise ValueError(f"Config has no tasks list: {config_path}")
    for item in data["tasks"]:
        if isinstance(item, str):
            path = item
        elif isinstance(item, dict) and isinstance(item.get("path"), str):
            path = item["path"]
        else:
            raise ValueError(f"Unsupported task entry in {config_path}: {item!r}")
        path = path.strip().rstrip("/")
        if not path.startswith("tasks/"):
            raise ValueError(f"Task path must start with tasks/: {path}")
        prefixes.append(path)
    if not prefixes:
        raise ValueError(f"No tasks found in {config_path}")
    return prefixes
