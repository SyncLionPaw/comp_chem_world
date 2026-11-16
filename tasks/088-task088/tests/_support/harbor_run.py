#!/usr/bin/env python3
"""Launch one Task89 Harbor trial with an evaluator-owned freshness lower bound."""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] != "run":
        print("usage: harbor_run.py run <Harbor run options for exactly one Task89 trial>", file=sys.stderr)
        return 2
    if any(arg in {"-c", "--config", "--dataset", "-d", "--repo", "--task", "-t",
                   "--include-task-name", "-i", "--exclude-task-name", "-x"}
           or arg.startswith(("--config=", "--dataset=", "--repo=", "--task=",
                              "--include-task-name=", "--exclude-task-name=")) for arg in args):
        print("Task89 freshness launcher rejects config/dataset overrides; launch one local Task89 trial", file=sys.stderr)
        return 2
    if any(arg.startswith("--verifier-env=CASE01_EVAL_STARTED_AT_UTC") for arg in args):
        print("CASE01_EVAL_STARTED_AT_UTC is reserved for this launcher", file=sys.stderr)
        return 2
    for index, arg in enumerate(args[:-1]):
        if arg == "--verifier-env" and args[index + 1].startswith("CASE01_EVAL_STARTED_AT_UTC="):
            print("CASE01_EVAL_STARTED_AT_UTC is reserved for this launcher", file=sys.stderr)
            return 2
    task_values = []
    for index, arg in enumerate(args):
        if arg in ("-p", "--path"):
            if index + 1 >= len(args):
                return 2
            task_values.append(args[index + 1])
        elif arg.startswith("--path="):
            task_values.append(arg.split("=", 1)[1])
    task_root = Path(__file__).resolve().parents[2]
    if len(task_values) != 1 or Path(task_values[0]).expanduser().resolve() != task_root:
        print("launcher requires exactly one --path resolving to this Task89 directory", file=sys.stderr)
        return 2

    # Harbor defaults to four concurrent trials; pin all three count controls.
    def requested_count(short, long):
        values = []
        for i, arg in enumerate(args):
            if arg in (short, long):
                if i + 1 >= len(args): return None
                values.append(args[i + 1])
            elif arg.startswith(long + "="):
                values.append(arg.split("=", 1)[1])
            elif short != long and arg.startswith(short) and len(arg) > len(short):
                values.append(arg[len(short):])
        return values
    for short, long in (("-k", "--n-attempts"), ("-n", "--n-concurrent"), ("-l", "--n-tasks")):
        values = requested_count(short, long)
        if values is None or any(value != "1" for value in values):
            print("Task89 freshness launcher accepts exactly one trial and one attempt", file=sys.stderr)
            return 2
    retry_values = requested_count("-r", "--max-retries")
    if retry_values is None or any(value != "0" for value in retry_values):
        print("Task89 freshness launcher rejects retries to preserve its single evaluator window", file=sys.stderr)
        return 2
    harbor = shutil.which("harbor")
    if not harbor:
        sibling = Path(sys.executable).with_name("harbor")
        if sibling.is_file():
            harbor = str(sibling)
    if not harbor:
        print("Harbor executable is unavailable", file=sys.stderr)
        return 2
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    command = [harbor, *args, "--n-attempts", "1", "--n-concurrent", "1", "--n-tasks", "1",
               "--max-retries", "0",
               "--verifier-env", f"CASE01_EVAL_STARTED_AT_UTC={started}"]
    env = os.environ.copy()
    env.pop("CASE01_EVAL_STARTED_AT_UTC", None)
    return subprocess.run(command, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
