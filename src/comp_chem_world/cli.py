import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

RESOURCE_SCRIPTS = {
    "inputs": "task_inputs.py",
    "wheels": "task_wheels.py",
    "assets": "task_assets.py",
}


def paint(text: str, color_code: str, stream: TextIO) -> str:
    if "NO_COLOR" in os.environ:
        return text
    if os.environ.get("FORCE_COLOR") or stream.isatty():
        bright_code = {"31": "1;91", "32": "1;92", "33": "1;93", "36": "1;96"}.get(
            color_code, color_code
        )
        return f"\033[{bright_code}m{text}\033[0m"
    return text


def report(label: str, message: str, color_code: str = "36") -> None:
    print(paint(f"[{label}] {message}", color_code, sys.stdout), flush=True)


def fail(message: str) -> None:
    print(paint(f"[ERROR] {message}", "31", sys.stderr), file=sys.stderr)
    raise SystemExit(1)


def project_root() -> Path:
    for path in (Path.cwd().resolve(), *Path.cwd().resolve().parents):
        if (path / "pyproject.toml").is_file() and (path / "scripts").is_dir():
            return path
    raise SystemExit("Run this command from within the comp-chem-world repository.")


def run_resource(
    root: Path,
    kind: str,
    action: str,
    check: bool = True,
    extra: Sequence[str] = (),
) -> None:
    subprocess.run(
        [
            sys.executable,
            "-I",
            str(root / "scripts" / RESOURCE_SCRIPTS[kind]),
            action,
            *extra,
        ],
        cwd=root,
        check=check,
    )


def clean_all(root: Path, check: bool = True) -> None:
    run_resource(root, "assets", "clean", check=check)
    run_resource(root, "wheels", "clean", check=check)


def restore_state_path(root: Path, store: str) -> Path:
    return root / "shared" / store / ".restore-state.json"


def restore_mode(root: Path, store: str) -> str | None:
    path = restore_state_path(root, store)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return "all"
    mode = data.get("mode", "all")
    return mode if mode in {"all", "subset"} else "all"


def any_restore_state(root: Path) -> bool:
    return any(restore_state_path(root, store).exists() for store in ("wheelhouse", "asset-store"))


def inputs_restored(root: Path) -> bool:
    """True only when both stores are restored in full (mode=all)."""
    modes = [restore_mode(root, store) for store in ("wheelhouse", "asset-store")]
    return all(mode == "all" for mode in modes)


def task_prefixes_from_subset(root: Path, subset: Path) -> list[str]:
    scripts = root / "scripts"
    sys.path.insert(0, str(scripts))
    from task_config_paths import task_prefixes_from_config

    path = subset if subset.is_absolute() else (root / subset)
    if not path.is_file():
        raise SystemExit(f"Subset config not found: {path}")
    prefixes = task_prefixes_from_config(path)
    if not prefixes:
        raise SystemExit(f"No tasks found in subset config: {path}")
    return prefixes


def prepare_extra(prefixes: list[str] | None) -> list[str]:
    if not prefixes:
        return []
    extra: list[str] = []
    for prefix in prefixes:
        extra.extend(["--prefix", prefix])
    return extra


def prepare_all(root: Path, prefixes: list[str] | None = None) -> None:
    if prefixes is None and inputs_restored(root):
        report("OK", "Task inputs are already restored.", "32")
        return
    if prefixes is not None and inputs_restored(root):
        report("OK", "Full task inputs are already restored (covers the requested subset).", "32")
        return
    if any_restore_state(root):
        raise SystemExit("Task inputs are already restored (possibly a subset); run 'uv run reset' first.")
    if prefixes:
        report(
            "SETUP",
            f"Restoring task inputs for {len(prefixes)} tasks from subset config; "
            "they will remain available until 'uv run reset'.",
            "33",
        )
    else:
        report("SETUP", "Restoring task inputs; they will remain available until 'uv run reset'.", "33")
    extra = prepare_extra(prefixes)
    try:
        run_resource(root, "wheels", "prepare", extra=extra)
        run_resource(root, "assets", "prepare", extra=extra)
    except BaseException:
        clean_all(root, check=False)
        raise


def ensure_inputs(root: Path) -> None:
    report("CHECK", "Ensuring shared inputs (wheelhouse + asset-store)...")
    run_resource(root, "inputs", "ensure")


def verify_all(root: Path) -> None:
    ensure_inputs(root)
    report("CHECK", "Verifying offline wheels and their task-path mappings...")
    run_resource(root, "wheels", "verify")
    report("CHECK", "Verifying shared scientific assets and their task-path mappings...")
    run_resource(root, "assets", "verify")
    report("OK", "All shared files match their SHA-256 manifests.", "32")


def ensure_docker() -> None:
    report("CHECK", "Checking Docker...")
    if not shutil.which("docker"):
        fail("Docker is required; install and start it first.")
    docker = subprocess.run(
        ["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
    )
    if docker.returncode:
        fail("Docker is unavailable or the current user lacks access.")
    report("OK", "Docker is available.", "32")


def ensure_env_file(root: Path) -> None:
    env_file = root / ".env"
    if env_file.exists():
        report("OK", ".env already exists.", "32")
        return
    shutil.copyfile(root / ".env.example", env_file)
    report(
        "SETUP",
        "Created .env; fill in ANTHROPIC_API_KEY and ANTHROPIC_BASE_URL before running a model.",
        "33",
    )


def build_images(root: Path) -> None:
    report("BUILD", "Building base images; cached layers will be reused.")
    subprocess.run(["bash", str(root / "images" / "build.sh")], cwd=root, check=True)


def initialize(
    root: Path,
    *,
    inputs_only: bool = False,
    subset: Path | None = None,
) -> None:
    prefixes = task_prefixes_from_subset(root, subset) if subset is not None else None
    if inputs_only:
        report("SETUP", "Inputs-only init: skipping Docker, .env, and image builds.", "33")
    else:
        ensure_docker()
        ensure_env_file(root)
    verify_all(root)
    prepare_all(root, prefixes)
    if inputs_only:
        report("OK", "Task inputs restored; run 'uv run init' later for Docker and images.", "32")
        return
    build_images(root)
    report("OK", "Initialization complete; task inputs are ready for repeated evaluations.", "32")


def parse_init_arguments(arguments: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="init",
        description="Restore shared task inputs and prepare the local environment.",
    )
    parser.add_argument(
        "--inputs-only",
        action="store_true",
        help="Only verify and restore shared wheels/assets; skip Docker, .env, and image builds.",
    )
    parser.add_argument(
        "-s",
        "--subset",
        type=Path,
        metavar="CONFIG",
        help=(
            "Harbor job config whose tasks.path entries limit restore "
            "(default: restore all tasks). Example: configs/local-a-selected-20.yaml"
        ),
    )
    return parser.parse_args(arguments)


def parse_pack_arguments(arguments: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pack",
        description=(
            "Pack shared wheelhouse + asset-store into an offline inputs archive. "
            "Recipients place the file at shared/inputs.tar.zst and run uv run init "
            "(optionally with -s for the same subset config)."
        ),
    )
    parser.add_argument(
        "-s",
        "--subset",
        type=Path,
        metavar="CONFIG",
        help=(
            "Harbor job config whose tasks.path entries define the subset archive "
            "(default: pack the full store to shared/inputs.tar.zst)"
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="PATH",
        help=(
            "Output archive path. Default: shared/inputs.tar.zst (full), or "
            "shared/inputs-<config-stem>.tar.zst when -s is set"
        ),
    )
    return parser.parse_args(arguments)


def default_pack_output(root: Path, subset: Path | None) -> Path:
    if subset is None:
        return root / "shared" / "inputs.tar.zst"
    stem = subset.stem if subset.is_absolute() else (root / subset).stem
    return root / "shared" / f"inputs-{stem}.tar.zst"


def pack_inputs(root: Path, *, subset: Path | None = None, output: Path | None = None) -> None:
    default = default_pack_output(root, subset)
    out = output if output is not None else default
    if not out.is_absolute():
        out = root / out

    if subset is None:
        canonical = root / "shared" / "inputs.tar.zst"
        if out.resolve() != canonical.resolve():
            raise SystemExit(
                "Full pack always writes shared/inputs.tar.zst; "
                "omit -o, or pass -s CONFIG for a named subset archive"
            )
        report("PACK", f"Packing full inputs archive -> {canonical}")
        run_resource(root, "inputs", "pack")
        report("OK", f"Packed full inputs archive at {canonical}", "32")
        return

    config = subset if subset.is_absolute() else (root / subset)
    if not config.is_file():
        raise SystemExit(f"Subset config not found: {config}")
    prefixes = task_prefixes_from_subset(root, config)
    report("PACK", f"Packing subset inputs for {len(prefixes)} tasks from {config} -> {out}")
    run_resource(
        root,
        "inputs",
        "pack-subset",
        extra=["--config", str(config), "--output", str(out)],
    )
    report(
        "OK",
        f"Packed subset archive at {out}. Recipients: copy/rename to shared/inputs.tar.zst, "
        f"then `uv run init -s {subset}`.",
        "32",
    )


def execute(command: str, arguments: Sequence[str] = ()) -> None:
    root = project_root()
    try:
        if command == "init":
            options = parse_init_arguments(arguments)
            initialize(root, inputs_only=options.inputs_only, subset=options.subset)
        elif command == "reset":
            if arguments:
                raise SystemExit("Usage: uv run reset")
            clean_all(root)
            print(
                "Removed restored task inputs; kept Docker images, .env, jobs, and the project environment."
            )
        elif command == "pack":
            options = parse_pack_arguments(arguments)
            pack_inputs(root, subset=options.subset, output=options.output)
        else:
            raise SystemExit(f"Unknown command: {command}")
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from error


def command_main() -> None:
    command = Path(sys.argv[0]).name
    execute(command, sys.argv[1:])
