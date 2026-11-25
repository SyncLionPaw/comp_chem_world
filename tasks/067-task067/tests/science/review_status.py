"""Adjudicate open scientific criteria with a Harbor RewardKit LLM judge."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_fingerprints(tests: Path) -> dict[str, str]:
    result = {}
    for p in sorted(tests.rglob("*")):
        rel = p.relative_to(tests).as_posix()
        if p.is_symlink():
            raise RuntimeError(f"trusted tests tree contains a symlink: {rel}")
        if (
            p.is_file()
            and p.name != "author-review.json"
            and p.suffix != ".pyc"
            and "__pycache__" not in p.parts
        ):
            result[rel] = sha(p)
    return result


def output_manifest(app: Path, protocol: dict) -> dict[str, dict[str, object]]:
    """Hash only declared output paths, recursively expanding declared directories."""
    manifest = {}
    selected = set()
    for rel in protocol["output_contract"]["required_paths"]:
        is_dir = rel.endswith("/")
        path = app / rel.rstrip("/")
        try:
            path.relative_to(app)
        except ValueError as exc:
            raise ValueError(f"candidate output path escapes APP: {rel}") from exc
        if any(p.is_symlink() for p in (path, *path.parents) if p == app or app in p.parents):
            raise ValueError(f"candidate output path contains a symlink: {rel}")
        if is_dir:
            if not path.is_dir():
                raise ValueError(f"candidate output directory missing: {rel}")
            descendants = sorted(path.rglob("*"))
            if not descendants or not any(p.is_file() for p in descendants):
                raise ValueError(f"candidate output directory is empty: {rel}")
            for item in descendants:
                if item.is_symlink():
                    raise ValueError(f"candidate output directory contains a symlink: {item.relative_to(app)}")
                if item.is_file():
                    selected.add(item)
                elif not item.is_dir():
                    raise ValueError(f"candidate output directory contains a special file: {item.relative_to(app)}")
        else:
            if not path.is_file():
                raise ValueError(f"candidate output missing: {rel}")
            selected.add(path)
    for path in sorted(selected):
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError(f"candidate output is not a regular file: {path.relative_to(app)}")
        manifest[path.relative_to(app).as_posix()] = {"sha256": sha(path), "bytes": path.stat().st_size}
    return manifest


def preflight_trusted_sources(app: Path, tests: Path):
    index = tests / "reference-hashes.json"
    if index.is_symlink() or not index.is_file():
        raise RuntimeError("trusted reference-hashes.json is missing or unsafe")
    try:
        entries = json.loads(index.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"trusted reference-hashes.json cannot be decoded: {exc}") from exc
    if not isinstance(entries, dict):
        raise RuntimeError("trusted reference hash index must be a JSON object")
    for rel, expected in entries.items():
        if not isinstance(rel, str) or not isinstance(expected, str):
            raise RuntimeError("trusted reference hash entry is malformed")
        if Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise RuntimeError(f"trusted reference path is unsafe: {rel}")
        if rel.startswith("tests/"):
            path = tests / rel.removeprefix("tests/")
        elif rel.startswith("environment/assets/"):
            path = app / rel
        else:
            raise RuntimeError(f"trusted reference path is outside supported scope: {rel}")
        if path.is_symlink() or not path.is_file() or sha(path) != expected:
            raise RuntimeError(f"trusted reference hash mismatch or missing file: {rel}")
    protocol_path = tests / "assessment-protocol.json"
    if protocol_path.is_symlink() or not protocol_path.is_file():
        raise RuntimeError("trusted assessment protocol is missing or unsafe")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    for rel, expected in protocol.get("inputs", {}).items():
        path = app / rel
        if path.is_symlink() or not path.is_file() or sha(path) != expected:
            raise RuntimeError(f"trusted public input hash mismatch or missing file: {rel}")
    judge_toml = tests / "llm_judge" / "judge.toml"
    if judge_toml.is_symlink() or not judge_toml.is_file():
        raise RuntimeError("trusted llm_judge/judge.toml is missing or unsafe")



def resolve_judge_file(app: Path, path_str: str) -> Path:
    """Map Harbor /app paths (or relative paths) onto the verifier workspace."""
    raw = Path(path_str)
    if raw.is_absolute():
        try:
            rel = raw.relative_to("/app")
        except ValueError:
            return raw
        return app / rel
    return app / raw


def materialize_judge_dir(tests: Path, app: Path, dest: Path) -> Path:
    """Write a judge.toml whose files= entries are absolute host paths under app.

    RewardKit reads judge files with Path(path).exists() and does not join --workspace.
    """
    src_toml = tests / "llm_judge" / "judge.toml"
    text = src_toml.read_text(encoding="utf-8")
    match = re.search(r"^files = (\[.*\])$", text, flags=re.M)
    if not match:
        raise RuntimeError("llm_judge/judge.toml is missing a files = [...] entry")
    files = json.loads(match.group(1))
    if not isinstance(files, list) or not all(isinstance(x, str) for x in files):
        raise RuntimeError("llm_judge/judge.toml files entry must be a string array")
    resolved = [str(resolve_judge_file(app, item).resolve()) for item in files]
    rewritten = text[: match.start(1)] + json.dumps(resolved) + text[match.end(1) :]
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / "judge.toml"
    out.write_text(rewritten, encoding="utf-8")
    return dest


def rewardkit_bin() -> list[str]:
    """Prefer a local rewardkit, otherwise uvx the pinned Harbor package."""
    local = shutil.which("rewardkit")
    if local:
        return [local]
    uvx = shutil.which("uvx")
    if not uvx:
        raise RuntimeError("neither rewardkit nor uvx is available in the verifier environment")
    return [
        uvx,
        "--python",
        ">=3.12,<3.14",
        "--from",
        "harbor-rewardkit==0.2.*",
        "rewardkit",
    ]


def judge_credentials() -> tuple[str, str, str]:
    """Resolve judge key/base/model; REWARDKIT_* wins over agent ANTHROPIC_*."""
    key = (
        os.environ.get("REWARDKIT_API_KEY", "").strip()
        or os.environ.get("ANTHROPIC_API_KEY", "").strip()
    )
    base = (
        os.environ.get("REWARDKIT_BASE_URL", "").strip()
        or os.environ.get("ANTHROPIC_BASE_URL", "").strip()
    )
    model = os.environ.get("REWARDKIT_JUDGE", "").strip()
    return key, base, model


def run_llm_judge(app: Path, tests: Path, logs: Path) -> dict:
    """Run RewardKit on tests/llm_judge; return scores and side-car details."""
    key, base, model = judge_credentials()
    if not key:
        raise RuntimeError(
            "REWARDKIT_API_KEY (or ANTHROPIC_API_KEY fallback) is required for LLM scientific review; "
            "no review request was made"
        )
    logs.mkdir(parents=True, exist_ok=True)
    out = logs / "llm-judge-reward.json"
    timeout = int(os.environ.get("LLM_JUDGE_TIMEOUT_SEC", "900"))
    env = os.environ.copy()
    # RewardKit/LiteLLM read Anthropic-compatible credentials from ANTHROPIC_*.
    env["ANTHROPIC_API_KEY"] = key
    if base:
        env["ANTHROPIC_BASE_URL"] = base
        env["ANTHROPIC_API_BASE"] = base
    else:
        env.pop("ANTHROPIC_BASE_URL", None)
        env.pop("ANTHROPIC_API_BASE", None)
    with tempfile.TemporaryDirectory(prefix="llm-judge-") as tmp:
        judge_dir = materialize_judge_dir(tests, app, Path(tmp))
        cmd = [
            *rewardkit_bin(),
            str(judge_dir),
            "--workspace",
            str(app),
            "--output",
            str(out),
        ]
        if model:
            cmd.extend(["--judge", model])
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-4000:]
        raise RuntimeError(f"rewardkit failed (exit {proc.returncode}): {detail or 'no output'}")
    if not out.is_file():
        raise RuntimeError("rewardkit exited 0 but did not write llm-judge-reward.json")
    try:
        scores = json.loads(out.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"rewardkit wrote invalid reward JSON: {exc}") from exc
    if not isinstance(scores, dict) or not scores:
        raise RuntimeError(f"rewardkit returned unexpected scores: {scores!r}")
    details = None
    for candidate in (
        out.with_name("reward-details.json"),
        out.with_name("llm-judge-reward-details.json"),
        logs / "reward-details.json",
    ):
        if candidate.is_file():
            try:
                details = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                details = {"raw_path": candidate.as_posix()}
            break
    return {
        "scores": scores,
        "details": details,
        "stdout_tail": (proc.stdout or "")[-2000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
    }


def judge_score(scores: dict) -> float:
    """Extract the RewardKit aggregate score in [0, 1]."""
    if "judge" in scores:
        value = scores["judge"]
    elif "reward" in scores:
        value = scores["reward"]
    elif len(scores) == 1:
        value = next(iter(scores.values()))
    else:
        raise RuntimeError(f"rewardkit returned ambiguous scores: {scores!r}")
    if not isinstance(value, (int, float)):
        raise RuntimeError(f"rewardkit score is not numeric: {value!r}")
    score = float(value)
    if score < -1e-9 or score > 1.0 + 1e-9:
        raise RuntimeError(f"rewardkit score out of range: {score}")
    return min(1.0, max(0.0, score))


def adjudicate(app: Path, tests: Path, diagnostic: dict, logs: Path | None = None) -> dict:
    """Return scoring status; missing API key or judge failure is infrastructure error.

    Successful LLM grading always yields status PASS with a continuous reward in
    [0, 1] (rubric weighted-mean). Structural diagnostic failures stay FAIL/0.
    """
    preflight_trusted_sources(app, tests)
    if diagnostic.get("status") == "FAIL":
        return {**diagnostic, "status": "FAIL", "reward": 0.0}
    if diagnostic.get("status") != "REVIEW_REQUIRED":
        raise RuntimeError("diagnostic did not return a valid candidate/review status")
    protocol = json.loads((tests / "assessment-protocol.json").read_text(encoding="utf-8"))
    try:
        candidate = output_manifest(app, protocol)
    except ValueError as exc:
        return {**diagnostic, "status": "FAIL", "reward": 0.0, "candidate_error": str(exc)}
    judge_logs = logs if logs is not None else Path(os.environ.get("LOGS", "/logs/verifier"))
    judge = run_llm_judge(app, tests, judge_logs)
    score = judge_score(judge["scores"])
    return {
        **diagnostic,
        "status": "PASS",
        "reward": score,
        "reward_status": "AWARDED",
        "candidate_manifest": candidate,
        "scientific_review": {
            "reviewer": "harbor-rewardkit-llm-judge",
            "mode": "rubric-weighted-mean",
            "partial_credit": True,
            "scores": judge["scores"],
            "details": judge["details"],
        },
    }


def run_case(app: Path, tests: Path, logs: Path) -> int:
    import sys

    sys.path.insert(0, str(tests))
    try:
        preflight_trusted_sources(app, tests)
        import diagnostic

        result = adjudicate(app, tests, diagnostic.run(app, tests), logs=logs)
        status = result.get("status")
        code = 1 if status == "FAIL" else 0 if status == "PASS" else 2
        if code == 2:
            result = {"status": "INFRA_ERROR", "error": "invalid final status", "diagnostic": result}
    except Exception as exc:
        result = {"status": "INFRA_ERROR", "error": f"{type(exc).__name__}: {exc}"}
        code = 2
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "report.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    reward = logs / "reward.txt"
    if result.get("status") in {"PASS", "FAIL"} and isinstance(result.get("reward"), (int, float)):
        reward.write_text(f"{float(result['reward']):.6g}\n", encoding="utf-8")
    elif reward.exists():
        reward.unlink()
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return code
