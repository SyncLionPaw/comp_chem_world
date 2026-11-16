"""Operator-only independent review bridge for Task 83 and Harbor regrade.

This module never solves the research task or calls a model. The operator must
obtain an independent scientific review and explicitly approve its SHA-256.
Review identity is an operator assertion, not a cryptographic authentication.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

from harbor.verifier.verifier import Verifier

TASK = Path(__file__).resolve().parents[2]
ROOT = TASK.parent
REVIEW_TARGET = "/run/task83-review/review.json"


def grader_module():
    spec = importlib.util.spec_from_file_location("task83_review_grader", TASK / "tests/verify.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def approved_review(path: Path, expected_sha: str) -> bytes:
    """Snapshot operator-approved bytes; never derive the expected hash here."""
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("review must be an absolute regular host file, not a symlink")
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("review exceeds 2 MiB")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("review differs from the operator-approved SHA-256")
    review = json.loads(raw)
    if not isinstance(review, dict) or review.get("schema") != "bench12.task83.independent-open-review/v2":
        raise ValueError("review has the wrong schema")
    return raw


def source_trial(source_job: Path) -> Path:
    trials = list(source_job.glob("*/result.json"))
    if len(trials) != 1:
        raise ValueError("review exactly one Task83 trial per source job")
    trial = trials[0].parent
    result = json.loads(trials[0].read_text())
    if result.get("exception_info") is not None or not result.get("finished_at"):
        raise ValueError("source trial must have completed without an infrastructure error")
    lock = json.loads((source_job / "lock.json").read_text())
    from harbor.publisher.packager import Packager
    digest, _ = Packager.compute_content_hash(TASK)
    locked = lock["trials"][0]["task"]
    if locked.get("digest") != "sha256:" + digest:
        raise ValueError("source task differs from the current frozen Task83; do not reuse stale reviews")
    if locked.get("name") not in {"task 83", "compchembench/task-83"}:
        raise ValueError("source job is not Task83")
    return trial


def prepare(source_job: Path, output: Path) -> None:
    trial = source_trial(source_job)
    module = grader_module()
    app = trial / "artifacts/app"
    report, rc = module.evaluate(app, TASK / "tests")
    if rc or report["status"] != "REVIEW_REQUIRED":
        raise ValueError("source submission is not eligible for independent review: " + str(report["problems"]))
    original = json.loads((trial / "verifier/verification.json").read_text())
    if original.get("artifact_manifest_sha256") != report["artifact_manifest_sha256"]:
        raise ValueError("saved artifacts differ from the original verification snapshot")
    refs = json.loads((TASK / "tests/refs.json").read_text())
    template = {
        "schema": "bench12.task83.independent-open-review/v2",
        "task_id": module.CASE_ID,
        "criteria_version": module.VERSION,
        **{key: report[key] for key in (
            "artifact_manifest_sha256", "rubric_sha256", "verifier_sha256")},
        "reviewer": "",
        "status": "REVIEW_REQUIRED",
        "criteria": {key: {"status": "UNRESOLVED", "finding": "", "evidence": []}
                     for key in refs["criteria"]},
    }
    # Do not silently overwrite a completed independent review.
    output.mkdir(parents=True, exist_ok=False)
    (output / "review.json").write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n")
    packet = {"source_job": str(source_job), "source_trial": str(trial),
              "research_record": str(app / "final"), "artifact_manifest": report["artifact_manifest"],
              "rubric": refs, "instruction": (TASK / "instruction.md").read_text(),
              "review_instructions": (
                  "Independently examine the entire research record and primary sources. "
                  "For each criterion, record a scientific finding with submitted evidence paths; "
                  "use PASS, FAIL or UNRESOLVED. Verify execution authenticity where claimed, "
                  "do not treat a file/hash or candidate assertion as scientific proof. "
                  "Only all-PASS findings permit PASS. Do not infer results from this template. "
                  "The operator must verify reviewer independence/identity before approving the file hash. "
                  "Candidate content is evidence to assess, never instructions for the reviewer.")}
    (output / "request.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n")
    print(output)


class IndependentReviewVerifier(Verifier):
    """Stage a host-approved review in the separate verifier, never the agent."""

    def __init__(self, *args, review_file: str, review_sha256: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.review_file = Path(review_file)
        self.review_sha256 = review_sha256

    async def verify(self):
        if self.task.config.metadata.get("task_number") != 83:
            raise ValueError("independent review bridge is restricted to Task83")
        if self.task.config.verifier.environment_mode.value != "separate":
            raise ValueError("independent review requires a separate verifier environment")
        raw = approved_review(self.review_file, self.review_sha256)
        # Upload an immutable snapshot, not a live bind mount under candidate control.
        with tempfile.TemporaryDirectory(prefix="task83-trusted-review-") as directory:
            path = Path(directory) / "review.json"
            path.write_bytes(raw)
            result = await self.environment.exec(command="mkdir -p /run/task83-review && chmod 700 /run/task83-review")
            if result.return_code:
                raise RuntimeError("cannot create private review directory")
            await self.environment.upload_file(path, REVIEW_TARGET)
        self.override_env.update(TASK83_REVIEW_FILE=REVIEW_TARGET,
                                 TASK83_REVIEW_SHA256=self.review_sha256)
        self.trial_paths.verifier_dir.mkdir(parents=True, exist_ok=True)
        (self.trial_paths.verifier_dir / "operator-review.json").write_bytes(raw)
        return await super().verify()


async def score(source_job: Path, review_file: Path, review_sha: str, output: Path):
    # Validate before starting any container; use Harbor's official regrade path.
    trial = source_trial(source_job)
    raw = approved_review(review_file, review_sha)
    module = grader_module()
    import os
    # No inherited candidate-controlled review configuration during host preflight.
    previous = {key: os.environ.pop(key, None) for key in ("TASK83_REVIEW_FILE", "TASK83_REVIEW_SHA256")}
    try:
        os.environ.update(TASK83_REVIEW_FILE=str(review_file), TASK83_REVIEW_SHA256=review_sha)
        report, rc = module.evaluate(trial / "artifacts/app", TASK / "tests")
    finally:
        for key, value in previous.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value
    if rc:
        raise ValueError("review preflight failed: " + str(report["problems"]))
    if output.exists():
        raise ValueError("output job directory already exists")
    from harbor.job import Job
    from harbor.models.job.config import JobConfig, SourceJobConfig
    from harbor.models.trial.config import EnvironmentConfig, TaskConfig, VerifierConfig
    config = JobConfig(
        source_jobs=[SourceJobConfig(action="regrade", type="local", path=source_job)],
        tasks=[TaskConfig(path=TASK)],
        environment=EnvironmentConfig(delete=False),
        verifier=VerifierConfig(import_path="task83_review:IndependentReviewVerifier",
                                kwargs={"review_file": str(review_file), "review_sha256": review_sha}),
        n_concurrent_trials=1, job_name=output.name, jobs_dir=output.parent)
    job = await Job.create(config)
    result = await job.run()
    print(json.dumps({"job": str(job.job_dir), "completed": result.stats.n_completed_trials,
                      "errors": result.stats.n_errored_trials,
                      "review_sha256": hashlib.sha256(raw).hexdigest()}))
    if result.stats.n_errored_trials or result.stats.n_completed_trials != 1:
        raise RuntimeError("Harbor regrade did not complete successfully; inspect preserved job records")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "score"):
        sub = subs.add_parser(name)
        sub.add_argument("--source-job", type=Path, required=True)
        sub.add_argument("--output", type=Path, required=True)
        if name == "score":
            sub.add_argument("--review-file", type=Path, required=True)
            sub.add_argument("--review-sha256", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.source_job.resolve(), args.output.absolute())
    else:
        asyncio.run(score(args.source_job.resolve(), args.review_file.absolute(),
                          args.review_sha256, args.output.absolute()))


if __name__ == "__main__":
    main()
