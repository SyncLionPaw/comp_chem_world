"""Validate the evaluator-only historical Case01 archive route.

This route binds a replay to the historical 9806 inputs. It is separate from
the Agent v1 trusted-execution receipt and never establishes fresh execution.
"""
from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path, PurePosixPath

CONTEXT_PATH = Path("/trusted/case01-author/context.json")
ARCHIVE_PATH = Path("/author_archive")
CONTEXT_SCHEMA = "case01-author-historical-oracle-context-v1"
TRANSFER_SCHEMA = "case01-historical-trajectory-transfer-v1"
RECEIPT_SCHEMA = "case01-historical-author-archive-receipt-v2"
ANCESTRY_SCHEMA = "case01-obtained-equilibration-evidence-v1"
EXPECTED_XTC_SHA256 = "ebecff6bd1845d3368fd5f23c010e269b6415cf29e4ec69c89c4721b4d46e708"
EXPECTED_XTC_BYTES = 1_978_683_908
EXPECTED_V2_SHA256 = "ffdc47e19c60721c4476fbf01c0aba1baf6d2a1ab7c3f027a97a1cc29a316eaf"
EXPECTED_ANCESTRY_SHA256 = "6a2a4afdfefaaaf6b4d3771e3a5e351eabfa8894fed9ed83e62d18751f0463a6"
EXPECTED_9136_RECEIPT_SHA256 = "801ddd19e65968bf57b5bdd17aca15a3a96e26478ddf9bb2e1ef9c3198a78a4b"
EXPECTED_9806_WORKDIR = "/public/home/xjchen/14_Interficial-Hydration-Force/case01/reference-replicate-20261007"
EXPECTED_9136_WORKDIR = "/public/home/xjchen/14_Interficial-Hydration-Force/case01/corrected-spce"
EXPECTED_9136_WORKFLOW_EVIDENCE_SHA256 = {
    "resume-execution.json": "e8bc2ef52f527f52b634f1ca02bdffcbc842d01aadd7ecb277decf7158236439",
    "resume-manifest-9044.json": "b845f67c5e9fb8c5b7e6c2132e1cc281739c7aa30a2c15bfa010a02698c5655b",
    "submission-input-hashes.txt": "14d010642b32dae93c8fa347bf30c4b82e010e0876b3a18c6b54dd048bd947b7",
    "resume-input-hashes.txt": "4d6b08625fb0b897812762226809d8973ac665b22134849ef34a7eec22ae928a",
}
EXPECTED_9136_SHARED_INPUTS = {
    "acceptance/case01-science-plan-2026-10-06.md",
    "analysis/audit_tpr_exclusions.py",
    "analysis/audit_tpr_settings.py",
    "analysis/independent_validation.py",
    "analysis/summarize_science_audit.py",
    "em.mdp", "npt.mdp", "nvt.mdp", "production.mdp",
    "setup.sh", "topol.template.top",
}
EXPECTED_9136_SCIENCE_PLAN_SHA256 = "f075a15c82b625a22a1b37a3548075ff8e483ed824a5554fe083f549e0875dac"


class HistoricalArchiveError(ValueError):
    """The evaluator historical context or its archive does not match its pins."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _regular_file(path: Path, what: str) -> Path:
    raw = Path(path)
    if raw.is_symlink():
        raise HistoricalArchiveError(f"{what} may not be a symlink")
    try:
        mode = raw.lstat().st_mode
    except OSError as exc:
        raise HistoricalArchiveError(f"{what} is unavailable: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise HistoricalArchiveError(f"{what} must be a regular file")
    return raw


def _read_json(path: Path, what: str) -> dict:
    _regular_file(path, what)

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key {key!r}")
            value[key] = item
        return value

    try:
        result = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                            parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"invalid JSON constant {x}")))
    except Exception as exc:
        raise HistoricalArchiveError(f"{what} is not valid JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise HistoricalArchiveError(f"{what} must contain a JSON object")
    return result


def _relative_file(root: Path, relative: str, what: str) -> Path:
    rel = PurePosixPath(relative)
    if rel.is_absolute() or rel.as_posix() != relative or not rel.parts or any(p in {".", ".."} for p in rel.parts):
        raise HistoricalArchiveError(f"{what} path is not canonical and relative")
    target = root.joinpath(*rel.parts)
    cursor = root
    for part in rel.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise HistoricalArchiveError(f"{what} path may not traverse symlinks")
    return _regular_file(target, what)


def _valid_sha(value: object, name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise HistoricalArchiveError(f"{name} must be a lowercase SHA-256")
    return value


def _parse_input_hashes(path: Path, what: str) -> dict[str, str]:
    """Parse a frozen sha256sum-style manifest without accepting path ambiguity."""
    result = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        parts = line.split()
        if len(parts) != 2 or re.fullmatch(r"[0-9a-f]{64}", parts[0]) is None:
            raise HistoricalArchiveError(f"{what} has a malformed row at line {number}")
        rel = PurePosixPath(parts[1])
        if (rel.is_absolute() or rel.as_posix() != parts[1] or not rel.parts
                or any(part in {".", ".."} for part in rel.parts)):
            raise HistoricalArchiveError(f"{what} has a non-canonical path at line {number}")
        if parts[1] in result:
            raise HistoricalArchiveError(f"{what} repeats a path: {parts[1]}")
        result[parts[1]] = parts[0]
    if not result:
        raise HistoricalArchiveError(f"{what} is empty")
    return result


def _validate_9136_workflow_evidence(archive: Path, prior_receipt: dict,
                                     expected_file_hashes: dict[str, str] | None = None) -> dict:
    """Derive the old workflow claims from separately pinned primary provenance."""
    expected_file_hashes = (EXPECTED_9136_WORKFLOW_EVIDENCE_SHA256
                            if expected_file_hashes is None else expected_file_hashes)
    root = archive / "ancestry9136" / "workflow-evidence"
    evidence = {}
    for name, expected_sha in expected_file_hashes.items():
        path = _relative_file(root, name, f"9136 workflow evidence {name}")
        if sha256_file(path) != expected_sha:
            raise HistoricalArchiveError(f"pinned 9136 workflow evidence changed: {name}")
        evidence[name] = path

    resume_execution = _read_json(evidence["resume-execution.json"], "9136 resume execution provenance")
    resume_manifest = _read_json(evidence["resume-manifest-9044.json"], "9044-to-9136 continuation manifest")
    submission = _parse_input_hashes(evidence["submission-input-hashes.txt"], "9136 original input manifest")
    resumed = _parse_input_hashes(evidence["resume-input-hashes.txt"], "9136 resumed input manifest")

    execution_submission = resume_execution.get("original_submission_manifest", {})
    execution_resume = resume_execution.get("resume_input_manifest", {})
    manifest_submission = resume_manifest.get("original_submission_manifest", {})
    manifest_resume = resume_manifest.get("resume_input_manifest", {})
    if (resume_execution.get("schema") != "case01-resume-provenance-v1"
            or resume_execution.get("original_job_id") != "9044"
            or resume_execution.get("resume_job_id") != "9136"
            or resume_manifest.get("schema") != "case01-resume-manifest-v1"
            or resume_manifest.get("from_job") != "9044"
            or resume_manifest.get("from_job_outcome") != "FAILED_BEFORE_NPT_MDRUN"
            or resume_manifest.get("status") != "READY_FOR_SINGLE_CONTINUATION"
            or execution_submission.get("path") != "submission-input-hashes.txt"
            or execution_submission.get("sha256") != expected_file_hashes["submission-input-hashes.txt"]
            or execution_resume.get("path") != "resume-input-hashes.txt"
            or execution_resume.get("sha256") != expected_file_hashes["resume-input-hashes.txt"]
            or manifest_submission.get("sha256") != expected_file_hashes["submission-input-hashes.txt"]
            or manifest_resume.get("sha256") != expected_file_hashes["resume-input-hashes.txt"]):
        raise HistoricalArchiveError("pinned 9044-to-9136 job mapping or input-manifest binding is invalid")

    continuation = resume_manifest.get("continuation", {})
    if (continuation.get("scientific_parameters_changed") is not False
            or continuation.get("science_plan_changed") is not False):
        raise HistoricalArchiveError("9136 continuation provenance reports changed science parameters or plan")

    shared = set(submission) & set(resumed)
    if shared != EXPECTED_9136_SHARED_INPUTS or any(submission[name] != resumed[name] for name in shared):
        raise HistoricalArchiveError("9136 continuation changed a shared scientific input or omitted a required one")
    if submission.get("acceptance/case01-science-plan-2026-10-06.md") != EXPECTED_9136_SCIENCE_PLAN_SHA256:
        raise HistoricalArchiveError("9136 continuation does not bind the frozen scientific plan")

    records = prior_receipt.get("accounting_records", [])
    completed_job_records = {row.get("job_id"): row for row in records if isinstance(row, dict)}
    expected_workdir = EXPECTED_9136_WORKDIR
    main = completed_job_records.get("9136", {})
    batch = completed_job_records.get("9136.batch", {})
    expected_accounting = {
        "state": "COMPLETED", "exit_code": "0:0", "elapsed_seconds": "3994",
        "start": "2026-10-06T23:30:49", "end": "2026-10-07T00:37:23",
    }
    if (prior_receipt.get("job_id") != "9136" or prior_receipt.get("ancestral_job_id") != "9044"
            or prior_receipt.get("job_state") != "COMPLETED" or prior_receipt.get("exit_code") != "0:0"
            or any(main.get(key) != value for key, value in expected_accounting.items())
            or main.get("job_id") != "9136" or main.get("workdir") != expected_workdir
            or any(batch.get(key) != value for key, value in expected_accounting.items())
            or batch.get("job_id") != "9136.batch" or batch.get("workdir") != ""):
        raise HistoricalArchiveError("9136 primary and batch accounting do not support the pinned continuation")

    declared_resume_entries = manifest_resume.get("entries")
    return {
        "resume_job_id": "9136",
        "original_job_id": "9044",
        "shared_scientific_inputs_equal": True,
        "shared_scientific_input_count": len(shared),
        "science_plan_sha256": EXPECTED_9136_SCIENCE_PLAN_SHA256,
        "resume_manifest_declared_entries": declared_resume_entries,
        "resume_manifest_parsed_entries": len(resumed),
        "resume_manifest_entry_count_discrepancy": declared_resume_entries != len(resumed),
        "source_file_hashes": dict(expected_file_hashes),
    }


def validate_context_document(context: dict, archive_root: Path) -> dict:
    """Validate pins and every archived byte needed by the historical replay."""
    required = {
        "schema", "case_id", "task_id", "route", "model", "execution_source",
        "agent_fresh", "agent_reward", "archive_mount", "archive_v2_sha256",
        "transfer_manifest_sha256", "xtc_sha256", "xtc_size_bytes",
        "ancestry_manifest_sha256", "trusted_9136_receipt_sha256",
        "canonical_package_source_sha256", "image_id",
    }
    if set(context) != required or context.get("schema") != CONTEXT_SCHEMA:
        raise HistoricalArchiveError("historical Oracle context schema or exact key set is invalid")
    expected = {
        "case_id": "case-01-water-md-response",
        "task_id": "14_Interficial-Hydration-Force/case-01-water-md-response",
        "route": "historical_author_oracle",
        "model": None,
        "execution_source": "explicit_historical_author_archive",
        "agent_fresh": False,
        "agent_reward": None,
        "archive_mount": "/author_archive",
        "xtc_sha256": EXPECTED_XTC_SHA256,
        "xtc_size_bytes": EXPECTED_XTC_BYTES,
        "ancestry_manifest_sha256": EXPECTED_ANCESTRY_SHA256,
        "trusted_9136_receipt_sha256": EXPECTED_9136_RECEIPT_SHA256,
        "archive_v2_sha256": EXPECTED_V2_SHA256,
    }
    if any(context.get(key) != value for key, value in expected.items()):
        raise HistoricalArchiveError("historical Oracle context selects an unapproved identity or evidence scope")
    for key in ("archive_v2_sha256", "transfer_manifest_sha256", "canonical_package_source_sha256"):
        _valid_sha(context.get(key), key)
    image_id = context.get("image_id")
    if not isinstance(image_id, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise HistoricalArchiveError("image_id must be a resolved immutable SHA-256 image ID")

    archive = Path(archive_root)
    if archive.is_symlink() or not archive.is_dir():
        raise HistoricalArchiveError("historical archive mount is missing or redirected")
    v2_path = _relative_file(archive, "historical-author-archive-integrity-v2.json", "v2 archive integrity record")
    transfer_path = _relative_file(archive, "trajectory-transfer-manifest-v1.json", "trajectory transfer manifest")
    collection_path = _relative_file(archive, "collection-manifest.json", "collection manifest")
    ancestry_path = _relative_file(archive, "ancestry9136/equilibration-manifest.json", "9136 equilibration manifest")
    prior_receipt_path = _relative_file(archive, "ancestry9136/trusted-execution-receipt-v1.json", "9136 historical receipt")
    xtc_path = _relative_file(archive, "production.xtc", "historical production XTC")
    for key, path in (("archive_v2_sha256", v2_path), ("transfer_manifest_sha256", transfer_path),
                      ("ancestry_manifest_sha256", ancestry_path), ("trusted_9136_receipt_sha256", prior_receipt_path)):
        if sha256_file(path) != context[key]:
            raise HistoricalArchiveError(f"{key} does not match the protected mounted evidence")
    if xtc_path.stat().st_size != EXPECTED_XTC_BYTES or sha256_file(xtc_path) != EXPECTED_XTC_SHA256:
        raise HistoricalArchiveError("mounted production XTC does not match the remote historical digest and byte count")

    v2 = _read_json(v2_path, "v2 archive integrity record")
    if (v2.get("schema") != RECEIPT_SCHEMA or v2.get("record_type") != "unsigned_historical_archive_integrity_record"
            or v2.get("evidence_origin") != "explicit_historical_author_archive"
            or v2.get("controller_trusted_source") is not False or v2.get("fresh_for_agent") is not False
            or v2.get("formal_reward") is not None or v2.get("public_verifier_compatible") is not False
            or v2.get("job", {}).get("job_id") != "9806"
            or v2.get("job", {}).get("workdir") != EXPECTED_9806_WORKDIR
            or v2.get("job", {}).get("scontrol_status") != "UNKNOWN_EXPIRED"):
        raise HistoricalArchiveError("v2 record is not the exact unsigned, expired-controller 9806 history")
    accounting=v2.get("job",{}).get("accounting",{})
    main_job=accounting.get("9806",{}) if isinstance(accounting,dict) else {}
    batch_job=accounting.get("9806.batch",{}) if isinstance(accounting,dict) else {}
    expected_accounting={"state":"COMPLETED","exit_code":"0:0","elapsed":"01:08:15",
                         "start":"2026-10-07T20:33:58","end":"2026-10-07T21:42:13"}
    if (any(main_job.get(k)!=v for k,v in expected_accounting.items())
            or main_job.get("job_id_raw")!="9806" or main_job.get("workdir")!=EXPECTED_9806_WORKDIR
            or any(batch_job.get(k)!=v for k,v in expected_accounting.items())
            or batch_job.get("job_id_raw")!="9806.batch" or batch_job.get("workdir")!=""):
        raise HistoricalArchiveError("durable sacct main/batch records do not bind the completed 9806 archive")

    transfer = _read_json(transfer_path, "trajectory transfer manifest")
    transfer_required = {"schema", "source_path", "captured_on", "remote_sha256", "remote_size_bytes",
                         "local_path", "local_sha256", "local_size_bytes", "archive_v2_sha256",
                         "transfer_method", "read_only_source"}
    if (set(transfer) != transfer_required or transfer.get("schema") != TRANSFER_SCHEMA
            or transfer.get("source_path") != EXPECTED_9806_WORKDIR + "/production.xtc"
            or transfer.get("remote_sha256") != EXPECTED_XTC_SHA256
            or transfer.get("local_sha256") != EXPECTED_XTC_SHA256
            or transfer.get("remote_size_bytes") != EXPECTED_XTC_BYTES
            or transfer.get("local_size_bytes") != EXPECTED_XTC_BYTES
            or transfer.get("local_path") != "production.xtc"
            or transfer.get("captured_on") != "2026-10-16"
            or transfer.get("transfer_method") != "rsync --partial"
            or transfer.get("archive_v2_sha256") != context["archive_v2_sha256"]
            or transfer.get("read_only_source") is not True):
        raise HistoricalArchiveError("trajectory transfer manifest does not bind the exact read-only 9806 XTC")

    collection = _read_json(collection_path, "collection manifest")
    expected_collection_sha = v2.get("archive", {}).get("collection_manifest_sha256")
    if sha256_file(collection_path) != expected_collection_sha:
        raise HistoricalArchiveError("collection manifest hash differs from the v2 historical record")
    collected_root = archive / "collected"
    listed = collection.get("files")
    if not isinstance(listed, list) or len(listed) != 72:
        raise HistoricalArchiveError("collection manifest does not enumerate the frozen 72-file archive")
    seen = set()
    for item in listed:
        if not isinstance(item, dict) or set(item) != {"path", "size_bytes", "sha256"}:
            raise HistoricalArchiveError("collection manifest contains a malformed file row")
        rel = item["path"]
        if rel in seen:
            raise HistoricalArchiveError("collection manifest repeats a file path")
        seen.add(rel)
        file_path = _relative_file(collected_root, rel, "collected archive member")
        if file_path.stat().st_size != item["size_bytes"] or sha256_file(file_path) != item["sha256"]:
            raise HistoricalArchiveError(f"collected archive member changed: {rel}")

    ancestry = _read_json(ancestry_path, "9136 equilibration manifest")
    if (ancestry.get("schema") != ANCESTRY_SCHEMA
            or ancestry.get("scope") != "Actual9044EM/NVT and9136NPT ancestry; not a new simulation"
            or ancestry.get("immutable_90_file_archive_modified") is not False):
        raise HistoricalArchiveError("9136 ancestor manifest is not the exact accepted protocol ancestry")
    ancestry_files = ancestry.get("files")
    if not isinstance(ancestry_files, dict) or len(ancestry_files) != 14:
        raise HistoricalArchiveError("9136 ancestor manifest does not declare the exact 14 protected roles")
    for role, item in ancestry_files.items():
        if not isinstance(item, dict) or set(item) != {"path", "relative_path", "sha256", "size_bytes"}:
            raise HistoricalArchiveError(f"malformed 9136 ancestor role: {role}")
        path = _relative_file(archive / "ancestry9136", item["relative_path"], f"9136 ancestor {role}")
        if path.stat().st_size != item["size_bytes"] or sha256_file(path) != item["sha256"]:
            raise HistoricalArchiveError(f"9136 ancestor artifact changed: {role}")
    prior = _read_json(prior_receipt_path, "9136 historical receipt")
    if (prior.get("schema") != "case01-trusted-execution-receipt-v1" or prior.get("job_id") != "9136"
            or prior.get("job_state") != "COMPLETED" or prior.get("exit_code") != "0:0"
            or prior.get("accounting_verified") is not True
            or prior.get("remote_workdir") != EXPECTED_9136_WORKDIR):
        raise HistoricalArchiveError("9136 receipt is not the frozen completed ancestor; it is not a 9806 controller proof")
    workflow_facts = _validate_9136_workflow_evidence(archive, prior)
    for role, expected_sha in (("starting-npt.gro", "d807b763d4df48281275e65e87be788106d2ab340ea2efcd0daf9bce699cc17f"),
                               ("topol.runtime.top", "1072dc72d08d1ea95e12d78a464fefffc962e86c115b43de17189f14ee8ab94e")):
        native = v2.get("native_files", {}).get(role)
        if not isinstance(native, dict) or native.get("sha256") != expected_sha:
            raise HistoricalArchiveError(f"9806 archived ancestry input {role} does not match the registered 9136 source")
    return {"context": context, "archive_root": archive, "xtc": xtc_path,
            "historical_job_id": "9806", "fresh_execution_status": "NOT_APPLICABLE_HISTORICAL_REFERENCE",
            "ancestry_workflow_evidence": workflow_facts}


def load_author_context(env: dict[str, str] | None = None) -> dict:
    """Load only the exact evaluator-mounted context; callers must opt in explicitly."""
    import os

    values = dict(os.environ if env is None else env)
    supplied = values.get("CASE01_AUTHOR_ARCHIVE_CONTEXT")
    if supplied != str(CONTEXT_PATH):
        raise HistoricalArchiveError("author historical route requires the exact evaluator-mounted context path")
    context_path = _regular_file(CONTEXT_PATH, "evaluator historical context")
    if context_path.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise HistoricalArchiveError("evaluator historical context must be non-group/world-writable")
    context = _read_json(context_path, "evaluator historical context")
    package_pin = values.get("CASE01_CANONICAL_PACKAGE_SOURCE_SHA256")
    if not package_pin or package_pin != context.get("canonical_package_source_sha256"):
        raise HistoricalArchiveError("evaluator package source pin is missing or differs from author context")
    if values.get("CASE01_IMAGE_ID") != context.get("image_id"):
        raise HistoricalArchiveError("resolved evaluator image ID is missing or differs from author context")
    return validate_context_document(context, ARCHIVE_PATH)
