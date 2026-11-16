import argparse
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


def run_resource(root: Path, kind: str, action: str, check: bool = True) -> None:
    subprocess.run(
        [sys.executable, "-I", str(root / "scripts" / RESOURCE_SCRIPTS[kind]), action],
        cwd=root,
        check=check,
    )


def clean_all(root: Path, check: bool = True) -> None:
    run_resource(root, "assets", "clean", check=check)
    run_resource(root, "wheels", "clean", check=check)


def inputs_restored(root: Path) -> bool:
    return all(
        (root / "shared" / store / ".restore-state.json").is_file()
        for store in ("wheelhouse", "asset-store")
    )


def prepare_all(root: Path) -> None:
    if inputs_restored(root):
        report("OK", "Task inputs are already restored.", "32")
        return
    if any(
        (root / "shared" / store / ".restore-state.json").exists()
        for store in ("wheelhouse", "asset-store")
    ):
        raise SystemExit("Task inputs are only partially restored; run 'uv run reset' first.")
    report("SETUP", "Restoring task inputs; they will remain available until 'uv run reset'.", "33")
    try:
        run_resource(root, "wheels", "prepare")
        run_resource(root, "assets", "prepare")
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
    report("SETUP", "Created .env; fill in DEEPSEEK_API_KEY before running a model.", "33")


def build_images(root: Path) -> None:
    report("BUILD", "Building base images; cached layers will be reused.")
    subprocess.run(["bash", str(root / "images" / "build.sh")], cwd=root, check=True)


def initialize(root: Path, *, inputs_only: bool = False) -> None:
    if inputs_only:
        report("SETUP", "Inputs-only init: skipping Docker, .env, and image builds.", "33")
    else:
        ensure_docker()
        ensure_env_file(root)
    verify_all(root)
    prepare_all(root)
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
    return parser.parse_args(arguments)


def execute(command: str, arguments: Sequence[str] = ()) -> None:
    root = project_root()
    try:
        if command == "init":
            options = parse_init_arguments(arguments)
            initialize(root, inputs_only=options.inputs_only)
        elif command == "reset":
            if arguments:
                raise SystemExit("Usage: uv run reset")
            clean_all(root)
            print("Removed restored task inputs; kept Docker images, .env, jobs, and the project environment.")
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from error


def command_main() -> None:
    command = Path(sys.argv[0]).name
    execute(command, sys.argv[1:])
