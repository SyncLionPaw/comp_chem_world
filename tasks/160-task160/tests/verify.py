#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Evaluate ACE active-learning label efficiency across diverse Si–O environments.
"""Runner report/reward protocol for the isolated case-07 evidence verifier."""
from __future__ import annotations

import hashlib
import argparse
import math
import signal
import shutil
import time
import base64
import gzip
import importlib.util
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import traceback
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


EXIT_BY_STATUS = {"PASS": 0, "FAIL": 1, "ERROR": 2}
SCHEMA = "case07-v2-l3-rubric/v1"
REFS_SHA256 = "4e6642ab99cd5ab0049da325a451c1013e8439d9776da90f979ebb0d9e470372"
DOMAINS = ("amorphous", "amorphous_silicon", "crystalline", "high_pressure", "mixed", "surfaces")
METRIC_KEYS = {"energy": "_energy_sq_eV2_atom2", "force_component": "_force_component_sq_eV2_A2"}


class CandidateFailure(Exception):
    """Candidate evidence contradicts the fixed task protocol."""


class EnvironmentFailure(Exception):
    """Trusted grader assets or runtime are missing or invalid."""


def persist(result: dict, log_dir: Path, verifier_code: int | None = None) -> int:
    status = result.get("overall")
    if status not in EXIT_BY_STATUS:
        status = "ERROR"
        result = {"case_id": "case-07", "overall": status, "reward": None,
                  "error": "verifier returned an invalid status"}
    expected_reward = {"PASS": 1.0, "FAIL": 0.0, "ERROR": None}[status]
    expected_code = EXIT_BY_STATUS[status]
    got_reward = result.get("reward")
    reward_matches = (got_reward is None if expected_reward is None else
                      type(got_reward) in (int, float) and got_reward == expected_reward)
    if not reward_matches or (verifier_code is not None and verifier_code != expected_code):
        status, expected_reward, expected_code = "ERROR", None, 2
        result = {"case_id": "case-07", "overall": status, "reward": None,
                  "error": "verifier status/reward/exit-code mismatch"}
    result.update(overall=status, status=status, reward=expected_reward,
                  entrypoint="case-07/tests/verify.py",
                  recorded_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    log_dir.mkdir(parents=True, exist_ok=True)
    reward_file = log_dir / "reward.txt"
    reward_file.unlink(missing_ok=True)
    report = log_dir / "verification.json"
    report.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    if status in ("PASS", "FAIL"):
        reward_file.write_text(f"{expected_reward:.1f}\n", encoding="ascii")
    return expected_code


def validate_public_source_data(refs: dict, tests: Path) -> None:
    """Verify the losslessly embedded author source members and their provenance."""
    source = refs.get("public_source_data")
    if (not isinstance(source, dict)
            or source.get("schema") != "bench24-public-scientific-source-data/v1"
            or source.get("source_doi") != "10.5281/zenodo.10419194"
            or source.get("license") != "CC-BY-4.0"
            or source.get("archive_md5_recomputed") is not False
            or not isinstance(source.get("members"), dict)
            or len(source["members"]) != 16):
        raise EnvironmentFailure("tests/refs.json public source registry is missing or malformed")
    if hashlib.sha256((tests / "refs.json").read_bytes()).hexdigest() != REFS_SHA256:
        raise EnvironmentFailure("tests/refs.json differs from its verifier pin")
    for name, row in source["members"].items():
        member = row.get("source_member")
        if (not isinstance(member, str) or not member.startswith("results/testsets/")
                or member.rsplit("/", 1)[-1] != name or row.get("encoding") != "gzip+base64"):
            raise EnvironmentFailure("invalid public source member identity")
        try:
            raw = gzip.decompress(base64.b64decode(row["data_base64"], validate=True))
        except (KeyError, ValueError, OSError, EOFError) as exc:
            raise EnvironmentFailure(f"embedded public source member is corrupt: {name}") from exc
        if (len(raw) != row.get("uncompressed_size")
                or hashlib.sha256(raw).hexdigest() != row.get("source_sha256")
                or f"{zlib.crc32(raw) & 0xffffffff:08x}" != row.get("zip_crc32")):
            raise EnvironmentFailure(f"embedded public source member failed integrity checks: {name}")


def validate_private_training_source(refs: dict, tests: Path, app: Path) -> None:
    """Verify mapped author training frames against protected public geometries."""
    source = refs.get("private_training_source")
    if (not isinstance(source, dict)
            or source.get("schema") != "case07-private-training-label-source/v1"
            or source.get("source_doi") != "10.5281/zenodo.10419194"
            or source.get("license") != "CC-BY-4.0"
            or source.get("source_member") != "database/training.general_purpose.SiOx.xyz"
            or source.get("source_dataset_size") != 204673853
            or source.get("source_dataset_sha256") != "beb2616dd95b7e33899f488ec9680a46474f9c85630340ca343dfbb60c4f9548"
            or source.get("source_member_zip_crc32") != "cec5b016"
            or source.get("source_frame_count") != 11428
            or source.get("archive_md5_recomputed") is not False
            or source.get("entry_count") != 132
            or not isinstance(source.get("entries"), dict)
            or len(source["entries"]) != 132):
        raise EnvironmentFailure("private training-source registry is missing or malformed")
    if hashlib.sha256((tests / "refs.json").read_bytes()).hexdigest() != REFS_SHA256:
        raise EnvironmentFailure("tests/refs.json differs from its verifier pin")
    manifest_path = app / "inputs/v2/geometry-manifest.json"
    if not manifest_path.is_file():
        manifest_path = app / "environment/assets/v2/geometry-manifest.json"
    if (not manifest_path.is_file()
            or hashlib.sha256(manifest_path.read_bytes()).hexdigest() != source.get("geometry_manifest_sha256")):
        raise EnvironmentFailure("private training-source registry is not bound to the protected geometry manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("schema") != "case07-v2-public-geometry-manifest/v1"
            or manifest.get("source_dataset_sha256") != source["source_dataset_sha256"]
            or len(manifest.get("entries", [])) != 132):
        raise EnvironmentFailure("private training-source registry source differs from the protected geometry manifest")
    by_id = {row["id"]: row for row in manifest["entries"]}
    if len(by_id) != 132 or set(source["entries"]) != set(by_id):
        raise EnvironmentFailure("private training-source IDs differ from the protected geometry manifest")
    try:
        import numpy as np
        from ase.io import read
        from io import StringIO
    except ImportError as exc:
        raise EnvironmentFailure(f"ASE/NumPy unavailable for private source integrity checks: {exc}") from exc

    frame_indices = set()
    phase_counts = {"seed": 0, "pool": 0}
    for ident, row in source["entries"].items():
        public = by_id[ident]
        if (row.get("domain") != public.get("domain") or row.get("phase") != public.get("phase")
                or row.get("geometry_sha256") is None
                or type(row.get("source_frame_index")) is not int or row["source_frame_index"] < 0
                or row["source_frame_index"] >= source["source_frame_count"]
                or row["source_frame_index"] in frame_indices
                or row.get("label_fields") != ["dft_energy", "dft_forces"]
                or row.get("encoding") != "gzip+base64"):
            raise EnvironmentFailure(f"invalid private source mapping metadata for {ident}")
        frame_indices.add(row["source_frame_index"]); phase_counts[row["phase"]] += 1
        try:
            frame = gzip.decompress(base64.b64decode(row["data_base64"], validate=True))
            atoms = read(StringIO(frame.decode("utf-8")), format="extxyz")
        except Exception as exc:
            raise EnvironmentFailure(f"private source frame cannot be decoded: {ident}") from exc
        geometry_sha = row.get("geometry_sha256")
        if (hashlib.sha256(frame).hexdigest() != row.get("frame_sha256")
                or not isinstance(geometry_sha, str) or len(geometry_sha) != 64
                or any(c not in "0123456789abcdef" for c in geometry_sha)
                or len(atoms) != row.get("n_atoms")
                or "dft_energy" not in atoms.info or "dft_forces" not in atoms.arrays):
            raise EnvironmentFailure(f"private source frame failed geometry/label identity checks: {ident}")
        forces = np.asarray(atoms.arrays["dft_forces"], float)
        if (forces.shape != (len(atoms), 3) or not np.isfinite(forces).all()
                or not np.isfinite(float(atoms.info["dft_energy"]))):
            raise EnvironmentFailure(f"private source labels are malformed: {ident}")
    if phase_counts != {"seed": 12, "pool": 120}:
        raise EnvironmentFailure("private source mapping has incorrect seed/pool counts")


import base64
import gzip
import hmac
import shutil
import time
import zlib




def _canonical_json(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()



















# Original pinned ACE backend definitions used by the root-controlled local worker.
class BackendError(RuntimeError):
    pass

ELEMENTS = ("Si", "O")


class BackendError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def deps():
    missing = []
    try:
        import numpy as np  # noqa: F401
    except ImportError:
        missing.append("numpy")
    try:
        import pandas as pd  # noqa: F401
    except ImportError:
        missing.append("pandas")
    try:
        import ase  # noqa: F401
        import ase.io  # noqa: F401
    except ImportError:
        missing.append("ase")
    try:
        import pyace  # noqa: F401
    except ImportError:
        missing.append("pyace (ICAMS/python-ace/PACEMAKER)")
    if missing:
        raise BackendError("ERROR: required native dependencies unavailable: " + ", ".join(missing))


def read_frames(path: Path):
    from ase.io import read
    try:
        frames = read(str(path), index=":", format="extxyz")
    except Exception as e:
        raise BackendError(f"ERROR: cannot read extxyz {path}: {e}") from e
    if not frames:
        raise BackendError(f"ERROR: no structures in {path}")
    return frames


def finite_labels(atoms, index):
    import numpy as np
    energy = atoms.info.get("dft_energy")
    forces = atoms.arrays.get("dft_forces")
    if energy is None or forces is None:
        raise BackendError(f"ERROR: frame {index} must contain oracle dft_energy and dft_forces")
    energy = float(energy)
    forces = np.asarray(forces, dtype=float)
    if not math.isfinite(energy) or forces.shape != (len(atoms), 3) or not np.isfinite(forces).all():
        raise BackendError(f"ERROR: invalid energy/force labels in frame {index}")
    symbols = atoms.get_chemical_symbols()
    if not symbols or not set(symbols).issubset(ELEMENTS):
        raise BackendError(f"ERROR: frame {index} contains elements outside Si/O")
    return energy, forces, symbols


def derive_e0(frames):
    """Least-squares elemental energy reference derived only from revealed labels."""
    import numpy as np
    counts, energies = [], []
    for i, atoms in enumerate(frames):
        energy, _, symbols = finite_labels(atoms, i)
        counts.append([symbols.count(el) for el in ELEMENTS])
        energies.append(energy)
    coeff, _, rank, _ = np.linalg.lstsq(np.asarray(counts, float), np.asarray(energies, float), rcond=None)
    if rank < len(ELEMENTS):
        raise BackendError("ERROR: revealed training set does not identify both Si and O energy references")
    return {el: float(coeff[i]) for i, el in enumerate(ELEMENTS)}


def make_dataset(frames, e0, out: Path):
    import numpy as np
    import pandas as pd
    records = []
    for i, atoms in enumerate(frames):
        energy, forces, symbols = finite_labels(atoms, i)
        corrected = energy - sum(e0[el] * symbols.count(el) for el in ELEMENTS)
        atoms = atoms.copy()
        atoms.arrays["forces"] = forces.copy()
        records.append({"energy": energy, "forces": forces, "ase_atoms": atoms,
                        "energy_corrected": float(corrected)})
    pd.DataFrame.from_records(records).to_pickle(out, compression="gzip", protocol=4)


def run_bounded(command, cwd, log, env, deadline, label):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise BackendError(f"ERROR: total fit timeout exhausted before {label}")
    proc = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                            env=env, text=True, start_new_session=True)
    try:
        return proc.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        except ProcessLookupError:
            pass
        raise BackendError(f"ERROR: {label} exceeded the total fit timeout")


def train(args):
    deps()
    data_path, reference_path, out = (Path(args.dataset).resolve(), Path(args.reference_dataset).resolve(),
                                     Path(args.out_dir).resolve())
    if not data_path.is_file():
        raise BackendError(f"ERROR: training dataset not found: {data_path}")
    if not reference_path.is_file():
        raise BackendError(f"ERROR: seed-only reference dataset not found: {reference_path}")
    template_path = Path(args.template).resolve(strict=True)
    pacemaker = os.environ.get("CASE07_PACEMAKER") or shutil.which("pacemaker")
    converter = os.environ.get("CASE07_PACE_YAML2YACE") or shutil.which("pace_yaml2yace")
    if not pacemaker or not converter:
        raise BackendError("ERROR: native executables pacemaker and pace_yaml2yace are required")
    if not Path(pacemaker).is_absolute() or not Path(converter).is_absolute():
        raise BackendError("ERROR: trusted fit requires absolute pinned PACEMAKER/converter paths")
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise BackendError(f"ERROR: output directory must be new or empty; refusing to reuse {out}")
    frames = read_frames(data_path)
    reference_frames = read_frames(reference_path)
    e0 = derive_e0(reference_frames)
    dataset = out / "revealed-training.pckl.gzip"
    make_dataset(frames, e0, dataset)
    yaml_in = out / "input.yaml"
    yaml_text = template_path.read_text().replace("__DATASET__", str(dataset)).replace("__SEED__", str(args.seed)).replace("__MAXITER__", str(args.maxiter))
    yaml_in.write_text(yaml_text)
    log_path = out / "train.log"
    start = time.monotonic()
    status = "ERROR"
    try:
        env = os.environ.copy()
        for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "BLIS_NUM_THREADS"):
            env[name] = "1"
        deadline = start + args.timeout_seconds
        with log_path.open("w") as log:
            rc = run_bounded([pacemaker, str(yaml_in)], out, log, env, deadline, "PACEMAKER")
        if rc != 0:
            raise BackendError(f"ERROR: PACEMAKER exited with status {rc}; see {log_path}")
        native = out / "output_potential.yaml"
        if not native.is_file() or native.stat().st_size == 0:
            raise BackendError("ERROR: PACEMAKER did not produce output_potential.yaml")
        with log_path.open("a") as log:
            rc = run_bounded([converter, str(native)], out, log, env, deadline, "pace_yaml2yace")
        if rc != 0:
            raise BackendError(f"ERROR: pace_yaml2yace exited with status {rc}; see {log_path}")
        yace = out / "output_potential.yace"
        if not yace.is_file() or yace.stat().st_size == 0:
            raise BackendError("ERROR: converter did not produce output_potential.yace")
        shutil.copy2(native, out / "potential.yaml")
        shutil.copy2(yace, out / "potential.yace")
        status = "TRAINED"
    finally:
        elapsed = time.monotonic() - start
        timing = {"status": status, "wall_seconds": elapsed, "timeout_seconds": args.timeout_seconds,
                  "maxiter": args.maxiter, "seed": args.seed}
        (out / "timing.json").write_text(json.dumps(timing, indent=2) + "\n")
    manifest = {"schema": "case07-pyace-model/v1", "status": status, "backend": "ICAMS/python-ace PACEMAKER + PyACE",
                "training_file": str(data_path), "training_sha256": sha256(data_path), "frame_count": len(frames),
                "reference_file": str(reference_path), "reference_sha256": sha256(reference_path),
                "seed": args.seed, "maxiter": args.maxiter, "timeout_seconds": args.timeout_seconds,
                "fit_config": {"optimizer": "L-BFGS-B", "maxiter": args.maxiter, "kappa": 0.01,
                               "repulsion": "auto", "parallel_mode": "serial", "initialization": "fresh basis; no reference potential",
                               "coefficient_initialization": "random (per UNARY/BINARY coefs_init)",
                               "random_seed": args.seed,
                               "initialization_evidence": "pinned ICAMS/python-ace commit 66c35ea6d5ebed2857d423952b922183206c140e: pacemaker passes top-level seed to GeneralACEFit, which calls numpy.random.seed; multispecies_basisextension.generate_functions_ext propagates UNARY/BINARY block keys and create_species_block maps coefs_init=random to numpy.random.randn(ndensity)*1e-4"},
                "elemental_energy_reference_eV_per_atom": e0, "reference_source": "revealed training labels only; Si/O least-squares composition fit",
                "template_sha256": sha256(template_path), "native_yaml": "potential.yaml", "yace": "potential.yace",
                "native_yaml_sha256": sha256(out / "potential.yaml"), "yace_sha256": sha256(out / "potential.yace"),
                "timing": timing}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


def predict(args):
    deps()
    import numpy as np
    from pyace.asecalc import PyACECalculator
    model, structures, target = Path(args.model).resolve(), Path(args.structures).resolve(), Path(args.output).resolve()
    if not model.is_file() or not structures.is_file():
        raise BackendError("ERROR: model and structures must exist")
    manifest_path = model.parent / "manifest.json"
    if not manifest_path.is_file():
        raise BackendError("ERROR: adjacent model manifest.json is required to restore the training-derived energy gauge")
    try:
        manifest = json.loads(manifest_path.read_text())
        e0 = manifest["elemental_energy_reference_eV_per_atom"]
        model_sha = sha256(model)
    except Exception as e:
        raise BackendError(f"ERROR: invalid model manifest: {e}") from e
    if manifest.get("schema") != "case07-pyace-model/v1" or manifest.get("status") != "TRAINED":
        raise BackendError("ERROR: model manifest is not a successful Case 07 PyACE training receipt")
    expected_name = model.name
    if expected_name not in ("potential.yaml", "potential.yace"):
        raise BackendError("ERROR: model must be the manifested potential.yaml or potential.yace")
    if expected_name == "potential.yaml":
        expected_sha = manifest.get("native_yaml_sha256")
    else:
        expected_sha = manifest.get("yace_sha256")
    if not isinstance(expected_sha, str) or model_sha != expected_sha:
        raise BackendError("ERROR: model SHA-256 does not match the adjacent manifest")
    if not isinstance(e0, dict) or set(e0) != set(ELEMENTS):
        raise BackendError("ERROR: manifest E0 gauge must define exactly Si and O")
    try:
        if not all(math.isfinite(float(e0[el])) for el in ELEMENTS):
            raise ValueError("non-finite element energy")
    except Exception as e:
        raise BackendError(f"ERROR: invalid manifest E0 gauge: {e}") from e
    frames = read_frames(structures)
    calc = PyACECalculator(str(model))
    preds = []
    for i, atoms in enumerate(frames):
        geometry = atoms.copy()
        geometry.calc = calc
        energy = float(geometry.get_potential_energy()) + sum(float(e0[el]) * atoms.get_chemical_symbols().count(el) for el in ELEMENTS)
        forces = np.asarray(geometry.get_forces(), dtype=float)
        if not math.isfinite(energy) or forces.shape != (len(atoms), 3) or not np.isfinite(forces).all():
            raise BackendError(f"ERROR: non-finite or malformed native PyACE prediction at frame {i}")
        preds.append({"index": i, "geometry_sha256": geometry_digest(atoms), "atom_count": len(atoms),
                      "energy_eV": energy, "forces_eV_per_angstrom": forces.tolist()})
    result = {"schema": "case07-pyace-predictions/v1", "status": "PREDICTED", "backend": "PyACECalculator",
              "model_path": str(model), "model_sha256": model_sha, "energy_gauge": "training-derived Si/O E0 restored to total energy",
              "structures_path": str(structures),
              "structures_sha256": sha256(structures), "frame_count": len(preds), "predictions": preds}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "frame_count": len(preds), "output": str(target)}))


def geometry_digest(atoms):
    """Stable identity over ordered species, cell, PBC and Cartesian coordinates."""
    import numpy as np
    payload = {"symbols": atoms.get_chemical_symbols(), "positions": np.asarray(atoms.positions, float).round(10).tolist(),
               "cell": np.asarray(atoms.cell, float).round(10).tolist(), "pbc": np.asarray(atoms.pbc, bool).tolist()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _ace_worker_main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("train")
    t.add_argument("--dataset", required=True, help="revealed labeled extxyz")
    t.add_argument("--reference-dataset", required=True, help="fixed seed-only labeled extxyz used to derive Si/O E0")
    t.add_argument("--template", required=True, help="verifier-generated fixed YAML template")
    t.add_argument("--out-dir", required=True)
    t.add_argument("--seed", type=int, required=True)
    t.add_argument("--maxiter", type=int, default=32)
    t.add_argument("--timeout-seconds", type=int, default=3600)
    t.set_defaults(func=train)
    p = sub.add_parser("predict")
    p.add_argument("--model", required=True, help="native PyACE potential YAML or YACE")
    p.add_argument("--structures", required=True, help="ordered input geometries in extxyz")
    p.add_argument("--output", required=True)
    p.set_defaults(func=predict)
    args = parser.parse_args()
    if args.command == "train" and (args.maxiter < 1 or args.maxiter > 64 or args.timeout_seconds < 1):
        parser.error("maxiter must be in 1..64 and timeout-seconds must be positive")
    try:
        args.func(args)
    except BackendError as e:
        print(str(e), file=sys.stderr)
        return 2
    except subprocess.TimeoutExpired as e:
        print(f"ERROR: native PyACE command timed out: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"ERROR: native PyACE backend failed: {e}", file=sys.stderr)
        return 2
    return 0




# Original scientific-verification functions copied verbatim from verify_v3.
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def canon(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()

def required_env(name):
 x=os.environ.get(name)
 if not x:raise EnvironmentFailure(f'runner-pinned {name} missing')
 return x

def read_json(path,env=False):
 try:return json.loads(Path(path).read_text())
 except (OSError,json.JSONDecodeError) as e:raise (EnvironmentFailure if env else CandidateFailure)(f'cannot read JSON {path}: {e}')

def path_under(path,root,label):
 p=Path(path).resolve(strict=True);r=Path(root).resolve(strict=True)
 if not p.is_relative_to(r):raise CandidateFailure(f'{label} escapes its root')
 return p

def read_atoms(path,environment=False):
 try:from ase.io import read
 except ImportError as e:raise EnvironmentFailure(f'ASE unavailable in isolated grader: {e}')
 try:return read(str(path),index=':',format='extxyz')
 except Exception as e:raise (EnvironmentFailure if environment else CandidateFailure)(f'cannot parse extxyz {path}: {e}')

def public_inputs(app):
 base=Path(app).resolve();root=base/'inputs/v2'
 if not root.is_dir():root=base/'environment/assets/v2'
 mp=root/'geometry-manifest.json'
 if not mp.is_file():raise EnvironmentFailure('case07-v2 public manifest missing')
 manifest=read_json(mp,True)
 if manifest.get('schema')!='case07-v2-public-geometry-manifest/v1' or manifest.get('geometry_count')!=132:raise EnvironmentFailure('unsupported/malformed public geometry manifest')
 entries=manifest['entries'];byid={e['id']:e for e in entries}
 if len(byid)!=132 or len(entries)!=132:raise EnvironmentFailure('public geometry IDs are not unique')
 counts={d:{p:0 for p in ('seed','pool')} for d in manifest['domain_config_types']}
 hashes=set()
 for e in entries:
  if e.get('domain') not in counts or e.get('phase') not in ('seed','pool'):raise EnvironmentFailure('invalid manifest domain/phase')
  counts[e['domain']][e['phase']]+=1;p=(root/e['path']).resolve(strict=True)
  if not p.is_relative_to(root.resolve()) or sha(p)!=e['geometry_sha256']:raise EnvironmentFailure(f'public geometry hash/path mismatch: {e["id"]}')
  if e['geometry_sha256'] in hashes:raise EnvironmentFailure('duplicate public geometry byte hash')
  hashes.add(e['geometry_sha256']);raw=p.read_text()
  for bad in ('dft_energy','dft_forces','charge_bader','charge_ddec3','charge_ddec6','dft_stress','dft_virials','dft_free_energy'):
   if bad in raw:raise EnvironmentFailure(f'label field leaked to public geometry: {e["id"]}')
 for d,c in counts.items():
  if c!={'seed':2,'pool':20}:raise EnvironmentFailure(f'{d} has wrong seed/pool quota: {c}')
 expected={e['path'] for e in entries}
 actual={str(p.relative_to(root)) for sub in ('seed_structures','candidate_pool') for p in (root/sub).glob('*.extxyz')}
 if actual!=expected:raise EnvironmentFailure('public geometry directory contains missing or extra files outside manifest whitelist')
 return root,mp,manifest,byid

def verify_candidate_labels(out,root,byid,ledger,backend):
 phase_files=[('seed','labels/seed.extxyz'),('round-1','labels/round-1.extxyz'),('round-2','labels/round-2.extxyz')]
 rows_by_phase={r['phase']:r for r in ledger};phase_ids={}
 for phase,rel in phase_files:
  p=out/rel;r=rows_by_phase[phase]
  if not p.is_file() or sha(p)!=r['released_labels_sha256']:raise CandidateFailure(f'{phase} labels differ from authenticated oracle release')
  frames=read_atoms(p)
  if len(frames)!=r['count']:raise CandidateFailure(f'{phase} label frame count mismatch')
  ids=[]
  for a in frames:
   ident=a.info.get('queried_id')
   if ident not in byid or ident in ids:raise CandidateFailure(f'{phase} label ID is invalid/duplicate')
   pub=byid[ident];ids.append(ident)
   if pub['phase']!=('seed' if phase=='seed' else 'pool'):raise CandidateFailure(f'{phase} label was queried from wrong pool')
   if 'dft_energy' not in a.info or 'dft_forces' not in a.arrays:raise CandidateFailure(f'{phase} label missing E/F')
   gp=root/pub['path'];public=read_atoms(gp)[0]
   if backend.geometry_digest(a)!=backend.geometry_digest(public):raise CandidateFailure(f'oracle label geometry/order differs from published ID {ident}')
   forces=np.asarray(a.arrays['dft_forces'],float);e=float(a.info['dft_energy'])
   if forces.shape!=(len(a),3) or not math.isfinite(e) or not np.isfinite(forces).all():raise CandidateFailure(f'malformed label values {ident}')
  if ids!=r['ids']:raise CandidateFailure(f'{phase} released ID order differs from receipt')
  phase_ids[phase]=ids
 return phase_ids

def verify_training_and_committees(out,phase_ids,backend):
 all_ids=[];trains={};committees={};modelrefs={}
 released={}
 for phase in ('seed','round-1','round-2'):
  for atoms in read_atoms(out/f'labels/{phase}.extxyz'):
   ident=atoms.info.get('queried_id')
   if not ident or ident in released:raise CandidateFailure('oracle releases contain missing/duplicate IDs')
   released[ident]=atoms
 seed_frames=[released[x] for x in phase_ids['seed']]
 counts=np.asarray([[a.get_chemical_symbols().count('Si'),a.get_chemical_symbols().count('O')] for a in seed_frames],float)
 energies=np.asarray([float(a.info['dft_energy']) for a in seed_frames],float)
 e0,_,rank,_=np.linalg.lstsq(counts,energies,rcond=None)
 if rank<2:raise CandidateFailure('seed-only labels do not identify both Si/O energy gauges')
 for stage in range(3):
  if stage==0:all_ids=list(phase_ids['seed'])
  else:all_ids+=phase_ids[f'round-{stage}']
  tr=out/f'training/round-{stage}.extxyz';idsfile=out/f'training/round-{stage}.ids';cp=out/f'models/round-{stage}/committee.json'
  if not tr.is_file() or not idsfile.is_file() or not cp.is_file():raise CandidateFailure(f'round {stage} training/committee artifacts missing')
  declared=idsfile.read_text().splitlines();frames=read_atoms(tr);actual=[a.info.get('queried_id') for a in frames]
  if declared!=all_ids or actual!=all_ids:raise CandidateFailure(f'round {stage} train frames/IDs do not equal exactly revealed labels')
  for frame in frames:
   ident=frame.info.get('queried_id');label=released.get(ident)
   if label is None:raise CandidateFailure(f'training contains unreleased label {ident}')
   if backend.geometry_digest(frame)!=backend.geometry_digest(label):raise CandidateFailure(f'training geometry/order differs from released label {ident}')
   if 'dft_energy' not in frame.info or 'dft_forces' not in frame.arrays:raise CandidateFailure(f'training labels missing for {ident}')
   if not math.isclose(float(frame.info['dft_energy']),float(label.info['dft_energy']),rel_tol=0,abs_tol=1e-12):raise CandidateFailure(f'training energy differs from oracle release {ident}')
   if np.asarray(frame.arrays['dft_forces']).shape!=np.asarray(label.arrays['dft_forces']).shape or not np.allclose(frame.arrays['dft_forces'],label.arrays['dft_forces'],rtol=0,atol=1e-12):raise CandidateFailure(f'training ordered forces differ from oracle release {ident}')
  doc=read_json(cp);training_sha=sha(tr)
  if doc.get('schema')!='case07-v2-committee/v1' or doc.get('round')!=stage or doc.get('training_sha256')!=training_sha or len(doc.get('members',[]))!=3:raise CandidateFailure(f'round {stage} committee metadata inconsistent')
  members=[];hashes=[]
  for m in doc['members']:
   model=path_under(out/f'models/round-{stage}'/m['model_yace'],out,'checkpoint')
   if model.suffix!='.yace' or sha(model)!=m.get('model_sha256'):raise CandidateFailure('YACE checkpoint path/hash invalid')
   manifest_path=model.parent/'manifest.json';native=read_json(manifest_path)
   if native.get('training_sha256')!=training_sha or native.get('seed')!=m.get('seed') or native.get('yace_sha256')!=sha(model):raise CandidateFailure('native ACE manifest does not bind model to current training bytes')
   gauges=native.get('elemental_energy_reference_eV_per_atom',{})
   if any(el not in gauges or not math.isclose(float(gauges[el]),float(e0[i]),rel_tol=0,abs_tol=1e-10) for i,el in enumerate(('Si','O'))):raise CandidateFailure('ACE model did not use the immutable oracle-seed-only E0 gauge')
   if m.get('training_sha256')!=training_sha or len(str(m.get('backend_manifest_sha256',''))) !=64 or sha(manifest_path)!=m['backend_manifest_sha256']:raise CandidateFailure('candidate committee lacks verified backend manifest hash')
   members.append((m,model,native));hashes.append(sha(model))
  if len(set(hashes))!=3 or len({m['seed'] for m,_,_ in members})!=3:raise CandidateFailure('committee members are not independent distinct seeds/models')
  committees[stage]=members;trains[stage]=(tr,frames,training_sha)
 return committees,trains

def replay_selections(out,root,manifest,byid,committees,phase_ids,backend_path,backend,work,tests_dir=None):
 pool=(work/'pool.extxyz');parts=[]
 for e in manifest['entries']:
  if e['phase']=='pool':parts.append((root/e['path']).read_bytes())
 pool.write_bytes(b''.join(parts));frames=read_atoms(pool);frameby={a.info['id']:a for a in frames};entries={e['id']:e for e in manifest['entries']}
 queried=set(phase_ids['seed'])
 for rnd in (1,2):
  models=[]
  for member,model,_native in committees[rnd-1]:models.append((member['model_sha256'],model))
  preds=trusted_predictions(backend_path,backend,models,pool,work,
                            Path(tests_dir or os.environ.get('TESTS', Path(__file__).parent)))
  rows=[]
  for i,(ident,a) in enumerate(frameby.items()):
   forces=[np.asarray(p['predictions'][i]['forces_eV_per_angstrom'],float) for p in preds]
   gd=[p['predictions'][i]['geometry_sha256'] for p in preds]
   if len(set(gd))!=1 or gd[0]!=backend.geometry_digest(a) or any(f.shape!=(len(a),3) or not np.isfinite(f).all() for f in forces):raise CandidateFailure('trusted force replay geometry/order mismatch')
   score=float(np.sqrt(np.mean(np.var(np.stack(forces),axis=0,ddof=1))))
   rows.append({'id':ident,'domain':a.info['domain'],'geometry_sha256':entries[ident]['geometry_sha256'],'force_disagreement_eV_per_A':score,'eligible_for_selection':ident not in queried})
  rows.sort(key=lambda x:(x['domain'],-x['force_disagreement_eV_per_A'],x['id']))
  selected=[]
  for domain in sorted({x['domain'] for x in rows}):
   candidates=[x for x in rows if x['domain']==domain and x['eligible_for_selection']]
   if not candidates:raise CandidateFailure(f'no unqueried structures remain in {domain}')
   selected.append(candidates[0])
  p=out/f'selections/round-{rnd}.json';req=p.with_suffix('.request.json')
  if not p.is_file() or not req.is_file():raise CandidateFailure(f'round {rnd} selection artifacts missing')
  candidate=read_json(p);request=read_json(req)
  expected_models=[entry['model_sha256'] for entry,_,_ in committees[rnd-1]]
  if (candidate.get('round')!=rnd or candidate.get('pool_sha256')!=sha(pool)
      or candidate.get('committee_sha256')!=sha(out/f'models/round-{rnd-1}/committee.json')
      or candidate.get('model_sha256')!=expected_models
      or request.get('phase')!=f'round-{rnd}' or request.get('ids')!=[x['id'] for x in selected]):
   raise CandidateFailure(f'round {rnd} request differs from trusted ranking or committee binding')
  got=candidate.get('ranked',[])
  if len(got)!=len(rows):raise CandidateFailure(f'round {rnd} rank omits pool entries')
  for a,b in zip(got,rows):
   if a.get('id')!=b['id'] or a.get('geometry_sha256')!=b['geometry_sha256'] or bool(a.get('eligible_for_selection'))!=b['eligible_for_selection'] or not math.isclose(float(a.get('force_disagreement_eV_per_A',float('nan'))),b['force_disagreement_eV_per_A'],rel_tol=1e-8,abs_tol=1e-12):raise CandidateFailure(f'round {rnd} ranking differs from trusted replay')
  att_path=Path(required_env('CASE07_ORACLE_STATE_DIR'))/f'attestation-round-{rnd}.json'
  att=read_json(att_path,True)
  receipt=json.loads(Path(required_env('CASE07_ORACLE_LEDGER')).read_text().splitlines()[rnd])
  if sha(att_path)!=receipt.get('attestation_sha256'):raise EnvironmentFailure(f'round {rnd} receipt does not pin the trusted attestation bytes')
  if att.get('selected_ids')!=[x['id'] for x in selected] or att.get('prior_query_receipt_sha256')!=json.loads(Path(required_env('CASE07_ORACLE_LEDGER')).read_text().splitlines()[rnd-1])['receipt_sha256']:
   raise EnvironmentFailure(f'round {rnd} trusted attestation chronology mismatch')
  if not any(x['force_disagreement_eV_per_A']>1e-12 for x in rows if x['eligible_for_selection']):
   raise CandidateFailure(f'round {rnd} ACE committee collapsed to zero force disagreement over the eligible pool')
  queried.update(x['id'] for x in selected)
 return True

# Original preregistered L3 evaluator copied verbatim from hidden_eval_v2.
class RubricError(ValueError):
    """Malformed, unpinned, or temporally invalid author rubric."""

def _utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RubricError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise RubricError(f"{label} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise RubricError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)

def _validated_errors(report: Mapping[str, Any]):
    """Validate paired per-frame errors and author source-file cluster IDs."""
    stage0, stage2 = report.get("round-0"), report.get("round-2")
    if not isinstance(stage0, Mapping) or not isinstance(stage2, Mapping):
        raise RubricError("trusted metric report must include round-0 and round-2")
    result = {"energy": {}, "force_component": {}}
    cluster_map = {}
    for domain in DOMAINS:
        if domain not in stage0 or domain not in stage2:
            raise RubricError(f"trusted metric report missing domain {domain}")
        for metric, key in METRIC_KEYS.items():
            arrays = []
            for stage in (stage0, stage2):
                block = stage[domain]
                try:
                    arr = np.asarray(block[key], dtype=float)
                    frames = int(block["frames"])
                    clusters = block["_source_file_groups"]
                except (KeyError, TypeError, ValueError) as exc:
                    raise RubricError(f"missing/malformed paired frame errors for {domain}/{metric}") from exc
                if arr.ndim != 1 or len(arr) != frames or frames < 1:
                    raise RubricError(f"{domain}/{metric} frame errors do not match declared frame count")
                if not np.isfinite(arr).all() or np.any(arr < 0):
                    raise RubricError(f"{domain}/{metric} errors must be finite nonnegative squared errors")
                if (not isinstance(clusters, list) or len(clusters) != frames or
                        any(not isinstance(x, str) or not x.strip() for x in clusters)):
                    raise RubricError(f"{domain}/{metric} needs one trusted source-file ID per frame")
                arrays.append((arr, clusters))
            if arrays[0][0].shape != arrays[1][0].shape:
                raise RubricError(f"paired frame order/count differs between baseline and target for {domain}/{metric}")
            if arrays[0][1] != arrays[1][1]:
                raise RubricError(f"trusted source-file/frame order differs between baseline and target for {domain}/{metric}")
            previous = cluster_map.get(domain)
            if previous is not None and previous != arrays[0][1]:
                raise RubricError(f"energy/force source-file frame groups differ for {domain}")
            cluster_map[domain] = arrays[0][1]
            result[metric][domain] = (arrays[0][0], arrays[1][0], arrays[0][1])
    total_clusters = 0
    counts = {}
    total_frames = 0
    for domain in DOMAINS:
        groups = cluster_map[domain]
        file_ids = set(groups)
        if any(groups.count(file_id) != 5 for file_id in file_ids):
            raise RubricError(f"each hidden source file must contribute exactly five frames ({domain})")
        total_clusters += len(file_ids)
        counts[domain] = len(file_ids)
        total_frames += len(groups)
    if total_frames != 80 or total_clusters != 16:
        raise RubricError("held-out evaluator must contain the pinned 16 source files x 5 frames")
    if counts["surfaces"] != 1 or any(counts[d] < 2 for d in DOMAINS if d != "surfaces"):
        raise RubricError("expected one surfaces source cluster and at least two clusters in every other domain")
    return result

def _metric_summaries(errors):
    summaries = {}
    for metric, groups in errors.items():
        base = np.concatenate([groups[d][0] for d in DOMAINS])
        target = np.concatenate([groups[d][1] for d in DOMAINS])
        b_rmse, t_rmse = math.sqrt(float(base.mean())), math.sqrt(float(target.mean()))
        if b_rmse <= 0:
            raise RubricError(f"stage-0 {metric} RMSE is zero; relative improvement is undefined")
        domain_rows = {}
        for domain in DOMAINS:
            b, t, _ = groups[domain]
            br, tr = math.sqrt(float(b.mean())), math.sqrt(float(t.mean()))
            if br <= 0:
                raise RubricError(f"stage-0 {domain}/{metric} RMSE is zero; regression is undefined")
            domain_rows[domain] = {
                "stage0_rmse": br,
                "stage2_rmse": tr,
                "relative_change": tr / br - 1.0,
            }
        summaries[metric] = {
            "stage0_rmse": b_rmse,
            "stage2_rmse": t_rmse,
            "relative_improvement": 1.0 - t_rmse / b_rmse,
            "domains": domain_rows,
        }
    return summaries

def _paired_stratified_bootstrap(errors, replicates: int, seed: int, confidence: float):
    """File-cluster percentile CI, stratified within domains and paired by file.

    Each resampled author source file contributes all five constituent frames.
    Thus repeated frames from one source trajectory are not treated as
    independent bootstrap units. Pooled metrics remain equally weighted by
    frame. The single surfaces source file is fixed in every replicate, so the
    pooled interval is conditional on that file and does not establish family
    or trajectory independence.
    """
    rng = np.random.default_rng(seed)
    alpha = 1.0 - confidence
    output = {}
    for metric, groups in errors.items():
        base_sums = np.zeros(replicates, dtype=float)
        target_sums = np.zeros(replicates, dtype=float)
        total = 0
        clusters_by_domain = {}
        for domain in DOMAINS:
            base, target, cluster_labels = groups[domain]
            cluster_ids = sorted(set(cluster_labels))
            clusters_by_domain[domain] = len(cluster_ids)
            indices = {cid: np.asarray([i for i, value in enumerate(cluster_labels) if value == cid], dtype=int)
                       for cid in cluster_ids}
            selected = rng.integers(0, len(cluster_ids), size=(replicates, len(cluster_ids)))
            for replicate in range(replicates):
                chosen_indices = np.concatenate([indices[cluster_ids[j]] for j in selected[replicate]])
                base_sums[replicate] += float(base[chosen_indices].sum())
                target_sums[replicate] += float(target[chosen_indices].sum())
            total += len(cluster_labels)
        b_rmse = np.sqrt(base_sums / total)
        t_rmse = np.sqrt(target_sums / total)
        improvement = 1.0 - t_rmse / b_rmse
        if not np.isfinite(improvement).all():
            raise RubricError(f"bootstrap generated non-finite {metric} improvements")
        lo, hi = np.quantile(improvement, [alpha / 2.0, 1.0 - alpha / 2.0])
        output[metric] = {
            "confidence_level": confidence,
            "replicates": replicates,
            "seed": seed,
            "method": "paired_stratified_author_source_file_cluster_percentile",
            "resampling_unit": "author extxyz source file; all five frames resampled together",
            "cluster_counts_by_domain": clusters_by_domain,
            "surfaces_cluster_policy": "single source cluster held fixed in every replicate",
            "scope_note": "pooled CI is conditional on the held-out source files; trajectory-family independence is not established",
            "relative_improvement_ci": [float(lo), float(hi)],
        }
    return output

def _validate_rubric(rubric: Mapping[str, Any], agent_output_started_at_utc: str | None):
    if rubric.get("schema") != SCHEMA:
        raise RubricError(f"unsupported rubric schema; expected {SCHEMA}")
    if rubric.get("pre_agent_preregistered") is not True:
        raise RubricError("rubric is not marked as pre-registered before agent output")
    registered = _utc(rubric.get("registered_at_utc"), "registered_at_utc")
    if agent_output_started_at_utc is None:
        raise RubricError("runner must provide agent_output_started_at_utc")
    agent_started = _utc(agent_output_started_at_utc, "agent_output_started_at_utc")
    if registered >= agent_started:
        raise RubricError("rubric registration time must precede agent output start")
    thresholds = rubric.get("thresholds")
    if not isinstance(thresholds, Mapping):
        raise RubricError("rubric thresholds object is missing")
    try:
        reps = int(thresholds["bootstrap_replicates"])
        seed = int(thresholds["bootstrap_seed"])
        confidence = float(thresholds["confidence_level"])
        min_improvement = thresholds["pooled_min_relative_improvement"]
        max_regression = thresholds["domain_max_relative_regression"]
        mins = {m: float(min_improvement[m]) for m in METRIC_KEYS}
        maxs = {m: float(max_regression[m]) for m in METRIC_KEYS}
    except (KeyError, TypeError, ValueError) as exc:
        raise RubricError("rubric thresholds are incomplete or malformed") from exc
    if not 100 <= reps <= 1_000_000 or not 0.5 < confidence < 1.0:
        raise RubricError("bootstrap count or confidence level is outside supported bounds")
    if any(not math.isfinite(x) or x < 0 or x >= 1 for x in (*mins.values(), *maxs.values())):
        raise RubricError("relative improvement/regression thresholds must be finite in [0,1)")
    calibration = rubric.get("calibration_status")
    if calibration not in ("PROVISIONAL", "CALIBRATED"):
        raise RubricError("calibration_status must be PROVISIONAL or CALIBRATED")
    return thresholds, reps, seed, confidence, mins, maxs, calibration, registered, agent_started

def evaluate_l3(metric_report: Mapping[str, Any], rubric: Mapping[str, Any],
                agent_output_started_at_utc: str | None, rubric_sha256: str | None = None) -> dict[str, Any]:
    """Apply a runner-pinned, pre-registered L3 rubric to trusted replay errors.

    Returns only aggregate metrics and the rubric decision; paired per-frame
    inputs are intentionally omitted. Missing/invalid rubric or metric
    provenance returns ERROR; PROVISIONAL calibration alone does not suppress
    the preregistered operational PASS/FAIL decision.
    """
    try:
        thresholds, reps, seed, confidence, minimums, max_regressions, calibration, registered, agent_started = _validate_rubric(
            rubric, agent_output_started_at_utc)
        errors = _validated_errors(metric_report)
        summaries = _metric_summaries(errors)
        cis = _paired_stratified_bootstrap(errors, reps, seed, confidence)
    except RubricError as exc:
        return {"schema": "case07-v2-l3-evaluation/v1", "status": "ERROR", "reward": None,
                "error_type": "rubric_or_metric_integrity", "message": str(exc),
                "rubric_sha256": rubric_sha256}

    criteria = {"pooled": {}, "domain_non_regression": {}}
    pooled_pass = True
    for metric in METRIC_KEYS:
        summary, ci = summaries[metric], cis[metric]["relative_improvement_ci"]
        threshold = minimums[metric]
        ok = summary["relative_improvement"] >= threshold and ci[0] >= threshold
        pooled_pass &= ok
        criteria["pooled"][metric] = {
            "required_min_relative_improvement": threshold,
            "point_estimate_pass": summary["relative_improvement"] >= threshold,
            "lower_confidence_bound_pass": ci[0] >= threshold,
            "pass": bool(ok),
        }
    domain_pass = True
    for domain in DOMAINS:
        domain_row = {}
        for metric in METRIC_KEYS:
            change = summaries[metric]["domains"][domain]["relative_change"]
            limit = max_regressions[metric]
            ok = change <= limit
            domain_pass &= ok
            domain_row[metric] = {"relative_change": change, "max_allowed_regression": limit, "pass": bool(ok)}
        criteria["domain_non_regression"][domain] = domain_row

    outcome = "PASS" if pooled_pass and domain_pass else "FAIL"
    return {
        "schema": "case07-v2-l3-evaluation/v1",
        "status": outcome,
        "reward": 1 if outcome == "PASS" else 0,
        "decision_basis": "preregistered_operational_benchmark_criterion",
        "empirical_calibration": "UNMEASURED" if calibration == "PROVISIONAL" else "CALIBRATED",
        "reason": None,
        "rubric_sha256": rubric_sha256,
        "rubric_registered_at_utc": registered.isoformat(),
        "agent_output_started_at_utc": agent_started.isoformat(),
        "calibration_status": calibration,
        "baseline_stage": "round-0",
        "target_stage": "round-2",
        "pooled": {
            metric: {
                "stage0_rmse": row["stage0_rmse"] * 1000.0,
                "stage2_rmse": row["stage2_rmse"] * 1000.0,
                "units": "meV/atom" if metric == "energy" else "meV/angstrom",
                "relative_improvement": row["relative_improvement"],
                "paired_bootstrap": cis[metric],
            }
            for metric, row in summaries.items()
        },
        "domains": {
            domain: {
                metric: {
                    "stage0_rmse": summaries[metric]["domains"][domain]["stage0_rmse"] * 1000.0,
                    "stage2_rmse": summaries[metric]["domains"][domain]["stage2_rmse"] * 1000.0,
                    "units": "meV/atom" if metric == "energy" else "meV/angstrom",
                    "relative_change": summaries[metric]["domains"][domain]["relative_change"],
                }
                for metric in METRIC_KEYS
            }
            for domain in DOMAINS
        },
        "criteria": criteria,
    }


def _verify_signed_receipt(receipt: dict, key: bytes, label: str) -> None:
    base = {k: v for k, v in receipt.items() if k not in ("receipt_hmac_sha256", "receipt_sha256")}
    expected_hmac = hmac.new(key, _canonical_json(base), hashlib.sha256).hexdigest()
    expected_sha = hashlib.sha256(_canonical_json({k: v for k, v in receipt.items() if k != "receipt_sha256"})).hexdigest()
    if not hmac.compare_digest(expected_hmac, receipt.get("receipt_hmac_sha256", "")):
        raise EnvironmentFailure(f"trusted {label} HMAC is invalid")
    if expected_sha != receipt.get("receipt_sha256"):
        raise EnvironmentFailure(f"trusted {label} receipt SHA is invalid")


def verify_trial_ledger(private: Path, refs: dict, manifest_path: Path, tests: Path):
    key_path = private / "signing.key"
    key = key_path.read_bytes()
    if len(key) != 32 or key_path.stat().st_mode & 0o077:
        raise EnvironmentFailure("trial signing key is malformed or not private")
    refs_sha = sha(tests / "refs.json")
    manifest_sha = sha(manifest_path)
    start = read_json(private / "agent-start.json", True)
    _verify_signed_receipt(start, key, "agent-start")
    runtime = refs.get("native_runtime", {})
    closure = read_json(private.parent / "runtime-closure.json", True)
    probe = closure.get("network_isolation_probe", {}).get("worker_probe", {})
    if (closure.get("schema") != "case07-local-runtime-closure/v1"
            or closure.get("runtime_closure_sha256") != runtime.get("runtime_closure_sha256")
            or closure.get("oracle_private_sha256") != runtime.get("oracle_private_sha256")
            or closure.get("uid_researcher") != 10001 or closure.get("uid_worker") != 10002
            or closure.get("network_guard") != "libseccomp-deny-non-af-unix-socket-v1"
            or closure.get("software_identity",{}).get("python",{}).get("path") != "/opt/si-ox-runtime/bin/python"
            or closure.get("software_identity",{}).get("backend") != "ICAMS/python-ace PACEMAKER + pace_yaml2yace + PyACECalculator"
            or set(closure.get("software_identity",{}).get("native_executables",{})) != {"pacemaker","pace_yaml2yace"}
            or probe.get("uid") != 10002 or probe.get("denied_families") != [2,10,17,16]
            or probe.get("af_unix_allowed") is not True
            or probe.get("python_prefix") != "/opt/si-ox-runtime"
            or probe.get("python_executable") != "/opt/si-ox-runtime/bin/python"
            or probe.get("pyace_calculator_imported") is not True
            or closure.get("network_isolation_probe",{}).get("network_guard_probe",{}).get("no_new_privs") is not True
            or closure.get("network_isolation_probe",{}).get("network_guard_probe",{}).get("seccomp_rule_api") != "seccomp_rule_add_array/SCMP_CMP_NE"):
        raise EnvironmentFailure("root-collected runtime closure or actual seccomp probe is missing/invalid")
    if (start.get("schema") != "case07-local-agent-start/v1"
            or start.get("runtime_identity_kind") != "python-runtime-closure"
            or start.get("runtime_closure_sha256") != runtime.get("runtime_closure_sha256")
            or start.get("oracle_private_sha256") != runtime.get("oracle_private_sha256")
            or start.get("geometry_manifest_sha256") != manifest_sha):
        raise EnvironmentFailure("trial start receipt does not bind the pinned native runtime and protected inputs")
    rows = []
    previous = "0" * 64
    all_ids = []
    ledger_path = private / "query-ledger.jsonl"
    for line_number, line in enumerate(ledger_path.read_text().splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EnvironmentFailure(f"trusted query ledger line {line_number} is malformed") from exc
        _verify_signed_receipt(row, key, f"query row {line_number}")
        if row.get("previous_receipt_sha256") != previous:
            raise EnvironmentFailure("trusted query receipt chain is broken")
        if row.get("agent_output_started_at_utc") != start.get("started_at_utc"):
            raise EnvironmentFailure("trusted query release is not bound to this trial start time")
        previous = row["receipt_sha256"]
        all_ids.extend(row.get("ids", []))
        rows.append(row)
    if [(row.get("phase"), row.get("count")) for row in rows] != [("seed", 12), ("round-1", 6), ("round-2", 6)]:
        raise CandidateFailure("trial did not complete the fixed 12/6/6 label-release schedule")
    state = read_json(private / "state.json", True)
    snapshot = read_json(private / "sealed-snapshot.json", True)
    _verify_signed_receipt(snapshot, key, "sealed trial snapshot")
    if (state.get("status") != "SEALED" or state.get("sealed") is not True
            or state.get("query_index") != 3 or len(all_ids) != 24
            or state.get("queried_ids") != all_ids or state.get("last_receipt_sha256") != previous
            or snapshot.get("query_ledger_sha256") != sha(ledger_path)
            or state.get("query_ledger_sha256") != sha(ledger_path)):
        raise CandidateFailure("sealed trial state differs from the authenticated 24-label ledger")
    attempts = state.get("fit_attempts", [])
    if (len(state.get("fit_slots", [])) != 9 or len(attempts) != 9
            or any(row.get("status") != "COMPLETE" for row in attempts)):
        raise CandidateFailure("trial did not complete all nine fixed trusted fit slots")
    expected_predictions = [(round_no, member) for round_no in (1, 2) for member in (1, 2, 3)]
    observed_predictions = [(row.get("round"), row.get("member"))
                            for row in state.get("pool_prediction_receipts", [])]
    if observed_predictions != expected_predictions:
        raise CandidateFailure("trial did not obtain all six trusted committee pool predictions")
    for round_no in (1, 2):
        att_path = private / f"attestation-round-{round_no}.json"
        att = read_json(att_path, True)
        _verify_signed_receipt(att, key, f"round {round_no} selection attestation")
        row = rows[round_no]
        rank_path = private / f"trusted-ranking-round-{round_no}.json"
        if (sha(att_path) != row.get("attestation_sha256")
                or sha(rank_path) != att.get("trusted_ranking_sha256")
                or att.get("prior_query_receipt_sha256") != rows[round_no - 1].get("receipt_sha256")):
            raise EnvironmentFailure(f"round {round_no} attestation is not bound to the trusted ranking and query order")
    budget_path = private / "active-budget-receipt.json"
    if not budget_path.is_file():
        raise CandidateFailure("trial did not submit the required post-fit active-budget receipt")
    budget = read_json(budget_path, True)
    _verify_signed_receipt(budget, key, "active-budget")
    fit_path = private / "fit-ledger.jsonl"
    if (budget.get("schema") != "case07-v2-active-budget-receipt/v1"
            or budget.get("query_count") != 24 or budget.get("limit_active_seconds") != 43200
            or type(budget.get("cumulative_active_seconds")) is not int
            or not 0 <= budget["cumulative_active_seconds"] <= 43200
            or budget.get("agent_start_sha256") != sha(private / "agent-start.json")
            or budget.get("query_ledger_sha256") != sha(ledger_path)
            or budget.get("fit_ledger_sha256") != sha(fit_path)
            or state.get("budget_receipt_sha256") != budget.get("receipt_sha256")):
        raise CandidateFailure("trial active-budget receipt does not bind its start, ledgers, and fixed 12-hour limit")
    return rows, state, start, budget, key


def verify_trial_fits(private: Path, key: bytes, start: dict, phase_ids: dict,
                      committees: dict, output: Path):
    fit_path = private / "fit-ledger.jsonl"
    rows = []
    for line_number, line in enumerate(fit_path.read_text().splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EnvironmentFailure(f"trusted fit ledger line {line_number} is malformed") from exc
        _verify_signed_receipt(row, key, f"fit row {line_number}")
        rows.append(row)
    if len(rows) != 9:
        raise CandidateFailure("trial does not contain exactly nine trusted ACE fits")
    for stage in range(3):
        expected_ids = list(phase_ids["seed"])
        if stage > 0:
            expected_ids.extend(phase_ids["round-1"])
        if stage > 1:
            expected_ids.extend(phase_ids["round-2"])
        if len(expected_ids) != (12 + stage * 6):
            raise CandidateFailure("fit training ID schedule is inconsistent with released labels")
        candidate_training = output / f"training/round-{stage}.extxyz"
        if not candidate_training.is_file():
            raise CandidateFailure("candidate cumulative training dataset is missing")
        expected_training_sha = sha(candidate_training)
        model_hashes = []
        for member in range(1, 4):
            row = rows[stage * 3 + member - 1]
            seed = 7000 + 100 * stage + 17 * member
            elapsed = row.get("elapsed_seconds")
            if (row.get("schema") != "case07-trusted-fit-result/v1"
                    or row.get("round") != stage or row.get("member") != member
                    or row.get("seed") != seed or row.get("training_ids") != expected_ids
                    or row.get("status") != "FIT_COMPLETE"
                    or row.get("training_sha256") != expected_training_sha
                    or type(elapsed) not in (int, float) or not math.isfinite(elapsed) or not 0 <= elapsed <= 1800):
                raise CandidateFailure("trusted fit ledger differs from the fixed stage/member/seed protocol")
            slot = private / f"models/r{stage}-m{member}"
            model = slot / "potential.yace"
            model_manifest = slot / "manifest.json"
            receipt_path = (private / row.get("execution_receipt_relpath", "")).resolve(strict=True)
            if not receipt_path.is_relative_to(private.resolve()):
                raise EnvironmentFailure("trusted native fit receipt path escaped private trial storage")
            native_receipt = read_json(receipt_path, True)
            if hashlib.sha256(_canonical_json(native_receipt)).hexdigest() != row.get("execution_receipt_sha256"):
                raise EnvironmentFailure("native isolated fit execution receipt hash differs from signed fit ledger")
            expected_runtime = start.get("runtime_closure_sha256")
            started_ns=native_receipt.get("started_monotonic_ns"); ended_ns=native_receipt.get("ended_monotonic_ns")
            network=native_receipt.get("network_guard_probe", {})
            if (native_receipt.get("schema") != "case07-local-isolated-native-fit/v1"
                    or native_receipt.get("runtime_closure_sha256") != expected_runtime
                    or native_receipt.get("worker_uid") != 10002 or native_receipt.get("worker_gid") != 10002
                    or native_receipt.get("exit_code") != 0 or native_receipt.get("timed_out") is not False
                    or type(started_ns) is not int or type(ended_ns) is not int or ended_ns <= started_ns
                    or not math.isclose(float(native_receipt.get("elapsed_seconds", -1)), (ended_ns-started_ns)/1e9, rel_tol=1e-8, abs_tol=1e-6)
                    or native_receipt.get("network_guard") != "libseccomp-deny-non-af-unix-socket-v1"
                    or network.get("denied_families") != [2,10,17,16]
                    or network.get("af_unix_allowed") is not True or network.get("no_new_privs") is not True
                    or network.get("seccomp_rule_api") != "seccomp_rule_add_array/SCMP_CMP_NE"
                    or native_receipt.get("round") != stage or native_receipt.get("member") != member
                    or native_receipt.get("seed") != seed
                    or native_receipt.get("training_sha256") != row.get("training_sha256")
                    or not re.fullmatch(r"[0-9a-f]{64}", str(native_receipt.get("executable_sha256", "")))
                    or not isinstance(native_receipt.get("argv"), list)
                    or native_receipt.get("trial_id") != start.get("trial_id")
                    or not re.fullmatch(r"[0-9a-f]{32}", str(native_receipt.get("nonce", "")))
                    or native_receipt.get("backend") != "ICAMS/python-ace PACEMAKER + pace_yaml2yace + PyACECalculator"
                    or native_receipt.get("source_runtime_sha256") != expected_runtime
                    or not isinstance(native_receipt.get("native_executables"), dict)
                    or set(native_receipt.get("native_executables",{})) != {"pacemaker","pace_yaml2yace"}):
                raise EnvironmentFailure("native fit receipt lacks the fixed runtime, worker, timing, network, and input evidence")
            if (sha(model) != row.get("model_sha256") or sha(model_manifest) != row.get("manifest_sha256")
                    or native_receipt.get("model_sha256") != row.get("model_sha256")
                    or native_receipt.get("manifest_sha256") != row.get("manifest_sha256")):
                raise EnvironmentFailure("private ACE model bytes differ from trusted native fit receipts")
            native_manifest = read_json(model_manifest, True)
            closure=json.loads((private.parent/"runtime-closure.json").read_text())
            installed=closure["software_identity"]["native_executables"]
            if (native_receipt.get("native_yaml_sha256") != native_manifest.get("native_yaml_sha256")
                    or native_receipt.get("yace_sha256") != native_manifest.get("yace_sha256")
                    or native_receipt.get("native_executables") != installed):
                raise EnvironmentFailure("native fit receipt does not bind YAML/YACE products and actual ACE executables")
            reference_path = output / "training/seed-only-reference.extxyz"
            if (not reference_path.is_file()
                    or native_manifest.get("reference_sha256") != sha(reference_path)):
                raise CandidateFailure("trusted ACE fit does not bind the fixed seed-only reference bytes")
            candidate_members = committees[stage]
            model_entry = next((entry for entry, _, _ in candidate_members if entry.get("seed") == seed), None)
            if model_entry is None or model_entry.get("model_sha256") != row["model_sha256"]:
                raise CandidateFailure("candidate committee model differs from the trial's trusted native fit")
            candidate_model = next(path for entry, path, _ in candidate_members if entry.get("seed") == seed)
            if sha(candidate_model) != row["model_sha256"]:
                raise CandidateFailure("candidate output model bytes differ from the private trusted fit")
            model_hashes.append(row["model_sha256"])
        if len(set(model_hashes)) != 3:
            raise CandidateFailure("trusted ACE committee members are not byte-distinct")
    return {"trusted_fit_slots": 9, "execution": "case07-local-isolated-native-fit/v1",
            "fit_ledger_sha256": sha(fit_path)}


def verify_trial_outputs(output: Path, private: Path, ledger: list, budget: dict,
                         committees: dict, manifest_path: Path):
    receipt_path = output / "oracle-query-receipts.jsonl"
    try:
        candidate_receipts = [json.loads(line) for line in receipt_path.read_text().splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateFailure("candidate oracle receipt stream is missing or malformed") from exc
    if len(candidate_receipts) != len(ledger):
        raise CandidateFailure("candidate oracle receipt stream differs from the trusted ledger")
    for got, expected in zip(candidate_receipts, ledger):
        if any(got.get(key) != expected.get(key) for key in ("status", "phase", "count", "receipt_sha256")):
            raise CandidateFailure("candidate query receipt differs from the authenticated release")
    stop_path, provenance_path = output / "stop_decision.json", output / "provenance.json"
    stop, provenance = read_json(stop_path), read_json(provenance_path)
    if (stop.get("schema") != "case07-v2-stop-decision/v1" or stop.get("rounds_completed") != 2
            or stop.get("query_counts") != {"seed": 12, "round-1": 6, "round-2": 6, "total": 24, "new_dft_attempts": 0}
            or stop.get("oracle_receipt_sha256") != [row["receipt_sha256"] for row in ledger]
            or stop.get("active_elapsed_seconds") != budget["cumulative_active_seconds"]):
        raise CandidateFailure("candidate stop decision differs from trusted releases or active budget")
    candidate_budget = read_json(output / "active-budget-receipt.json")
    if candidate_budget != budget:
        raise CandidateFailure("candidate active-budget copy differs from the private signed receipt")
    frozen = stop.get("frozen_committees", [])
    if len(frozen) != 3:
        raise CandidateFailure("candidate stop decision does not freeze three committees")
    for stage, row in enumerate(frozen):
        committee_path = output / f"models/round-{stage}/committee.json"
        expected_hashes = [entry["model_sha256"] for entry, _, _ in committees[stage]]
        if (row.get("path") != str(committee_path.relative_to(output)) or row.get("sha256") != sha(committee_path)
                or row.get("member_sha256") != expected_hashes):
            raise CandidateFailure(f"candidate stop decision has a different committee at stage {stage}")
    if (provenance.get("schema") != "case07-v2-provenance/v1"
            or provenance.get("public_geometry_manifest_sha256") != sha(manifest_path)
            or provenance.get("oracle_receipt_sha256") != [row["receipt_sha256"] for row in ledger]
            or provenance.get("query_count") != 24 or provenance.get("new_dft_attempts") != 0
            or provenance.get("active_budget_receipt_sha256") != sha(output / "active-budget-receipt.json")):
        raise CandidateFailure("candidate provenance does not bind the public geometry, query ledger, and budget")
    return {"stop_decision_sha256": sha(stop_path), "provenance_sha256": sha(provenance_path)}


def trusted_predictions(backend_path, backend, models, structures, outdir, tests):
    result = []
    runner = Path(__file__).resolve()
    env = {key: value for key, value in os.environ.items()
           if key in ("PATH", "LD_LIBRARY_PATH", "LANG", "LC_ALL")}
    env.update({"HOME": str(Path(outdir).resolve()), "PYTHONNOUSERSITE": "1",
                "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"})
    for index, (model_sha, model) in enumerate(models, 1):
        target = Path(outdir) / f"prediction-{model_sha[:12]}-{index}.json"
        try:
            proc = subprocess.run([sys.executable, "-I", str(runner), "--ace-worker", "predict",
                                   "--model", str(model), "--structures", str(structures), "--output", str(target)],
                                  cwd=outdir, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, timeout=1800, check=False)
        except subprocess.TimeoutExpired as exc:
            raise EnvironmentFailure("fixed trusted ACE prediction worker exceeded 1,800 seconds") from exc
        if proc.returncode != 0 or not target.is_file():
            raise EnvironmentFailure("fixed trusted ACE prediction worker failed")
        doc = read_json(target, True)
        if (doc.get("model_sha256") != model_sha or doc.get("structures_sha256") != sha(structures)
                or doc.get("frame_count") != len(read_atoms(structures, environment=True))):
            raise EnvironmentFailure("trusted ACE prediction output hash/frame binding is invalid")
        result.append(doc)
    return result


def score_hidden_from_refs(refs: dict, tests: Path, committees: dict, work: Path) -> dict:
    """Run the original paired E/F scorer over the losslessly bundled 16 sources."""
    source = refs["public_source_data"]["members"]
    mapping = refs["heldout_source_map"]["entries"]
    if len(mapping) != 16 or {row.get("domain_group") for row in mapping} != set(DOMAINS):
        raise EnvironmentFailure("bundled held-out source map does not cover the fixed six domains")
    root = work / "heldout"
    root.mkdir(mode=0o700)
    grouped = {domain: [] for domain in DOMAINS}
    for row in mapping:
        name = row.get("filename")
        packed = source.get(name)
        if (not isinstance(packed, dict) or packed.get("source_member") != row.get("source_member")
                or packed.get("source_sha256") != row.get("source_sha256")
                or packed.get("zip_crc32") != row.get("zip_crc32")
                or packed.get("uncompressed_size") != row.get("uncompressed_size")):
            raise EnvironmentFailure("held-out source map differs from embedded original source identities")
        try:
            raw = gzip.decompress(base64.b64decode(packed["data_base64"], validate=True))
        except (KeyError, ValueError, OSError, EOFError) as exc:
            raise EnvironmentFailure(f"embedded held-out source cannot be decoded: {name}") from exc
        if (len(raw) != row["uncompressed_size"]
                or hashlib.sha256(raw).hexdigest() != row["source_sha256"]
                or f"{zlib.crc32(raw) & 0xffffffff:08x}" != row["zip_crc32"]):
            raise EnvironmentFailure(f"embedded held-out source integrity check failed: {name}")
        path = root / name
        path.write_bytes(raw)
        grouped[row["domain_group"]].append((row, path))
    if len(source) != 16 or sum(len(rows) for rows in grouped.values()) != 16:
        raise EnvironmentFailure("bundled held-out source inventory is incomplete or contains extras")
    try:
        import numpy as np
        from ase.io import read
    except ImportError as exc:
        raise EnvironmentFailure(f"ASE/NumPy unavailable for held-out E/F scoring: {exc}") from exc
    report = {}
    for stage in (0, 2):
        members = committees[stage]
        models = [(member["model_sha256"], model) for member, model, _ in members]
        stage_report = {}
        for domain in DOMAINS:
            e2, fc2, fv2, e_frame, f_frame, source_groups = [], [], [], [], [], []
            nframes = 0
            for item, path in grouped[domain]:
                try:
                    frames = read(str(path), index=":", format="extxyz")
                except Exception as exc:
                    raise EnvironmentFailure(f"held-out source is not valid extxyz: {item['filename']}") from exc
                predictions = trusted_predictions(None, sys.modules[__name__], models, path, work, tests)
                for index, ref in enumerate(frames):
                    if "dft_energy" not in ref.info or "dft_forces" not in ref.arrays:
                        raise EnvironmentFailure(f"held-out source lacks required dft_energy/dft_forces: {item['filename']}")
                    energies = [float(doc["predictions"][index]["energy_eV"]) for doc in predictions]
                    forces = [np.asarray(doc["predictions"][index]["forces_eV_per_angstrom"], dtype=float)
                              for doc in predictions]
                    ref_energy, ref_forces = float(ref.info["dft_energy"]), np.asarray(ref.arrays["dft_forces"], dtype=float)
                    pred_energy, pred_forces = float(np.mean(energies)), np.mean(np.stack(forces), axis=0)
                    if (ref_forces.shape != (len(ref), 3) or pred_forces.shape != (len(ref), 3)
                            or not math.isfinite(ref_energy) or not math.isfinite(pred_energy)
                            or not np.isfinite(ref_forces).all() or not np.isfinite(pred_forces).all()):
                        raise EnvironmentFailure(f"malformed held-out E/F values in {item['filename']}")
                    energy_sq = ((pred_energy - ref_energy) / len(ref)) ** 2
                    diff = pred_forces - ref_forces
                    component_sq = (diff ** 2).ravel()
                    e2.append(energy_sq); fc2.extend(component_sq); fv2.extend((diff ** 2).sum(axis=1))
                    e_frame.append(float(energy_sq)); f_frame.append(float(np.mean(component_sq)))
                    source_groups.append(f"{domain}::{item['filename']}")
                    nframes += 1
            if nframes != 5 * len(grouped[domain]):
                raise EnvironmentFailure(f"held-out source frame count differs from the five-frame source contract: {domain}")
            stage_report[domain] = {
                "frames": nframes,
                "energy_rmse_meV_atom": 1000 * math.sqrt(float(np.mean(e2))),
                "force_component_rmse_meV_A": 1000 * math.sqrt(float(np.mean(fc2))),
                "force_component_frame_equal_rmse_meV_A": 1000 * math.sqrt(float(np.mean(f_frame))),
                "force_vector_rmse_meV_A": 1000 * math.sqrt(float(np.mean(fv2))),
                "_energy_sq_eV2_atom2": e_frame,
                "_force_component_sq_eV2_A2": f_frame,
                "_source_file_groups": source_groups,
            }
        report[f"round-{stage}"] = stage_report
    return report


def score_trial(app: Path, private: Path, tests: Path, logs: Path) -> dict:
    """Use trusted trial receipts and the original scientific checks for one trial."""
    global np
    try:
        import numpy as np
    except ImportError as exc:
        raise EnvironmentFailure(f"NumPy unavailable in the isolated verifier: {exc}") from exc
    refs = read_json(tests / "refs.json", True)
    if sha(tests / "refs.json") != REFS_SHA256:
        raise EnvironmentFailure("tests/refs.json differs from its frozen verifier pin")
    root, manifest_path, manifest, byid = public_inputs(app)
    backend = sys.modules[__name__]
    ledger, state, start, budget, key = verify_trial_ledger(private, refs, manifest_path, tests)
    validate_public_source_data(refs, tests)
    validate_private_training_source(refs, tests, app)
    output = app / "outputs"
    phase_ids = verify_candidate_labels(output, root, byid, ledger, backend)
    committees, _training = verify_training_and_committees(output, phase_ids, backend)
    fit_evidence = verify_trial_fits(private, key, start, phase_ids, committees, output)
    output_evidence = verify_trial_outputs(output, private, ledger, budget, committees, manifest_path)
    os.environ["CASE07_ORACLE_STATE_DIR"] = str(private)
    os.environ["CASE07_ORACLE_LEDGER"] = str(private / "query-ledger.jsonl")
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="case07-v2-replay-", dir=logs) as temporary:
        work = Path(temporary)
        os.chmod(work, 0o700)
        replay_selections(output, root, manifest, byid, committees, phase_ids,
                          Path(__file__).resolve(), backend, work, tests)
        hidden = score_hidden_from_refs(refs, tests, committees, work)
        rubric_row = refs.get("rubric", {})
        rubric_pin = rubric_row.get("sha256")
        rubric_raw = rubric_row.get("content_utf8")
        if (not isinstance(rubric_pin, str) or not isinstance(rubric_raw, str)
                or hashlib.sha256(rubric_raw.encode("utf-8")).hexdigest() != rubric_pin):
            raise EnvironmentFailure("embedded pre-registered L3 rubric is missing or differs from its refs pin")
        try:
            rubric = json.loads(rubric_raw)
        except json.JSONDecodeError as exc:
            raise EnvironmentFailure("embedded pre-registered L3 rubric is malformed") from exc
        if rubric.get("schema") != rubric_row.get("schema"):
            raise EnvironmentFailure("pre-registered L3 rubric schema differs from its refs pin")
        l3 = evaluate_l3(hidden, rubric, start.get("started_at_utc"), rubric_pin)
    if l3.get("status") not in ("PASS", "FAIL") or l3.get("reward") not in (0, 1):
        raise EnvironmentFailure(l3.get("message", "fixed L3 evaluator returned ERROR"))
    safe_l3 = {k: v for k, v in l3.items() if k not in ("status", "reward", "reason", "error_type", "message")}
    return {
        "case_id": "case-07", "overall": l3["status"], "reward": float(l3["reward"]),
        "workflow_l1_l2": "PASS", "oracle_queries": 24, "new_dft_attempts": 0,
        "heldout_l3": safe_l3, "family_independence": "UNKNOWN_NOT_ASSESSED",
        "model_fit_provenance": fit_evidence, "trial_output_evidence": output_evidence,
        "active_elapsed_seconds": budget["cumulative_active_seconds"],
    }


def score_trial_main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="score one isolated case-07 trial")
    parser.add_argument("--score-trial", action="store_true")
    parser.add_argument("--app", required=True)
    parser.add_argument("--private", required=True)
    parser.add_argument("--tests", default=str(Path(__file__).parent))
    parser.add_argument("--logs", required=True)
    args = parser.parse_args(argv)
    try:
        result = score_trial(Path(args.app).resolve(), Path(args.private).resolve(),
                             Path(args.tests).resolve(), Path(args.logs).resolve())
        code = persist(result, Path(args.logs))
    except CandidateFailure as exc:
        code = persist({"case_id": "case-07", "overall": "FAIL", "reward": 0.0,
                        "error_type": "candidate_evidence", "error": str(exc)}, Path(args.logs))
    except (EnvironmentFailure, OSError, ValueError, KeyError, TypeError) as exc:
        code = persist({"case_id": "case-07", "overall": "ERROR", "reward": None,
                        "error_type": "trusted_verifier", "error": str(exc)}, Path(args.logs))
    except Exception as exc:
        code = persist({"case_id": "case-07", "overall": "ERROR", "reward": None,
                        "error_type": "trusted_verifier", "error": f"unexpected verifier failure: {type(exc).__name__}"},
                       Path(args.logs))
    report = read_json(Path(args.logs) / "verification.json", True)
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return code


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--ace-worker":
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        return _ace_worker_main() or 0
    return score_trial_main()


if __name__ == "__main__":
    raise SystemExit(main())
