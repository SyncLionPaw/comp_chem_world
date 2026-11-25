FROM compchembench-connectivity:hpc

WORKDIR /app

COPY AGENTS.md /app/AGENTS.md
# Inherit the connectivity base and add the pinned PACEMAKER/PyACE runtime.
# The trial-local trusted service dispatches fits to isolated workers.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential cmake ninja-build python3.12-dev python3.12-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3.12 -m venv /opt/si-ox-runtime

ENV PATH="/opt/si-ox-runtime/bin:${PATH}"

COPY wheels/ /opt/wheels/
COPY requirements.lock.txt /tmp/requirements.lock
RUN pip install --no-cache-dir --no-index --find-links=/opt/wheels --only-binary=:all: --require-hashes -r /tmp/requirements.lock \
    && rm -rf /opt/wheels

COPY assets/runtime-source/python-ace-66c35ea6e5dbed2857d423952b922183206c140e.tar.gz /tmp/python-ace.tar.gz
RUN printf '%s\n' \
        '--- a/CMakeLists.txt' \
        '+++ b/CMakeLists.txt' \
        '@@ -55,7 +55,7 @@' \
        ' include_directories(${CNPY_INCLUDE_PATH})' \
        ' ' \
        '-add_subdirectory(lib/pybind11)' \
        '+find_package(pybind11 2.13 CONFIG REQUIRED)' \
        ' ' \
        ' ' \
        ' # for advanced functionality' \
        > /tmp/use-installed-pybind11.patch \
    && echo '6629cdcbfcce08bb859bd6990758b35b57b4b8d89b38099b4f2830fe64fec65d  /tmp/python-ace.tar.gz' | sha256sum -c - \
    && mkdir -p /tmp/pyace-source \
    && tar -xzf /tmp/python-ace.tar.gz -C /tmp/pyace-source --strip-components=1 \
    && patch -d /tmp/pyace-source -p1 < /tmp/use-installed-pybind11.patch \
    && CMAKE_BUILD_PARALLEL_LEVEL=2 CMAKE_ARGS="-Dpybind11_DIR=$(python -m pybind11 --cmakedir)" PIP_NO_INDEX=1 \
       pip install --no-cache-dir --no-build-isolation --no-deps /tmp/pyace-source \
    && PIP_NO_INDEX=1 pip install --no-cache-dir --no-build-isolation --no-deps /tmp/pyace-source/lib/maxvolpy \
    && pip check \
    && rm -rf /tmp/pyace-source /tmp/python-ace.tar.gz /tmp/use-installed-pybind11.patch

RUN python -c 'import numpy, pandas, ase, pyace; from pyace.asecalc import PyACECalculator; import maxvolpy; print("case-06 NumPy/ASE/PyACE runtime PASS", numpy.__version__, ase.__version__, pyace.__file__)' \
    && pip check

COPY assets/README.md /app/inputs/README.md
COPY assets/v2/ /app/inputs/v2/

# The worker runtime needs libseccomp, installed after the cached PyACE build layer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libseccomp2 \
    && rm -rf /var/lib/apt/lists/*

# Harbor runs the researcher as an ordinary user. The root PID 1 owns the
# oracle broker and signing key; native ACE work runs as a separate worker UID.
COPY assets/oracle-private.json /opt/case07/oracle-private.json
RUN groupadd --gid 10001 researcher \
    && useradd --uid 10001 --gid 10001 --create-home --shell /bin/bash researcher \
    && groupadd --gid 10002 case07worker \
    && useradd --uid 10002 --gid 10002 --no-create-home --shell /usr/sbin/nologin case07worker \
    && install -d -o researcher -g researcher -m 0750 /app/outputs /app/workspace \
    && install -d -o root -g root -m 0711 /trusted /trusted/case07 \
    && install -d -o root -g root -m 0700 /app/case07-artifacts/trusted \
    && install -d -o root -g researcher -m 0750 /run/case07 \
    && install -d -o root -g root -m 0711 /run/case07-worker \
    && chown root:root /opt/case07/oracle-private.json \
    && chmod 0400 /opt/case07/oracle-private.json \
    && (rm -f /usr/bin/sudo /usr/sbin/sudo /bin/su /usr/bin/su /usr/bin/pkexec /etc/sudoers.d/* || true)

# Remove inherited setuid/setgid bits and file capabilities; worker network
# isolation is enforced by a per-process seccomp filter in the runtime.
RUN /usr/bin/python3 - <<'PY'
import errno, os, stat
skip = {'proc', 'sys', 'dev', 'run'}
for root, dirs, files in os.walk('/', topdown=True, followlinks=False):
    if root == '/': dirs[:] = [name for name in dirs if name not in skip]
    for name in [*dirs, *files]:
        path = os.path.join(root, name)
        try:
            info = os.stat(path, follow_symlinks=False)
            if stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode):
                if info.st_mode & 0o6000:
                    os.chmod(path, stat.S_IMODE(info.st_mode) & ~0o6000, follow_symlinks=False)
                try:
                    if 'security.capability' in os.listxattr(path, follow_symlinks=False):
                        os.removexattr(path, 'security.capability', follow_symlinks=False)
                except OSError as exc:
                    if exc.errno not in (errno.ENODATA, errno.ENOTSUP, getattr(errno, 'EOPNOTSUPP', errno.ENOTSUP)):
                        raise
        except FileNotFoundError:
            continue
PY

# Runtime/entrypoint is emitted inline below; it does not copy tests or the
# reference solution into the task image.

RUN cat > /opt/case07/runtime.py <<'PY_CASE07_RUNTIME'
from __future__ import annotations
import argparse, base64, ctypes, datetime, errno, fcntl, gzip, hashlib, hmac, json, math, os, pwd, grp, re, secrets, shutil, signal, socket, struct, subprocess, sys, tarfile, tempfile, threading, time, uuid, zlib
from datetime import timezone
from pathlib import Path
from typing import Any

ORACLE_PRIVATE_SHA256 = "948478437db46ed3a8681e855d8b756eb89c7ffdf1313eb55050f64263249773"
DOMAINS = ("amorphous", "amorphous_silicon", "crystalline", "high_pressure", "mixed", "surfaces")
ELEMENTS = ("Si", "O")
RUNTIME_SCHEMA = "case07-local-isolated-native-fit/v1"

class TrialControlError(RuntimeError):
    pass


def _canonical_json(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _atomic_json(path: Path, value: dict, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + ".tmp-" + secrets.token_hex(6))
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    os.chmod(path, mode)


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


class TrialControlService:
    """Per-trial, append-only query and budget state; no model fitting fallback."""

    PHASES = (("seed", 12), ("round-1", 6), ("round-2", 6))
    LIMIT_SECONDS = 43200

    def __init__(self, refs_path: Path, public_manifest_path: Path, trial_dir: Path,
                 *, clock=time.monotonic, attestor=None, fitter=None, predictor=None):
        self.refs_path = Path(refs_path).resolve(strict=True)
        self.public_manifest_path = Path(public_manifest_path).resolve(strict=True)
        self.trial_dir = Path(trial_dir).resolve()
        self.clock = clock
        self.attestor = attestor
        self.fitter = fitter
        self.predictor = predictor
        self._lock = threading.RLock()
        self._start_monotonic = None
        self._key = secrets.token_bytes(32)
        self.trial_id = uuid.uuid4().hex
        self.private_dir = self.trial_dir / ".case07-learning" / self.trial_id
        self.private_dir.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.private_dir.parent, 0o700)
        self.private_dir.mkdir(mode=0o700)
        os.chmod(self.private_dir, 0o700)
        self.ledger_path = self.private_dir / "query-ledger.jsonl"
        self.fit_ledger_path = self.private_dir / "fit-ledger.jsonl"
        for ledger in (self.ledger_path, self.fit_ledger_path):
            fd = os.open(ledger, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        self.state_path = self.private_dir / "state.json"
        self.key_path = self.private_dir / "signing.key"
        fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(self._key)
            stream.flush()
            os.fsync(stream.fileno())
        refs_raw = self.refs_path.read_bytes()
        refs = json.loads(refs_raw.decode("utf-8"))
        if hashlib.sha256(refs_raw).hexdigest() != ORACLE_PRIVATE_SHA256:
            raise TrialControlError("root-only oracle asset differs from its frozen source pin")
        source = refs.get("private_training_source", {})
        template = refs.get("trusted_ace_template", {})
        template_text = template.get("content_utf8")
        if (template.get("schema") != "case07-trusted-ace-template/v1"
                or not isinstance(template_text, str)
                or hashlib.sha256(template_text.encode("utf-8")).hexdigest() != template.get("sha256")):
            raise TrialControlError("refs.json trusted ACE template is missing or changed")
        self.template_bytes = template_text.encode("utf-8")
        self.template_sha256 = template["sha256"]
        if (source.get("schema") != "case07-private-training-label-source/v1"
                or source.get("source_dataset_sha256") != "beb2616dd95b7e33899f488ec9680a46474f9c85630340ca343dfbb60c4f9548"
                or len(source.get("entries", {})) != 132):
            raise TrialControlError("protected per-trial training source is missing or changed")
        manifest = json.loads(self.public_manifest_path.read_text(encoding="utf-8"))
        if (manifest.get("schema") != "case07-v2-public-geometry-manifest/v1"
                or manifest.get("source_dataset_sha256") != source.get("source_dataset_sha256")
                or len(manifest.get("entries", [])) != 132
                or hashlib.sha256(self.public_manifest_path.read_bytes()).hexdigest() != source.get("geometry_manifest_sha256")):
            raise TrialControlError("protected public geometry manifest is missing or changed")
        self.entries = source["entries"]
        self.public = {row["id"]: row for row in manifest["entries"]}
        if set(self.entries) != set(self.public):
            raise TrialControlError("private label IDs differ from the public geometry manifest")
        self._labels = {}
        for ident, row in self.entries.items():
            try:
                raw = gzip.decompress(base64.b64decode(row["data_base64"], validate=True))
            except Exception as exc:
                raise TrialControlError("protected source frame decode failed") from exc
            if hashlib.sha256(raw).hexdigest() != row.get("frame_sha256"):
                raise TrialControlError("protected source frame identity check failed")
            self._labels[ident] = raw
        self._state = {
            "schema": "case07-trial-control-state/v1", "trial_id": self.trial_id,
            "status": "CREATED", "query_index": 0, "queried_ids": [],
            "last_receipt_sha256": "0" * 64, "attested_round": None,
            "fit_slots": [], "fit_attempts": [], "pool_prediction_receipts": [], "sealed": False,
        }
        _atomic_json(self.state_path, self._state)
        self._record_trial(self)

    _live_trials = {}

    @classmethod
    def _record_trial(cls, instance):
        cls._live_trials[str(instance.private_dir.parent.resolve())] = instance

    @classmethod
    def get_trial(cls, private_dir: Path):
        return cls._live_trials.get(str(Path(private_dir).resolve()))

    def _persist(self):
        _atomic_json(self.state_path, self._state)

    def _signed_receipt(self, base: dict) -> dict:
        receipt = dict(base)
        receipt["receipt_hmac_sha256"] = hmac.new(self._key, _canonical_json(base), hashlib.sha256).hexdigest()
        receipt["receipt_sha256"] = hashlib.sha256(_canonical_json(receipt)).hexdigest()
        return receipt

    def _require_live(self):
        if self._state.get("sealed") or self._state.get("status") == "SEALED":
            raise TrialControlError("trial service is sealed")
        if self._state.get("budget_receipt_sha256"):
            raise TrialControlError("trial budget has been frozen")
        if self._start_monotonic is not None and self.clock() - self._start_monotonic >= self.LIMIT_SECONDS:
            raise TrialControlError("trial active-time limit exceeded")


    def begin_run(self) -> dict:
        with self._lock:
            if self._state["status"] != "READY" or self._start_monotonic is None:
                raise TrialControlError("begin-run requires the already activated trial and is permitted exactly once")
            self._state.update({"status": "RUNNING"})
            self._persist()
            return {"status": "RUNNING", "trial_id": self.trial_id,
                    "started_at_utc": self.start_receipt["started_at_utc"],
                    "agent_start_receipt_sha256": hashlib.sha256(_canonical_json(self.start_receipt)).hexdigest()}

    @staticmethod
    def _with_queried_id(raw: bytes, ident: str) -> bytes:
        lines = raw.splitlines(keepends=True)
        if len(lines) < 2 or not lines[1].endswith((b"\n", b"\r")):
            raise TrialControlError("protected source frame has malformed extended XYZ comment")
        end = len(lines[1].rstrip(b"\r\n"))
        lines[1] = lines[1][:end] + b" queried_id=" + ident.encode("ascii") + lines[1][end:]
        return b"".join(lines)

    def _validate_fit_dataset(self, raw: bytes, expected_ids: list[str], label: str) -> None:
        """Accept the solve.sh ASE rewrite only when ordered geometries and labels match."""
        try:
            import numpy as np
            from ase.io import read
            from io import StringIO
            frames = read(StringIO(raw.decode("utf-8")), index=":", format="extxyz")
        except Exception as exc:
            raise TrialControlError(f"{label} fit dataset is not valid extxyz") from exc
        if len(frames) != len(expected_ids):
            raise TrialControlError(f"{label} fit dataset frame count differs from its fixed ID schedule")
        for ident, atoms in zip(expected_ids, frames):
            if atoms.info.get("queried_id") != ident:
                raise TrialControlError(f"{label} fit dataset IDs/order differ from the fixed release schedule")
            try:
                expected = read(StringIO(self._with_queried_id(self._labels[ident], ident).decode("utf-8")),
                                format="extxyz")
                got_energy = float(atoms.info["dft_energy"])
                expected_energy = float(expected.info["dft_energy"])
                got_forces = np.asarray(atoms.arrays["dft_forces"], dtype=float)
                expected_forces = np.asarray(expected.arrays["dft_forces"], dtype=float)
            except Exception as exc:
                raise TrialControlError(f"{label} fit dataset has missing or malformed DFT E/F labels") from exc
            if (geometry_digest(atoms) != geometry_digest(expected)
                    or not math.isfinite(got_energy) or got_energy != expected_energy
                    or got_forces.shape != expected_forces.shape
                    or not np.isfinite(got_forces).all()
                    or not np.array_equal(got_forces, expected_forces)):
                raise TrialControlError(f"{label} fit dataset differs from trusted ordered geometry/E/F for {ident}")

    def query(self, request: dict) -> tuple[dict, bytes]:
        with self._lock:
            self._require_live()
            if self._state["status"] != "RUNNING":
                raise TrialControlError("begin-run must precede labels")
            phase, count = self.PHASES[self._state["query_index"]] if self._state["query_index"] < len(self.PHASES) else (None, 0)
            ids = request.get("ids")
            if request.get("phase") != phase or not isinstance(ids, list) or len(ids) != count:
                raise TrialControlError("query does not match the next fixed release")
            if len(set(ids)) != len(ids) or set(ids) & set(self._state["queried_ids"]):
                raise TrialControlError("query IDs are repeated or already released")
            if phase == "seed":
                expected = [row["id"] for row in json.loads(self.public_manifest_path.read_text())["entries"] if row["phase"] == "seed"]
                if ids != expected:
                    raise TrialControlError("seed release IDs/order differ from the frozen manifest")
            else:
                if self._state.get("attested_round") != int(phase[-1]):
                    raise TrialControlError("round labels require prior trusted selection attestation")
                domains = [self.public.get(ident, {}).get("domain") for ident in ids]
                if (any(self.public.get(ident, {}).get("phase") != "pool" for ident in ids)
                        or len(set(domains)) != 6 or domains != sorted(domains)):
                    raise TrialControlError("each round must release six alphabetically ordered pool domains")
                attested = self._state.get("attested_ids")
                if ids != attested:
                    raise TrialControlError("query differs from the registered selection attestation")
            body = b"".join(self._with_queried_id(self._labels[x], x) for x in ids)
            base = {"schema": "case07-v2-oracle-query-receipt/v1", "status": "RELEASED",
                    "phase": phase, "count": count, "ids": list(ids),
                    "agent_output_started_at_utc": self.start_receipt["started_at_utc"],
                    "released_labels_sha256": hashlib.sha256(body).hexdigest(),
                    "previous_receipt_sha256": self._state["last_receipt_sha256"]}
            if phase != "seed":
                attestation_path = self.private_dir / f"attestation-round-{phase[-1]}.json"
                base["attestation_sha256"] = hashlib.sha256(attestation_path.read_bytes()).hexdigest()
            receipt = self._signed_receipt(base)
            with self.ledger_path.open("ab") as stream:
                stream.write(_canonical_json(receipt) + b"\n"); stream.flush(); os.fsync(stream.fileno())
            self._state["queried_ids"].extend(ids)
            self._state["last_receipt_sha256"] = receipt["receipt_sha256"]
            self._state["query_index"] += 1
            self._state["attested_round"] = None
            self._state.pop("attested_ids", None)
            self._persist()
            public_receipt = {k: receipt[k] for k in ("status", "phase", "count", "receipt_sha256")}
            return public_receipt, body

    def attest_selection(self, round_no: int, selection: dict) -> dict:
        with self._lock:
            self._require_live()
            if round_no not in (1, 2) or self._state["query_index"] != round_no:
                raise TrialControlError("selection attestation is out of order")
            if self._state.get("attested_round") is not None:
                raise TrialControlError("round selection may be attested only once")
            if self.attestor is None:
                raise TrialControlError("trusted full-pool ACE replay is not configured")
            expected = self.attestor(round_no, selection, tuple(self._state["queried_ids"]))
            ids = selection.get("selected_ids")
            if ids != expected or len(ids) != 6 or len(set(ids)) != 6:
                raise TrialControlError("selection differs from trusted full-pool replay")
            base = {"schema": "case07-trusted-selection-attestation/v1", "round": round_no,
                    "selected_ids": list(ids), "prior_query_receipt_sha256": self._state["last_receipt_sha256"],
                    "selection_sha256": hashlib.sha256(_canonical_json(selection)).hexdigest(),
                    "trusted_ranking_sha256": hashlib.sha256((self.private_dir / f"trusted-ranking-round-{round_no}.json").read_bytes()).hexdigest(),
                    "created_at_utc": datetime.datetime.now(timezone.utc).isoformat(timespec="seconds")}
            receipt = self._signed_receipt(base)
            _atomic_json(self.private_dir / f"attestation-round-{round_no}.json", receipt)
            self._state["attested_round"] = round_no
            self._state["attested_ids"] = list(ids)
            self._persist()
            return {"status": "ATTESTED", "round": round_no, "selected_ids": list(ids),
                    "attestation_sha256": hashlib.sha256(_canonical_json(receipt)).hexdigest()}

    def fit_member(self, **request) -> dict:
        with self._lock:
            self._require_live()
            if self.fitter is None:
                raise TrialControlError("trusted isolated ACE fit runner is not configured")
            round_no = request.get("round")
            member = request.get("member")
            if (type(round_no) is not int or type(member) is not int
                    or round_no not in (0, 1, 2) or member not in (1, 2, 3)):
                raise TrialControlError("fit round/member is outside the fixed nine-slot campaign")
            expected_slots = [(r, m) for r in range(3) for m in range(1, 4)]
            slot_index = len(self._state["fit_attempts"])
            if slot_index >= 9 or expected_slots[slot_index] != (round_no, member):
                raise TrialControlError("fit-member calls must follow the nine frozen stage/member slots")
            if self._state["query_index"] != round_no + 1:
                raise TrialControlError("fit stage requires its cumulative label release first")
            expected_ids = self._state["queried_ids"][:12 + max(0, round_no) * 6]
            if request.get("training_ids") != expected_ids:
                raise TrialControlError("fit training IDs differ from this stage's exact revealed labels")
            expected_seed = 7000 + 100 * round_no + 17 * member
            if request.get("seed") != expected_seed or request.get("timeout_seconds", 1800) != 1800:
                raise TrialControlError("fit seed or fixed 1,800 second ceiling differs from the protocol")
            attempt = {"round": round_no, "member": member, "seed": expected_seed,
                       "training_ids": list(expected_ids), "training_sha256": request.get("training_sha256"),
                       "started_at_utc": datetime.datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "status": "STARTED"}
            self._state["fit_attempts"].append(attempt)
            self._persist()
            started = self.clock()
            try:
                result = self.fitter(request, self)
                if not isinstance(result, dict) or result.get("status") != "FIT_COMPLETE":
                    raise TrialControlError("trusted fit runner did not return a complete native result")
                row = {"round": round_no, "member": member, "seed": expected_seed,
                       "training_ids": list(expected_ids), "training_sha256": request.get("training_sha256"),
                       "model_sha256": result.get("model_sha256"), "manifest_sha256": result.get("manifest_sha256"),
                       "execution_receipt_sha256": result.get("execution_receipt_sha256"),
                       "execution_receipt_relpath": result.get("execution_receipt_relpath"),
                       "elapsed_seconds": result.get("elapsed_seconds"), "status": "FIT_COMPLETE"}
                if not all(isinstance(row[k], str) and len(row[k]) == 64 for k in ("training_sha256", "model_sha256", "manifest_sha256", "execution_receipt_sha256")):
                    raise TrialControlError("trusted fit result is missing pinned input/model/process evidence")
                if type(row["elapsed_seconds"]) not in (int, float) or not 0 <= row["elapsed_seconds"] <= 1800:
                    raise TrialControlError("trusted fit result exceeded its fixed 1,800 second ceiling")
                receipt_rel = row["execution_receipt_relpath"]
                if not isinstance(receipt_rel, str):
                    raise TrialControlError("trusted fit runner omitted the host-private execution receipt path")
                receipt_path = (self.private_dir / receipt_rel).resolve(strict=True)
                if (not receipt_path.is_relative_to(self.private_dir.resolve())
                        or hashlib.sha256(_canonical_json(json.loads(receipt_path.read_text()))).hexdigest() != row["execution_receipt_sha256"]):
                    raise TrialControlError("host-private native fit execution receipt failed its digest binding")
                event = self._signed_receipt({"schema": "case07-trusted-fit-result/v1", **row})
                with self.fit_ledger_path.open("ab") as stream:
                    stream.write(_canonical_json(event) + b"\n"); stream.flush(); os.fsync(stream.fileno())
                self._state["fit_slots"].append(row)
                attempt.update({"status": "COMPLETE", "elapsed_seconds": self.clock() - started,
                                "execution_receipt_sha256": row["execution_receipt_sha256"]})
                self._persist()
                result["trusted_fit_receipt"] = event
                return result
            except Exception as exc:
                attempt.update({"status": "FAILED", "elapsed_seconds": self.clock() - started,
                                "failure_type": type(exc).__name__})
                self._persist()
                raise

    def budget_check(self) -> dict:
        with self._lock:
            self._require_live()
            if self._state["query_index"] != len(self.PHASES) or len(self._state["queried_ids"]) != 24:
                raise TrialControlError("budget receipt is only available after the fixed 24-label schedule")
            if len(self._state["fit_slots"]) != 9:
                raise TrialControlError("budget receipt requires all nine completed trusted fit slots")
            existing = self.private_dir / "active-budget-receipt.json"
            if existing.is_file():
                return json.loads(existing.read_text(encoding="utf-8"))
            elapsed = int(self.clock() - self._start_monotonic)
            if not 0 <= elapsed <= self.LIMIT_SECONDS:
                raise TrialControlError("trial active-time limit exceeded")
            base = {"schema": "case07-v2-active-budget-receipt/v1", "trial_id": self.trial_id,
                    "cumulative_active_seconds": elapsed, "limit_active_seconds": self.LIMIT_SECONDS,
                    "query_count": len(self._state["queried_ids"]),
                    "agent_start_sha256": hashlib.sha256((self.private_dir / "agent-start.json").read_bytes()).hexdigest(),
                    "query_ledger_sha256": hashlib.sha256(self.ledger_path.read_bytes()).hexdigest(),
                    "fit_ledger_sha256": hashlib.sha256(self.fit_ledger_path.read_bytes()).hexdigest()}
            receipt = self._signed_receipt(base)
            self._state["budget_receipt_sha256"] = receipt["receipt_sha256"]
            self._persist()
            _atomic_json(self.private_dir / "active-budget-receipt.json", receipt)
            return receipt

    def health(self) -> dict:
        with self._lock:
            self._require_live()
            return {"status": "READY", "trial_id": self.trial_id}

    def seal(self) -> dict:
        with self._lock:
            if self._state.get("sealed"):
                return json.loads(self.state_path.read_text())
            self._state["sealed"] = True
            self._state["status"] = "SEALED"
            self._state["sealed_at_utc"] = datetime.datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._state["query_ledger_sha256"] = hashlib.sha256(self.ledger_path.read_bytes()).hexdigest() if self.ledger_path.exists() else hashlib.sha256(b"").hexdigest()
            self._persist()
            snapshot = {k: self._state[k] for k in ("schema", "trial_id", "status", "query_index", "queried_ids", "last_receipt_sha256", "fit_slots", "fit_attempts", "pool_prediction_receipts", "sealed", "sealed_at_utc", "query_ledger_sha256")}
            signed = self._signed_receipt(snapshot)
            _atomic_json(self.private_dir / "sealed-snapshot.json", signed)
            return signed

    @property

    def predict_pool(self, round_no: int, member: int) -> dict:
        with self._lock:
            self._require_live()
            if self.predictor is None:
                raise TrialControlError("trusted isolated ACE prediction runner is not configured")
            if type(round_no) is not int or type(member) is not int or round_no not in (1, 2) or member not in (1, 2, 3):
                raise TrialControlError("pool prediction round/member is outside the frozen campaign")
            if self._state["query_index"] != round_no:
                raise TrialControlError("pool prediction is only available after the preceding stage fit")
            if {(row["round"], row["member"]) for row in self._state["fit_slots"]} < {(round_no - 1, 1), (round_no - 1, 2), (round_no - 1, 3)}:
                raise TrialControlError("full-pool prediction requires all three completed committee fits")
            cache_path = self.private_dir / f"predictions-round-{round_no}-member-{member}.json"
            if cache_path.exists():
                cached = json.loads(cache_path.read_text())
                return {"status": "PREDICTED", "round": round_no, "member": member,
                        "model_sha256": cached["receipt"]["model_sha256"],
                        "pool_sha256": cached["receipt"]["pool_sha256"],
                        "predictions": cached["predictions"]["predictions"],
                        "receipt_sha256": cached["receipt"]["receipt_sha256"]}
            result = self.predictor(round_no, member, self)
            receipt_sha = result.get("receipt_sha256")
            self._state["pool_prediction_receipts"].append({"round": round_no, "member": member,
                                                              "receipt_sha256": receipt_sha})
            self._persist()
            return result

    def predict_candidate_model(self, model_sha256: str, pool_sha256: str) -> dict:
        with self._lock:
            self._require_live()
            round_no = self._state["query_index"]
            if round_no not in (1, 2):
                raise TrialControlError("trusted predictions are only available after seed/round-1 fits")
            pool_bytes = b"".join(
                (self.public_manifest_path.parent / row["path"]).read_bytes()
                for row in json.loads(self.public_manifest_path.read_text())["entries"]
                if row["phase"] == "pool")
            actual_pool_sha = hashlib.sha256(pool_bytes).hexdigest()
            if pool_sha256 != actual_pool_sha:
                raise TrialControlError("candidate prediction request differs from the complete frozen public pool")
            slot = next((row for row in self._state["fit_slots"]
                         if row["round"] == round_no - 1 and row["model_sha256"] == model_sha256), None)
            if slot is None:
                raise TrialControlError("candidate prediction model is not a trusted completed fit in this stage")
            result = self.predict_pool(round_no, slot["member"])
            return {**result, "structures_sha256": actual_pool_sha}

    def dispatch(self, path: str, document: dict) -> dict:
        """Shared routing logic used by the HTTP adapter and local lifecycle mocks."""
        if path == "/health":
            result, body = self.health(), None
        elif path == "/begin-run":
            result, body = self.begin_run(), None
        elif path == "/query":
            result, body = self.query(document)
        elif path == "/attest-selection":
            result, body = self.attest_selection(int(document["round"]), document["selection"]), None
        elif path == "/fit-member":
            result, body = self.fit_member(**document), None
        elif path == "/predict-pool":
            result, body = self.predict_pool(int(document["round"]), int(document["member"])), None
        elif path == "/predict-candidate-model":
            result, body = self.predict_candidate_model(document["model_sha256"], document["pool_sha256"]), None
        elif path == "/budget-check":
            result, body = self.budget_check(), None
        else:
            raise TrialControlError("unknown trial-control route")
        return {"result": result, "labels_base64": base64.b64encode(body).decode() if body is not None else None}



    def retire(self):
        self._live_trials.pop(str(self.private_dir.parent.resolve()), None)


    def attest_selection(self, round_no: int, selection: dict, queried_ids: tuple[str, ...], service=None) -> list[str]:
        if round_no not in (1, 2):
            raise TrialControlError("trusted selection replay round is invalid")
        candidate = selection.get("selection")
        request = selection.get("request")
        bindings = selection.get("candidate_bindings")
        if not isinstance(candidate, dict) or not isinstance(request, dict):
            raise TrialControlError("selection attestation requires both the ranked artifact and query request")
        expected_models = [row["model_sha256"] for row in service._state["fit_slots"]
                           if row["round"] == round_no - 1]
        expected_training_ids = list(queried_ids[:12 + (round_no - 1) * 6])
        if (not isinstance(bindings, dict) or len(expected_models) != 3
                or candidate.get("model_sha256") != expected_models
                or bindings.get("committee_sha256") != candidate.get("committee_sha256")
                or bindings.get("training_ids") != expected_training_ids
                or not re.fullmatch(r"[0-9a-f]{64}", str(bindings.get("training_sha256", "")))
                or bindings.get("pool_sha256") != candidate.get("pool_sha256")):
            raise TrialControlError("candidate ranking is not bound to the trusted fitted committee")
        manifest = json.loads((self.public_root / "geometry-manifest.json").read_text())
        entries = [row for row in manifest["entries"] if row["phase"] == "pool"]
        predictions = []
        for member in (1, 2, 3):
            cache = self.private_dir / f"predictions-round-{round_no}-member-{member}.json"
            if not cache.is_file():
                raise TrialControlError("selection attestation requires all three trusted full-pool predictions")
            doc = json.loads(cache.read_text())
            if doc["predictions"].get("frame_count") != len(entries):
                raise TrialControlError("trusted pool prediction cache is incomplete")
            predictions.append(doc["predictions"]["predictions"])
        rows = []
        queried = set(queried_ids)
        for index, entry in enumerate(entries):
            force_sets = [pred[index]["forces_eV_per_angstrom"] for pred in predictions]
            flattened = [component for forces in force_sets for atom in forces for component in atom]
            if not flattened or any(type(x) not in (float, int) or not math.isfinite(x) for x in flattened):
                raise TrialControlError("trusted predictions contain malformed or non-finite forces")
            variances = []
            for atom_i in range(entry["n_atoms"]):
                for axis in range(3):
                    vals = [float(forces[atom_i][axis]) for forces in force_sets]
                    mean = sum(vals) / len(vals)
                    variances.append(sum((x - mean) ** 2 for x in vals) / (len(vals) - 1))
            score = math.sqrt(sum(variances) / len(variances))
            rows.append({"id": entry["id"], "domain": entry["domain"],
                         "geometry_sha256": entry["geometry_sha256"],
                         "force_disagreement_eV_per_A": score,
                         "eligible_for_selection": entry["id"] not in queried})
        rows.sort(key=lambda row: (row["domain"], -row["force_disagreement_eV_per_A"], row["id"]))
        selected = []
        for domain in sorted({row["domain"] for row in rows}):
            eligible = [row for row in rows if row["domain"] == domain and row["eligible_for_selection"]]
            if not eligible:
                raise TrialControlError("trusted full-pool replay has no eligible structure in a domain")
            selected.append(eligible[0])
        expected_pool_hashes = []
        for member in (1, 2, 3):
            cached = json.loads((self.private_dir / f"predictions-round-{round_no}-member-{member}.json").read_text())
            expected_pool_hashes.append(cached["receipt"]["pool_sha256"])
        if (candidate.get("round") != round_no or len(candidate.get("ranked", [])) != len(rows)
                or len(set(expected_pool_hashes)) != 1 or candidate.get("pool_sha256") != expected_pool_hashes[0]):
            raise TrialControlError("selection artifact round/pool identity differs from trusted predictions")
        expected_ids = [row["id"] for row in selected]
        if request.get("phase") != f"round-{round_no}" or request.get("ids") != expected_ids:
            raise TrialControlError("query request differs from the trusted per-domain force-disagreement ranking")
        got = candidate.get("ranked", [])
        for actual, expected in zip(got, rows):
            if (actual.get("id") != expected["id"] or actual.get("geometry_sha256") != expected["geometry_sha256"]
                    or bool(actual.get("eligible_for_selection")) != expected["eligible_for_selection"]
                    or not math.isclose(float(actual.get("force_disagreement_eV_per_A", float("nan"))),
                                        expected["force_disagreement_eV_per_A"], rel_tol=1e-8, abs_tol=1e-12)):
                raise TrialControlError("candidate ranking differs from trusted ACE full-pool replay")
        if not any(row["force_disagreement_eV_per_A"] > 1e-12 for row in rows if row["eligible_for_selection"]):
            raise TrialControlError("trusted ACE committee has zero eligible pool force disagreement")
        rank_path = self.private_dir / f"trusted-ranking-round-{round_no}.json"
        _atomic_json(rank_path, {"schema": "case07-trusted-force-ranking/v1", "round": round_no,
                                 "pool_sha256": json.loads((self.private_dir / f"predictions-round-{round_no}-member-1.json").read_text())["receipt"]["pool_sha256"],
                                 "rows": rows, "selected_ids": expected_ids})
        return expected_ids


    def fit(self, request: dict, service) -> dict:
        ident = f"r{request['round']}-m{request['member']}"
        work = self.private_dir / "workers" / ident
        work.mkdir(parents=True, mode=0o700, exist_ok=False)
        inputs = work / "inputs"
        inputs.mkdir(mode=0o700)
        training = base64.b64decode(request["training_data_base64"], validate=True)
        reference = base64.b64decode(request["reference_data_base64"], validate=True)
        expected_ids = service._state["queried_ids"][:12 + max(0, request["round"]) * 6]
        seed_ids = [row["id"] for row in json.loads(service.public_manifest_path.read_text())["entries"] if row["phase"] == "seed"]
        service._validate_fit_dataset(training, expected_ids, "cumulative training")
        service._validate_fit_dataset(reference, seed_ids, "seed-only reference")
        if hashlib.sha256(training).hexdigest() != request.get("training_sha256"):
            raise TrialControlError("candidate training SHA differs from the bytes sent to the trusted fit worker")
        (inputs / "training.extxyz").write_bytes(training)
        (inputs / "reference.extxyz").write_bytes(reference)
        (inputs / "ace-small.yaml").write_bytes(service.template_bytes)
        command = ["python3", str(Path(__file__).resolve()), "worker", "train", "--dataset", "/inputs/training.extxyz",
                   "--reference-dataset", "/inputs/reference.extxyz", "--template", "/inputs/ace-small.yaml", "--out-dir", "/out",
                   "--seed", str(request["seed"]), "--maxiter", "32", "--timeout-seconds", "1800"]
        evidence = self._run(work, command, 1800)
        out = evidence.pop("output_dir")
        files = {name: (out / name).read_bytes() for name in ("potential.yace", "potential.yaml", "manifest.json", "timing.json", "train.log")}
        manifest = json.loads(files["manifest.json"])
        if (manifest.get("status") != "TRAINED" or manifest.get("training_sha256") != request.get("training_sha256")
                or manifest.get("seed") != request["seed"] or manifest.get("maxiter") != 32
                or manifest.get("template_sha256") != service.template_sha256):
            raise TrialControlError("native ACE fit manifest differs from fixed training/seed/iteration/template pins")
        model_sha = hashlib.sha256(files["potential.yace"]).hexdigest()
        manifest_sha = hashlib.sha256(files["manifest.json"]).hexdigest()
        receipt = {"schema": "case07-native-fit-execution/v1", **evidence,
                   "round": request["round"], "member": request["member"], "seed": request["seed"],
                   "training_sha256": request["training_sha256"], "template_sha256": manifest["template_sha256"],
                   "model_sha256": model_sha, "manifest_sha256": manifest_sha,
                   "timing_sha256": hashlib.sha256(files["timing.json"]).hexdigest()}
        receipt_sha = hashlib.sha256(_canonical_json(receipt)).hexdigest()
        receipt_path = work / "execution-receipt.json"
        _atomic_json(receipt_path, receipt)
        (self.private_dir / "models" / ident).mkdir(parents=True, mode=0o700)
        for name, raw in files.items(): (self.private_dir / "models" / ident / name).write_bytes(raw)
        return {"status": "FIT_COMPLETE", "model_sha256": model_sha, "manifest_sha256": manifest_sha,
                "execution_receipt_sha256": receipt_sha, "elapsed_seconds": evidence["elapsed_seconds"],
                "files_base64": {k: base64.b64encode(v).decode("ascii") for k, v in files.items()},
                "execution_receipt": receipt, "execution_receipt_relpath": str(receipt_path.relative_to(self.private_dir))}


    def predict_pool(self, round_no: int, member: int, service) -> dict:
        if round_no not in (1, 2) or member not in (1, 2, 3):
            raise TrialControlError("pool prediction request is outside the fixed two-round/three-member protocol")
        fit_round = round_no - 1
        slot = next((row for row in service._state["fit_slots"]
                     if row["round"] == fit_round and row["member"] == member), None)
        if slot is None:
            raise TrialControlError("pool prediction requires a completed trusted fit from the preceding stage")
        model_dir = self.private_dir / "models" / f"r{fit_round}-m{member}"
        model = model_dir / "potential.yace"
        manifest = model_dir / "manifest.json"
        if (hashlib.sha256(model.read_bytes()).hexdigest() != slot["model_sha256"]
                or hashlib.sha256(manifest.read_bytes()).hexdigest() != slot["manifest_sha256"]):
            raise TrialControlError("trusted model bytes changed since the fit receipt")
        geometry_manifest = json.loads((self.public_root / "geometry-manifest.json").read_text())
        entries = [row for row in geometry_manifest["entries"] if row["phase"] == "pool"]
        chunks = []
        for row in entries:
            source = (self.public_root / row["path"]).resolve(strict=True)
            if not source.is_relative_to(self.public_root):
                raise TrialControlError("pool input path escapes the frozen geometry root")
            source_bytes = source.read_bytes()
            if hashlib.sha256(source_bytes).hexdigest() != row.get("geometry_sha256"):
                raise TrialControlError("pool source bytes differ from the frozen public file SHA")
            chunks.append(source_bytes)
        pool = b"".join(chunks)
        work = self.private_dir / "workers" / f"predict-r{round_no}-m{member}"
        work.mkdir(parents=True, mode=0o700, exist_ok=False)
        inputs = work / "inputs"; inputs.mkdir(mode=0o700)
        (inputs / "potential.yace").write_bytes(model.read_bytes())
        (inputs / "manifest.json").write_bytes(manifest.read_bytes())
        (inputs / "pool.extxyz").write_bytes(pool)
        command = ["python3", str(Path(__file__).resolve()), "worker", "predict", "--model", "/inputs/potential.yace",
                   "--structures", "/inputs/pool.extxyz", "--output", "/out/predictions.json"]
        evidence = self._run(work, command, 600)
        result_path = evidence.pop("output_dir") / "predictions.json"
        raw = result_path.read_bytes(); result = json.loads(raw)
        if (result.get("status") != "PREDICTED" or result.get("model_sha256") != slot["model_sha256"]
                or result.get("structures_sha256") != hashlib.sha256(pool).hexdigest()
                or len(result.get("predictions", [])) != len(entries)):
            raise TrialControlError("native PyACE pool prediction failed its model/pool/frame bindings")
        try:
            from ase.io import read
            source_frames = read(str(work / "inputs" / "pool.extxyz"), index=":", format="extxyz")
        except Exception as exc:
            raise TrialControlError(f"trusted pool source frames could not be parsed: {exc}") from exc
        if len(source_frames) != len(entries):
            raise TrialControlError("trusted pool source-frame count differs from the frozen manifest")
        for index, (row, atoms, pred) in enumerate(zip(entries, source_frames, result["predictions"])):
            semantic_sha = geometry_digest(atoms)
            forces = pred.get("forces_eV_per_angstrom")
            if (pred.get("index") != index or pred.get("geometry_sha256") != semantic_sha
                    or pred.get("atom_count") != row["n_atoms"]
                    or len(atoms) != row["n_atoms"]
                    or not isinstance(forces, list) or len(forces) != len(atoms)
                    or any(not isinstance(vec, list) or len(vec) != 3
                           or any(type(value) not in (int, float) or not math.isfinite(value) for value in vec)
                           for vec in forces)):
                raise TrialControlError("native PyACE prediction geometry/order differs from the frozen pool source frames")
        receipt = {"schema": "case07-native-pool-prediction/v1", "round": round_no, "member": member,
                   "model_sha256": slot["model_sha256"], "pool_sha256": hashlib.sha256(pool).hexdigest(),
                   "predictions_sha256": hashlib.sha256(raw).hexdigest(), **evidence}
        receipt_sha = hashlib.sha256(_canonical_json(receipt)).hexdigest()
        signed = service._signed_receipt({**receipt, "receipt_sha256": receipt_sha})
        cache = self.private_dir / f"predictions-round-{round_no}-member-{member}.json"
        _atomic_json(cache, {"receipt": signed, "predictions": result})
        return {"status": "PREDICTED", "round": round_no, "member": member,
                "model_sha256": slot["model_sha256"], "pool_sha256": hashlib.sha256(pool).hexdigest(),
                "predictions": result["predictions"], "receipt_sha256": signed["receipt_sha256"]}



class LocalACEWorker:
    """Run only the fixed native backend under the dedicated worker UID."""
    def __init__(self, private_dir: Path, public_root: Path, runtime_sha256: str):
        self.private_dir=Path(private_dir).resolve(); self.public_root=Path(public_root).resolve()
        self.runtime_sha256=runtime_sha256

    def _run(self, work: Path, command: list[str], timeout: int, service=None) -> dict:
        import pwd, grp
        worker=pwd.getpwnam("case07worker")
        inputs=work/"inputs"; out=work/"out"
        out.mkdir(mode=0o700)
        os.chmod(self.private_dir.parent,0o711)
        os.chmod(self.private_dir,0o711)
        os.chown(work.parent,0,worker.pw_gid); os.chmod(work.parent,0o710)
        os.chown(work,0,worker.pw_gid); os.chmod(work,0o710)
        os.chown(inputs,0,worker.pw_gid); os.chmod(inputs,0o550)
        for item in inputs.iterdir():
            if item.is_symlink() or not item.is_file(): raise TrialControlError("unsafe native worker input")
            os.chown(item,0,worker.pw_gid); os.chmod(item,0o440)
        os.chown(out,worker.pw_uid,worker.pw_gid); os.chmod(out,0o700)
        if len(command)<4 or command[2]!="worker" or command[3] not in {"probe","train","predict"}:
            raise TrialControlError("trusted native worker command is not allowlisted")
        command=[str(sys.executable), "-B", "-I", str(Path(__file__).resolve()), "worker-launch", *command[3:]]
        start_utc=datetime.datetime.now(timezone.utc).isoformat(timespec="microseconds")
        start_ns=time.monotonic_ns(); log_path=work/"worker.log"
        timed_out=False; rc=None;budget_limited=False
        effective_timeout=float(timeout)
        clock_start=service.clock() if service is not None else time.monotonic()
        active_deadline=None
        if service is not None:
            if service._start_monotonic is None: raise TrialControlError("active runtime has not started")
            active_deadline=service._start_monotonic+service.LIMIT_SECONDS
            remaining=active_deadline-service.clock()
            if remaining<=0: raise TrialControlError("trial active-time limit reached before native worker start")
            budget_limited=remaining<=effective_timeout+2.0
            effective_timeout=min(effective_timeout,remaining)
        env={"PATH":"/opt/si-ox-runtime/bin:/usr/local/bin:/usr/bin:/bin","HOME":"/nonexistent","PYTHONDONTWRITEBYTECODE":"1","OMP_NUM_THREADS":"1","MKL_NUM_THREADS":"1","OPENBLAS_NUM_THREADS":"1","BLIS_NUM_THREADS":"1","LANG":"C.UTF-8","LC_ALL":"C.UTF-8"}
        with log_path.open("wb") as log:
            proc=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                                  cwd=work,env=env,start_new_session=True,close_fds=True)
            elapsed=max(0.0,(service.clock() if service is not None else time.monotonic())-clock_start)
            wait_for=max(0.0,effective_timeout-elapsed)
            if active_deadline is not None: wait_for=min(wait_for,max(0.0,active_deadline-service.clock()))
            try: rc=proc.wait(timeout=wait_for)
            except subprocess.TimeoutExpired:
                timed_out=True
                if budget_limited: os.killpg(proc.pid,signal.SIGKILL)
                else:
                    os.killpg(proc.pid,signal.SIGTERM)
                    try: proc.wait(timeout=2)
                    except subprocess.TimeoutExpired: os.killpg(proc.pid,signal.SIGKILL)
                proc.wait();rc=proc.returncode
        end_ns=time.monotonic_ns();end_utc=datetime.datetime.now(timezone.utc).isoformat(timespec="microseconds")
        raw_log=log_path.read_bytes();lines=raw_log.splitlines()
        prefix=b"CASE07_WORKER_LAUNCH: "
        if not lines or not lines[0].startswith(prefix): raise TrialControlError("isolated worker did not emit its trusted startup identity")
        launch=json.loads(lines[0][len(prefix):])
        if (launch.get("uid")!=worker.pw_uid or launch.get("gid")!=worker.pw_gid
                or launch.get("network_guard")!="libseccomp-deny-non-af-unix-socket-v1"
                or launch.get("denied_families")!=[2,10,17,16] or launch.get("af_unix_allowed") is not True
                or launch.get("no_new_privs") is not True or launch.get("seccomp_rule_api")!="seccomp_rule_add_array/SCMP_CMP_NE"):
            raise TrialControlError("isolated worker startup identity or seccomp evidence is invalid")
        start_ns=int(launch["started_monotonic_ns"]);start_utc=launch["started_at_utc"]
        return {"schema":RUNTIME_SCHEMA,"runtime_closure_sha256":self.runtime_sha256,
                "started_at_utc":start_utc,"ended_at_utc":end_utc,"started_monotonic_ns":start_ns,
                "ended_monotonic_ns":end_ns,"elapsed_seconds":(end_ns-start_ns)/1e9,
                "worker_uid":worker.pw_uid,"worker_gid":worker.pw_gid,"argv":command,
                "executable_sha256":hashlib.sha256(Path(command[0]).read_bytes()).hexdigest(),
                "exit_code":rc,"timed_out":timed_out,"network_guard":"libseccomp-deny-non-af-unix-socket-v1",
                "network_guard_probe":launch,
                "log_sha256":hashlib.sha256(raw_log).hexdigest(),"output_dir":out}

class NativeACEWorker(LocalACEWorker):
    def attest_selection(self, round_no: int, selection: dict, queried_ids: tuple[str, ...], service=None) -> list[str]:
        if round_no not in (1, 2):
            raise TrialControlError("trusted selection replay round is invalid")
        candidate = selection.get("selection")
        request = selection.get("request")
        bindings = selection.get("candidate_bindings")
        if not isinstance(candidate, dict) or not isinstance(request, dict):
            raise TrialControlError("selection attestation requires both the ranked artifact and query request")
        expected_models = [row["model_sha256"] for row in service._state["fit_slots"]
                           if row["round"] == round_no - 1]
        expected_training_ids = list(queried_ids[:12 + (round_no - 1) * 6])
        if (not isinstance(bindings, dict) or len(expected_models) != 3
                or candidate.get("model_sha256") != expected_models
                or bindings.get("committee_sha256") != candidate.get("committee_sha256")
                or bindings.get("training_ids") != expected_training_ids
                or not re.fullmatch(r"[0-9a-f]{64}", str(bindings.get("training_sha256", "")))
                or bindings.get("pool_sha256") != candidate.get("pool_sha256")):
            raise TrialControlError("candidate ranking is not bound to the trusted fitted committee")
        manifest = json.loads((self.public_root / "geometry-manifest.json").read_text())
        entries = [row for row in manifest["entries"] if row["phase"] == "pool"]
        predictions = []
        for member in (1, 2, 3):
            cache = self.private_dir / f"predictions-round-{round_no}-member-{member}.json"
            if not cache.is_file():
                raise TrialControlError("selection attestation requires all three trusted full-pool predictions")
            doc = json.loads(cache.read_text())
            if doc["predictions"].get("frame_count") != len(entries):
                raise TrialControlError("trusted pool prediction cache is incomplete")
            predictions.append(doc["predictions"]["predictions"])
        rows = []
        queried = set(queried_ids)
        for index, entry in enumerate(entries):
            force_sets = [pred[index]["forces_eV_per_angstrom"] for pred in predictions]
            flattened = [component for forces in force_sets for atom in forces for component in atom]
            if not flattened or any(type(x) not in (float, int) or not math.isfinite(x) for x in flattened):
                raise TrialControlError("trusted predictions contain malformed or non-finite forces")
            variances = []
            for atom_i in range(entry["n_atoms"]):
                for axis in range(3):
                    vals = [float(forces[atom_i][axis]) for forces in force_sets]
                    mean = sum(vals) / len(vals)
                    variances.append(sum((x - mean) ** 2 for x in vals) / (len(vals) - 1))
            score = math.sqrt(sum(variances) / len(variances))
            rows.append({"id": entry["id"], "domain": entry["domain"],
                         "geometry_sha256": entry["geometry_sha256"],
                         "force_disagreement_eV_per_A": score,
                         "eligible_for_selection": entry["id"] not in queried})
        rows.sort(key=lambda row: (row["domain"], -row["force_disagreement_eV_per_A"], row["id"]))
        selected = []
        for domain in sorted({row["domain"] for row in rows}):
            eligible = [row for row in rows if row["domain"] == domain and row["eligible_for_selection"]]
            if not eligible:
                raise TrialControlError("trusted full-pool replay has no eligible structure in a domain")
            selected.append(eligible[0])
        expected_pool_hashes = []
        for member in (1, 2, 3):
            cached = json.loads((self.private_dir / f"predictions-round-{round_no}-member-{member}.json").read_text())
            expected_pool_hashes.append(cached["receipt"]["pool_sha256"])
        if (candidate.get("round") != round_no or len(candidate.get("ranked", [])) != len(rows)
                or len(set(expected_pool_hashes)) != 1 or candidate.get("pool_sha256") != expected_pool_hashes[0]):
            raise TrialControlError("selection artifact round/pool identity differs from trusted predictions")
        expected_ids = [row["id"] for row in selected]
        if request.get("phase") != f"round-{round_no}" or request.get("ids") != expected_ids:
            raise TrialControlError("query request differs from the trusted per-domain force-disagreement ranking")
        got = candidate.get("ranked", [])
        for actual, expected in zip(got, rows):
            if (actual.get("id") != expected["id"] or actual.get("geometry_sha256") != expected["geometry_sha256"]
                    or bool(actual.get("eligible_for_selection")) != expected["eligible_for_selection"]
                    or not math.isclose(float(actual.get("force_disagreement_eV_per_A", float("nan"))),
                                        expected["force_disagreement_eV_per_A"], rel_tol=1e-8, abs_tol=1e-12)):
                raise TrialControlError("candidate ranking differs from trusted ACE full-pool replay")
        if not any(row["force_disagreement_eV_per_A"] > 1e-12 for row in rows if row["eligible_for_selection"]):
            raise TrialControlError("trusted ACE committee has zero eligible pool force disagreement")
        rank_path = self.private_dir / f"trusted-ranking-round-{round_no}.json"
        _atomic_json(rank_path, {"schema": "case07-trusted-force-ranking/v1", "round": round_no,
                                 "pool_sha256": json.loads((self.private_dir / f"predictions-round-{round_no}-member-1.json").read_text())["receipt"]["pool_sha256"],
                                 "rows": rows, "selected_ids": expected_ids})
        return expected_ids

    def fit(self, request: dict, service) -> dict:
        ident = f"r{request['round']}-m{request['member']}"
        work = self.private_dir / "workers" / ident
        work.mkdir(parents=True, mode=0o700, exist_ok=False)
        inputs = work / "inputs"
        out = work / "out"
        inputs.mkdir(mode=0o700)
        training = base64.b64decode(request["training_data_base64"], validate=True)
        reference = base64.b64decode(request["reference_data_base64"], validate=True)
        expected_ids = service._state["queried_ids"][:12 + max(0, request["round"]) * 6]
        seed_ids = [row["id"] for row in json.loads(service.public_manifest_path.read_text())["entries"] if row["phase"] == "seed"]
        service._validate_fit_dataset(training, expected_ids, "cumulative training")
        service._validate_fit_dataset(reference, seed_ids, "seed-only reference")
        if hashlib.sha256(training).hexdigest() != request.get("training_sha256"):
            raise TrialControlError("candidate training SHA differs from the bytes sent to the trusted fit worker")
        (inputs / "training.extxyz").write_bytes(training)
        (inputs / "reference.extxyz").write_bytes(reference)
        (inputs / "ace-small.yaml").write_bytes(service.template_bytes)
        command = [str(Path(sys.executable).resolve()), str(Path(__file__).resolve()), "worker", "train", "--dataset", str(inputs / "training.extxyz"),
                   "--reference-dataset", str(inputs / "reference.extxyz"), "--template", str(inputs / "ace-small.yaml"), "--out-dir", str(out),
                   "--seed", str(request["seed"]), "--maxiter", "32", "--timeout-seconds", "1800"]
        evidence = self._run(work, command, 1800, service=service)
        out = evidence.pop("output_dir")
        files = {name: (out / name).read_bytes() for name in ("potential.yace", "potential.yaml", "manifest.json", "timing.json", "train.log")}
        manifest = json.loads(files["manifest.json"])
        if (manifest.get("status") != "TRAINED" or manifest.get("training_sha256") != request.get("training_sha256")
                or manifest.get("seed") != request["seed"] or manifest.get("maxiter") != 32
                or manifest.get("template_sha256") != service.template_sha256):
            raise TrialControlError("native ACE fit manifest differs from fixed training/seed/iteration/template pins")
        model_sha = hashlib.sha256(files["potential.yace"]).hexdigest()
        manifest_sha = hashlib.sha256(files["manifest.json"]).hexdigest()
        receipt = {"schema": "case07-native-fit-execution/v1", **evidence,
                   "round": request["round"], "member": request["member"], "seed": request["seed"],
                   "training_sha256": request["training_sha256"], "template_sha256": manifest["template_sha256"],
                   "model_sha256": model_sha, "manifest_sha256": manifest_sha,
                   "timing_sha256": hashlib.sha256(files["timing.json"]).hexdigest(),
                   "trial_id": service.trial_id, "nonce": secrets.token_hex(16),
                   "backend": "ICAMS/python-ace PACEMAKER + pace_yaml2yace + PyACECalculator",
                   "source_runtime_sha256": self.runtime_sha256,
                   "native_yaml_sha256": hashlib.sha256(files["potential.yaml"]).hexdigest(),
                   "yace_sha256": model_sha,
                   "native_executables": {name:{"path":str(Path(shutil.which(name)).resolve()),"sha256":hashlib.sha256(Path(shutil.which(name)).read_bytes()).hexdigest()} for name in ("pacemaker","pace_yaml2yace") if shutil.which(name) is not None}}
        receipt_sha = hashlib.sha256(_canonical_json(receipt)).hexdigest()
        receipt_path = work / "execution-receipt.json"
        _atomic_json(receipt_path, receipt)
        (self.private_dir / "models" / ident).mkdir(parents=True, mode=0o700)
        for name, raw in files.items(): (self.private_dir / "models" / ident / name).write_bytes(raw)
        return {"status": "FIT_COMPLETE", "model_sha256": model_sha, "manifest_sha256": manifest_sha,
                "execution_receipt_sha256": receipt_sha, "elapsed_seconds": evidence["elapsed_seconds"],
                "files_base64": {k: base64.b64encode(v).decode("ascii") for k, v in files.items()},
                "execution_receipt": receipt, "execution_receipt_relpath": str(receipt_path.relative_to(self.private_dir))}

    def predict_pool(self, round_no: int, member: int, service) -> dict:
        if round_no not in (1, 2) or member not in (1, 2, 3):
            raise TrialControlError("pool prediction request is outside the fixed two-round/three-member protocol")
        fit_round = round_no - 1
        slot = next((row for row in service._state["fit_slots"]
                     if row["round"] == fit_round and row["member"] == member), None)
        if slot is None:
            raise TrialControlError("pool prediction requires a completed trusted fit from the preceding stage")
        model_dir = self.private_dir / "models" / f"r{fit_round}-m{member}"
        model = model_dir / "potential.yace"
        manifest = model_dir / "manifest.json"
        if (hashlib.sha256(model.read_bytes()).hexdigest() != slot["model_sha256"]
                or hashlib.sha256(manifest.read_bytes()).hexdigest() != slot["manifest_sha256"]):
            raise TrialControlError("trusted model bytes changed since the fit receipt")
        geometry_manifest = json.loads((self.public_root / "geometry-manifest.json").read_text())
        entries = [row for row in geometry_manifest["entries"] if row["phase"] == "pool"]
        chunks = []
        for row in entries:
            source = (self.public_root / row["path"]).resolve(strict=True)
            if not source.is_relative_to(self.public_root):
                raise TrialControlError("pool input path escapes the frozen geometry root")
            source_bytes = source.read_bytes()
            if hashlib.sha256(source_bytes).hexdigest() != row.get("geometry_sha256"):
                raise TrialControlError("pool source bytes differ from the frozen public file SHA")
            chunks.append(source_bytes)
        pool = b"".join(chunks)
        work = self.private_dir / "workers" / f"predict-r{round_no}-m{member}"
        work.mkdir(parents=True, mode=0o700, exist_ok=False)
        inputs = work / "inputs"; out = work / "out"; inputs.mkdir(mode=0o700)
        (inputs / "potential.yace").write_bytes(model.read_bytes())
        (inputs / "manifest.json").write_bytes(manifest.read_bytes())
        (inputs / "pool.extxyz").write_bytes(pool)
        command = [str(Path(sys.executable).resolve()), str(Path(__file__).resolve()), "worker", "predict", "--model", str(inputs / "potential.yace"),
                   "--structures", str(inputs / "pool.extxyz"), "--output", str(out / "predictions.json")]
        evidence = self._run(work, command, 600, service=service)
        result_path = evidence.pop("output_dir") / "predictions.json"
        raw = result_path.read_bytes(); result = json.loads(raw)
        if (result.get("status") != "PREDICTED" or result.get("model_sha256") != slot["model_sha256"]
                or result.get("structures_sha256") != hashlib.sha256(pool).hexdigest()
                or len(result.get("predictions", [])) != len(entries)):
            raise TrialControlError("native PyACE pool prediction failed its model/pool/frame bindings")
        try:
            from ase.io import read
            source_frames = read(str(work / "inputs" / "pool.extxyz"), index=":", format="extxyz")
        except Exception as exc:
            raise TrialControlError(f"trusted pool source frames could not be parsed: {exc}") from exc
        if len(source_frames) != len(entries):
            raise TrialControlError("trusted pool source-frame count differs from the frozen manifest")
        for index, (row, atoms, pred) in enumerate(zip(entries, source_frames, result["predictions"])):
            semantic_sha = geometry_digest(atoms)
            forces = pred.get("forces_eV_per_angstrom")
            if (pred.get("index") != index or pred.get("geometry_sha256") != semantic_sha
                    or pred.get("atom_count") != row["n_atoms"]
                    or len(atoms) != row["n_atoms"]
                    or not isinstance(forces, list) or len(forces) != len(atoms)
                    or any(not isinstance(vec, list) or len(vec) != 3
                           or any(type(value) not in (int, float) or not math.isfinite(value) for value in vec)
                           for vec in forces)):
                raise TrialControlError("native PyACE prediction geometry/order differs from the frozen pool source frames")
        receipt = {"schema": "case07-native-pool-prediction/v1", "round": round_no, "member": member,
                   "model_sha256": slot["model_sha256"], "pool_sha256": hashlib.sha256(pool).hexdigest(),
                   "predictions_sha256": hashlib.sha256(raw).hexdigest(), **evidence}
        receipt_sha = hashlib.sha256(_canonical_json(receipt)).hexdigest()
        signed = service._signed_receipt({**receipt, "receipt_sha256": receipt_sha})
        cache = self.private_dir / f"predictions-round-{round_no}-member-{member}.json"
        _atomic_json(cache, {"receipt": signed, "predictions": result})
        return {"status": "PREDICTED", "round": round_no, "member": member,
                "model_sha256": slot["model_sha256"], "pool_sha256": hashlib.sha256(pool).hexdigest(),
                "predictions": result["predictions"], "receipt_sha256": signed["receipt_sha256"]}



QUERY_SOCKET="/run/case07/query.sock"

def _recv_exact(conn, size):
    chunks=[]
    while size:
        block=conn.recv(size)
        if not block: raise EOFError("short UDS request")
        chunks.append(block);size-=len(block)
    return b"".join(chunks)

def _serve_request(service, conn):
    try:
        creds=conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize("3i"))
        pid,uid,gid=struct.unpack("3i",creds)
        if uid != 10001: raise TrialControlError("query peer UID is not the researcher")
        if service._collecting.is_set(): raise TrialControlError("trusted service is sealing")
        length=struct.unpack("!I",_recv_exact(conn,4))[0]
        if not 0 < length <= 256*1024*1024: raise TrialControlError("UDS request size is outside bounds")
        doc=json.loads(_recv_exact(conn,length))
        if not isinstance(doc,dict) or set(doc)!={"path","document"}: raise TrialControlError("malformed UDS request")
        reply={"peer_uid":uid,"peer_pid":pid,"broker_uid":os.getuid(),"broker_pid":os.getpid(),**service.dispatch(doc["path"],doc["document"])}
        raw=json.dumps(reply,separators=(",",":"),allow_nan=False).encode()
    except Exception as exc:
        raw=json.dumps({"error":str(exc)},separators=(",",":" )).encode()
    try: conn.sendall(struct.pack("!I",len(raw))+raw)
    finally: conn.close()

def _start_socket(service):
    path=Path(QUERY_SOCKET);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() or path.is_symlink(): raise TrialControlError("query socket path already exists")
    server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);server.bind(str(path))
    os.chown(path,0,10001);os.chmod(path,0o660);server.listen(32);server.settimeout(1.0)
    service._uds_server=server;service._uds_stopping=threading.Event()
    service._uds_client_threads=set();service._uds_clients_lock=threading.Lock()
    service._collecting=threading.Event()
    service._inflight_path=Path("/run/case07/inflight.json")
    def write_inflight():
        with service._uds_clients_lock:
            _atomic_json(service._inflight_path,{"inflight_requests":len(service._uds_client_threads)},0o600)
    write_inflight()
    def serve_and_forget(conn):
        try: _serve_request(service,conn)
        finally:
            with service._uds_clients_lock:
                service._uds_client_threads.discard(threading.current_thread())
                _atomic_json(service._inflight_path,{"inflight_requests":len(service._uds_client_threads)},0o600)
    def accept_loop():
        while not service._uds_stopping.is_set():
            try: conn,_=server.accept()
            except socket.timeout: continue
            except OSError: break
            thread=threading.Thread(target=serve_and_forget,args=(conn,),daemon=True)
            with service._uds_clients_lock:
                service._uds_client_threads.add(thread)
                _atomic_json(service._inflight_path,{"inflight_requests":len(service._uds_client_threads)},0o600)
            thread.start()
    service._uds_thread=threading.Thread(target=accept_loop,daemon=True,name="case07-native-query")
    service._uds_thread.start()
    return {"CASE07_QUERY_SOCKET":str(path),"CASE07_QUERY_CLIENT":"/usr/local/bin/case07-query"}

def _stop_socket(service):
    if getattr(service,"_uds_stopping",None): service._uds_stopping.set()
    if getattr(service,"_uds_server",None): service._uds_server.close();service._uds_server=None
    if getattr(service,"_uds_thread",None):
        service._uds_thread.join(timeout=5)
        if service._uds_thread.is_alive(): raise RuntimeError("trusted UDS accept loop did not stop")
    Path(QUERY_SOCKET).unlink(missing_ok=True)
    marker=Path("/run/case07/listener-stopped")
    marker.write_text("stopped\n");os.chmod(marker,0o440)

def _drain_socket_clients(service, timeout=60):
    deadline=time.monotonic()+timeout
    while True:
        with service._uds_clients_lock: threads=list(service._uds_client_threads)
        if not threads: return
        remaining=deadline-time.monotonic()
        if remaining<=0: raise RuntimeError("trusted broker still has in-flight requests after worker termination")
        for thread in threads: thread.join(timeout=min(.25,remaining))

TrialControlService.client_env=property(lambda self:{"CASE07_QUERY_SOCKET":QUERY_SOCKET,"CASE07_QUERY_CLIENT":"/usr/local/bin/case07-query"})
TrialControlService.start_socket=_start_socket
TrialControlService.stop_socket=_stop_socket

def _activate_local(self, runtime_sha256):
    with self._lock:
        if self._state["status"]!="CREATED" or self._start_monotonic is not None: raise TrialControlError("trial activation is permitted exactly once")
        if not re.fullmatch(r"[0-9a-f]{64}",runtime_sha256): raise TrialControlError("runtime closure SHA is invalid")
        self._start_monotonic=self.clock();started=datetime.datetime.now(timezone.utc).isoformat(timespec="seconds")
        base={"schema":"case07-local-agent-start/v1","trial_id":self.trial_id,"started_at_utc":started,
              "runtime_identity_kind":"python-runtime-closure","runtime_closure_sha256":runtime_sha256,
              "oracle_private_sha256":ORACLE_PRIVATE_SHA256,"geometry_manifest_sha256":hashlib.sha256(self.public_manifest_path.read_bytes()).hexdigest()}
        self.start_receipt=self._signed_receipt(base);_atomic_json(self.private_dir/"agent-start.json",self.start_receipt)
        self._state.update({"status":"READY","started_at_utc":started});self._persist()
TrialControlService.activate=_activate_local

def _terminate_uid(uid):
    for attempt in range(4):
        pids=[]
        for item in Path("/proc").iterdir():
            if not item.name.isdigit(): continue
            try:
                status=(item/"status").read_text()
                state=next(line.split()[1] for line in status.splitlines() if line.startswith("State:"))
                real_uid=int(next(line.split()[1] for line in status.splitlines() if line.startswith("Uid:")))
                if real_uid==uid and state!="Z": pids.append(int(item.name))
            except (FileNotFoundError,PermissionError,StopIteration,ValueError): pass
        if not pids: return True
        sig=signal.SIGTERM if attempt==0 else signal.SIGKILL
        for pid in pids:
            try: os.kill(pid,sig)
            except ProcessLookupError: pass
        time.sleep(.25 if sig==signal.SIGTERM else .1)
    return not any(True for _ in Path("/proc").iterdir() if _.name.isdigit() and _process_has_uid(_.name,uid))

def _process_has_uid(pid,uid):
    try:
        status=(Path("/proc")/pid/"status").read_text()
        state=next(line.split()[1] for line in status.splitlines() if line.startswith("State:"))
        real_uid=int(next(line.split()[1] for line in status.splitlines() if line.startswith("Uid:")))
        return real_uid==uid and state!="Z"
    except (FileNotFoundError,PermissionError,StopIteration,ValueError): return False

def run_agent():
    oracle=Path("/opt/case07/oracle-private.json");manifest=Path("/app/inputs/v2/geometry-manifest.json")
    runtime_sha=Path("/opt/case07/runtime-closure.sha256").read_text().strip()
    root=Path("/trusted/case07")
    if root.exists() and any(root.iterdir()): raise RuntimeError("trusted Task160 state is not fresh")
    root.mkdir(mode=0o711,parents=True,exist_ok=True);os.chown(root,0,0);os.chmod(root,0o711)
    service=TrialControlService(oracle,manifest,root)
    os.chmod(service.private_dir.parent,0o711);os.chmod(service.private_dir,0o711)
    worker=NativeACEWorker(service.private_dir,manifest.parent,runtime_sha)
    isolation_probe=probe_runtime(worker)
    software=software_identity()
    service._finalize_lock=threading.Lock();service._runtime_shutdown=threading.Event()
    service.fitter=worker.fit;service.predictor=worker.predict_pool
    service.attestor=lambda round_no,selection,queried:worker.attest_selection(round_no,selection,queried,service)
    def stop_accepting(_signum,_frame):
        service._collecting.set()
        service.stop_socket()
    def stop_and_seal(_signum,_frame):
        with service._finalize_lock:
            service._collecting.set()
            service.stop_socket()
            _terminate_uid(10001);_terminate_uid(10002)
            _drain_socket_clients(service,timeout=60)
            service.seal()
        raise SystemExit(0)
    signal.signal(signal.SIGUSR1,stop_accepting)
    signal.signal(signal.SIGTERM,stop_and_seal);signal.signal(signal.SIGINT,stop_and_seal)
    service.start_socket();service.activate(runtime_sha)
    Path("/run/case07/broker.pid").write_text(str(os.getpid())+"\n");os.chmod("/run/case07/broker.pid",0o440)
    ready=Path("/trusted/case07/runtime-closure.json")
    _atomic_json(ready,{"schema":"case07-local-runtime-closure/v1","runtime_closure_sha256":runtime_sha,
      "oracle_private_sha256":ORACLE_PRIVATE_SHA256,"uid_researcher":10001,"uid_worker":10002,
      "network_guard":"libseccomp-deny-non-af-unix-socket-v1","query_transport":"unix-socket-so-peercred",
      "network_isolation_probe":isolation_probe,"software_identity":software},0o400)
    def enforce_active_deadline():
        deadline=service._start_monotonic+service.LIMIT_SECONDS
        while not service._collecting.is_set():
            remaining=deadline-service.clock()
            if remaining<=0: break
            service._runtime_shutdown.wait(min(.25,remaining))
            if service._runtime_shutdown.is_set(): return
        if service._collecting.is_set(): return
        try:
            with service._finalize_lock:
                if service._collecting.is_set(): return
                service._collecting.set();service.stop_socket()
                if not _terminate_uid(10001) or not _terminate_uid(10002): raise RuntimeError("active deadline could not stop all untrusted processes")
                _drain_socket_clients(service,timeout=60)
                service.seal()
            service._runtime_shutdown.set()
        except Exception as exc:
            _atomic_json(Path("/trusted/case07/deadline-watchdog-error.json"),{"error_type":type(exc).__name__},0o400)
            os.kill(os.getpid(),signal.SIGTERM)
    threading.Thread(target=enforce_active_deadline,daemon=True,name="case07-active-deadline").start()
    service._runtime_shutdown.wait()

def software_identity():
    from importlib import metadata
    import numpy, ase, pyace
    from pyace.asecalc import PyACECalculator
    entries={}
    for name in ("pacemaker","pace_yaml2yace"):
        path=shutil.which(name)
        if not path or not Path(path).is_file(): raise RuntimeError(f"required native executable is missing: {name}")
        resolved=Path(path).resolve(strict=True)
        entries[name]={"path":str(resolved),"sha256":hashlib.sha256(resolved.read_bytes()).hexdigest()}
    module_path=Path(pyace.__file__).resolve(strict=True)
    return {"python":{"path":str(sys.executable),"sha256":hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),"version":sys.version.split()[0]},
            "numpy_version":numpy.__version__,"ase_version":ase.__version__,"pyace_version":metadata.version("pyace"),
            "pyace_module_sha256":hashlib.sha256(module_path.read_bytes()).hexdigest(),
            "backend":"ICAMS/python-ace PACEMAKER + pace_yaml2yace + PyACECalculator","native_executables":entries}

def probe_worker_entry():
    import socket as _socket
    import numpy as _np, ase as _ase, pyace as _pyace
    from pyace.asecalc import PyACECalculator as _PyACECalculator
    if sys.prefix != "/opt/si-ox-runtime" or sys.executable != "/opt/si-ox-runtime/bin/python":
        raise RuntimeError("native worker did not retain the pinned isolated Python venv")
    denied=[]
    for family in (_socket.AF_INET,_socket.AF_INET6,_socket.AF_PACKET,_socket.AF_NETLINK):
        try: _socket.socket(family,_socket.SOCK_STREAM)
        except PermissionError: denied.append(family)
        else: raise RuntimeError("non-UNIX socket escaped seccomp")
    local=_socket.socket(_socket.AF_UNIX,_socket.SOCK_STREAM);local.close()
    print(json.dumps({"uid":os.getuid(),"gid":os.getgid(),"python_prefix":sys.prefix,"python_executable":sys.executable,
      "numpy_version":_np.__version__,"ase_version":_ase.__version__,"pyace_version":__import__("importlib.metadata",fromlist=["version"]).version("pyace"),
      "pyace_calculator_imported":_PyACECalculator.__name__=="PyACECalculator",
      "network_guard":"libseccomp-deny-non-af-unix-socket-v1","denied_families":denied,"af_unix_allowed":True}))

def probe_runtime(worker):
    work=Path("/run/case07-worker/seccomp-probe")
    work.mkdir(mode=0o700,exist_ok=False);(work/"inputs").mkdir(mode=0o700)
    evidence=worker._run(work,[str(Path(sys.executable).resolve()),str(Path(__file__).resolve()),"worker","probe"],10)
    evidence["output_dir"]=str(evidence["output_dir"])
    lines=(work/"worker.log").read_text().splitlines()
    probe=json.loads(lines[-1]) if lines else {}
    if (evidence.get("exit_code")!=0 or evidence.get("worker_uid")!=10002
            or probe.get("uid")!=10002 or probe.get("network_guard")!="libseccomp-deny-non-af-unix-socket-v1"
            or probe.get("denied_families")!=[2,10,17,16] or probe.get("af_unix_allowed") is not True):
        raise RuntimeError("native worker isolation probe did not pass")
    evidence["worker_probe"]=probe
    return evidence

def _worker_launch(args):
    import pwd,ctypes,resource
    if not args or args[0] not in {"probe","train","predict"}: raise SystemExit("worker operation is not allowlisted")
    worker=pwd.getpwnam("case07worker")
    os.setgroups([]);os.setgid(worker.pw_gid);os.setuid(worker.pw_uid)
    libc=ctypes.CDLL(None,use_errno=True)
    libc.prctl.argtypes=[ctypes.c_int,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_ulong]
    libc.prctl.restype=ctypes.c_int
    if libc.prctl(38,1,0,0,0)!=0: raise OSError(ctypes.get_errno(),"PR_SET_NO_NEW_PRIVS")
    sec=ctypes.CDLL("libseccomp.so.2",use_errno=True)
    class ScmpArgCmp(ctypes.Structure):
        _fields_=[("arg",ctypes.c_uint),("op",ctypes.c_int),("datum_a",ctypes.c_uint64),("datum_b",ctypes.c_uint64)]
    sec.seccomp_init.argtypes=[ctypes.c_uint32];sec.seccomp_init.restype=ctypes.c_void_p
    sec.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p];sec.seccomp_syscall_resolve_name.restype=ctypes.c_int
    sec.seccomp_rule_add_array.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint,ctypes.POINTER(ScmpArgCmp)]
    sec.seccomp_rule_add_array.restype=ctypes.c_int
    sec.seccomp_load.argtypes=[ctypes.c_void_p];sec.seccomp_load.restype=ctypes.c_int
    sec.seccomp_release.argtypes=[ctypes.c_void_p];sec.seccomp_release.restype=None
    ctx=sec.seccomp_init(0x7fff0000)
    if not ctx: raise OSError(ctypes.get_errno(),"seccomp_init")
    syscall=sec.seccomp_syscall_resolve_name(b"socket")
    if syscall<0: sec.seccomp_release(ctx);raise OSError("socket syscall is unavailable")
    cmp=ScmpArgCmp(0,1,1,0)  # SCMP_CMP_NE; allow only AF_UNIX (1)
    rc=sec.seccomp_rule_add_array(ctx,0x00050000|errno.EPERM,syscall,1,ctypes.byref(cmp))
    if rc!=0: sec.seccomp_release(ctx);raise OSError(-rc,"seccomp socket-family rule")
    if sec.seccomp_load(ctx)!=0:
        err=ctypes.get_errno();sec.seccomp_release(ctx);raise OSError(err,"seccomp_load")
    sec.seccomp_release(ctx)
    resource.setrlimit(resource.RLIMIT_CPU,(3600,3600));resource.setrlimit(resource.RLIMIT_AS,(8*1024**3,8*1024**3))
    resource.setrlimit(resource.RLIMIT_NPROC,(64,64));resource.setrlimit(resource.RLIMIT_FSIZE,(8*1024**3,8*1024**3))
    import socket as _socket
    import numpy as _np, ase as _ase, pyace as _pyace
    from pyace.asecalc import PyACECalculator as _PyACECalculator
    if sys.prefix != "/opt/si-ox-runtime" or sys.executable != "/opt/si-ox-runtime/bin/python":
        raise RuntimeError("native worker did not retain the pinned isolated Python venv")
    denied=[]
    for family in (_socket.AF_INET,_socket.AF_INET6,_socket.AF_PACKET,_socket.AF_NETLINK):
        try: _socket.socket(family,_socket.SOCK_STREAM)
        except PermissionError: denied.append(family)
        else: raise RuntimeError("network socket denial probe unexpectedly succeeded")
    local=_socket.socket(_socket.AF_UNIX,_socket.SOCK_STREAM);local.close()
    launch={"uid":os.getuid(),"gid":os.getgid(),"network_guard":"libseccomp-deny-non-af-unix-socket-v1",
            "denied_families":denied,"af_unix_allowed":True,"started_at_utc":datetime.datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "started_monotonic_ns":time.monotonic_ns(),"no_new_privs":True,"seccomp_rule_api":"seccomp_rule_add_array/SCMP_CMP_NE"}
    os.write(1,b"CASE07_WORKER_LAUNCH: "+json.dumps(launch,separators=(",",":")).encode()+b"\n")
    exe=str(sys.executable);script=str(Path(__file__).resolve(strict=True))
    env={"PATH":"/opt/si-ox-runtime/bin:/usr/local/bin:/usr/bin:/bin","HOME":"/nonexistent","PYTHONDONTWRITEBYTECODE":"1",
         "OMP_NUM_THREADS":"1","MKL_NUM_THREADS":"1","OPENBLAS_NUM_THREADS":"1","BLIS_NUM_THREADS":"1","LANG":"C.UTF-8","LC_ALL":"C.UTF-8"}
    os.execve(exe,[exe,"-B","-I",script,"worker",*args],env)

def main():
    if len(sys.argv)>1 and sys.argv[1]=="worker-launch": _worker_launch(sys.argv[2:]);return 0
    if len(sys.argv)>1 and sys.argv[1]=="worker":
        args=sys.argv[2:]
        if args==["probe"]: probe_worker_entry();return 0
        sys.argv=[sys.argv[0],*args]
        raise SystemExit(_ace_worker_main() or 0)
    if len(sys.argv)>1 and sys.argv[1]=="serve": run_agent();return 0
    raise SystemExit("usage: runtime.py serve|worker-launch probe|train|predict|worker train|predict")
if __name__=="__main__": main()

PY_CASE07_RUNTIME
RUN cat > /opt/case07/entrypoint.py <<'PY_CASE07_ENTRY'
#!/usr/bin/env python3
import os,signal,sys,time,shutil,stat,subprocess,json,hashlib,threading
from pathlib import Path
R='/trusted/case07';B='/app/case07-artifacts/trusted'
def fail(msg): raise SystemExit('case07 entrypoint: '+msg)
def _uid_processes(uid):
    found=[]
    for item in Path('/proc').iterdir():
        if not item.name.isdigit(): continue
        try:
            status=(item/'status').read_text()
            state=next(line.split()[1] for line in status.splitlines() if line.startswith('State:'))
            real_uid=int(next(line.split()[1] for line in status.splitlines() if line.startswith('Uid:')))
            if real_uid==uid and state!='Z': found.append(int(item.name))
        except (FileNotFoundError,PermissionError,StopIteration,ValueError): pass
    return found

def _stop_uid(uid):
    for attempt in range(4):
        victims=_uid_processes(uid)
        if not victims: return
        sig=signal.SIGTERM if attempt==0 else signal.SIGKILL
        for pid in victims:
            try: os.kill(pid,sig)
            except ProcessLookupError: pass
        time.sleep(.25 if sig==signal.SIGTERM else .1)
    if _uid_processes(uid): fail('could not stop every researcher/worker process before collection')

def _copy_tree_nofollow(source,destination):
    source=Path(source);destination=Path(destination)
    st=source.lstat()
    if not stat.S_ISDIR(st.st_mode): fail('collect source is not a plain directory')
    destination.mkdir(mode=0o700)
    for item in source.iterdir():
        info=item.lstat();target=destination/item.name
        if stat.S_ISDIR(info.st_mode): _copy_tree_nofollow(item,target)
        elif stat.S_ISREG(info.st_mode): shutil.copyfile(item,target,follow_symlinks=False)
        else: fail('refusing symlink or special file in collected source')

def root_collect():
    pidfile=Path('/run/case07/broker.pid')
    if not pidfile.is_file(): fail('root broker PID receipt missing')
    pid=int(pidfile.read_text().strip())
    stopped=Path('/run/case07/listener-stopped')
    if Path(f'/proc/{pid}').exists():
        try: os.kill(pid,signal.SIGUSR1)  # close the UDS listener before killing clients
        except ProcessLookupError: pass
    listener_deadline=time.monotonic()+10
    while not stopped.is_file() and time.monotonic()<listener_deadline: time.sleep(.05)
    if not stopped.is_file(): fail('broker did not close its UDS listener before collection')
    if not Path(f'/proc/{pid}').exists():
        prior=Path(R+'/.case07-learning')
        if not prior.is_dir() or len(list(prior.glob('*/sealed-snapshot.json')))!=1:
            fail('broker exited without a valid deadline-sealed trial')
    _stop_uid(10001)
    drain_deadline=time.monotonic()+60
    inflight=Path('/run/case07/inflight.json')
    while time.monotonic()<drain_deadline:
        _stop_uid(10002)
        try: pending=int(json.loads(inflight.read_text())['inflight_requests'])
        except (FileNotFoundError,KeyError,ValueError,json.JSONDecodeError): pending=1
        if pending==0 and not _uid_processes(10001) and not _uid_processes(10002): break
        time.sleep(.1)
    else: fail('broker requests or worker processes did not drain before collection')
    try: os.kill(pid,signal.SIGTERM)
    except ProcessLookupError: pass
    deadline=time.monotonic()+75
    snapshot=Path(R+'/.case07-learning')
    while time.monotonic()<deadline:
        candidates=list(snapshot.glob('*/sealed-snapshot.json')) if snapshot.is_dir() else []
        if candidates:
            broker_alive=Path(f'/proc/{pid}').exists()
            if not broker_alive: break
        time.sleep(.1)
    else: fail('broker did not exit after draining requests and sealing')
    if len(candidates)!=1: fail('expected exactly one sealed Task160 trial')
    src=candidates[0].parent
    target=Path(B)
    if target.exists() and any(target.iterdir()): fail('refusing to overwrite prior collected bundle')
    target.mkdir(parents=True,exist_ok=True,mode=0o700)
    private=target/'private';_copy_tree_nofollow(src,private)
    app=target/'app';app.mkdir(mode=0o700)
    (app/'inputs').mkdir(mode=0o700)
    _copy_tree_nofollow('/app/inputs/v2',app/'inputs'/'v2')
    outputs=Path('/app/outputs')
    if outputs.exists(): _copy_tree_nofollow(outputs,app/'outputs')
    closure=Path(R+'/runtime-closure.json')
    if closure.is_file(): shutil.copyfile(closure,target/'runtime-closure.json',follow_symlinks=False)
    for base,dirs,files in os.walk(target,topdown=False,followlinks=False):
        for name in files:
            item=Path(base)/name
            if item.is_symlink() or not item.is_file(): fail('unsafe entry in collected bundle')
            os.chown(item,0,0);os.chmod(item,0o400)
        for name in dirs:
            item=Path(base)/name
            if item.is_symlink() or not item.is_dir(): fail('unsafe directory in collected bundle')
            os.chown(item,0,0);os.chmod(item,0o700)
    os.chown(target,0,0);os.chmod(target,0o700)
    print(json.dumps({'status':'SEALED','trial_id':json.loads((private/'sealed-snapshot.json').read_text())['trial_id'],'bundle':str(target)}))

def main():
    role=os.environ.get('CCB_CASE07_ROLE')
    if len(sys.argv)>1 and sys.argv[1]=='collect': root_collect();return
    if role=='verifier':
        if len(sys.argv)>1 and sys.argv[1]=='grade': os.execvp(sys.argv[2],sys.argv[2:])
        while True: time.sleep(60)
    if role!='agent': fail('missing or invalid Harbor role')
    Path('/trusted/case07').mkdir(parents=True,exist_ok=True,mode=0o711)
    os.chown('/trusted/case07',0,0);os.chmod('/trusted/case07',0o711)
    runtime=subprocess.Popen(['/opt/si-ox-runtime/bin/python','-B','-I','/opt/case07/runtime.py','serve'],stdin=subprocess.DEVNULL,stdout=open('/run/case07/broker.log','ab'),stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
    stop_requested=threading.Event()
    def request_stop(_signum,_frame): stop_requested.set()
    signal.signal(signal.SIGTERM,request_stop);signal.signal(signal.SIGINT,request_stop)
    socket=Path('/run/case07/query.sock')
    for _ in range(18000):
        if socket.exists(): break
        if runtime.poll() is not None: fail('native service exited during startup')
        if stop_requested.is_set():
            runtime.terminate();fail('container stop requested during native service startup')
        time.sleep(.05)
    else: runtime.terminate();fail('native service did not become ready')
    while True:
        code=runtime.poll()
        if stop_requested.is_set():
            if code is None:
                try: runtime.send_signal(signal.SIGTERM)
                except ProcessLookupError: pass
                try: runtime.wait(timeout=60)
                except subprocess.TimeoutExpired: runtime.kill();runtime.wait()
            return
        if code is not None:
            snapshot=Path('/trusted/case07/.case07-learning')
            sealed=list(snapshot.glob('*/sealed-snapshot.json')) if snapshot.is_dir() else []
            if code!=0 or not sealed or not Path('/run/case07/listener-stopped').is_file():
                fail('native service exited before a successful root collection seal')
            # Keep PID 1 alive while Harbor's native collect command freezes and returns the bundle.
            while not stop_requested.wait(1): pass
            return
        time.sleep(.1)
if __name__=='__main__': main()

PY_CASE07_ENTRY
RUN cat > /usr/local/bin/case07-query <<'PY_CASE07_QUERY'
#!/usr/bin/env python3
import argparse,base64,json,os,socket,struct,sys,hashlib
P=argparse.ArgumentParser();S=P.add_subparsers(dest='command',required=True)
S.add_parser('begin-run')
q=S.add_parser('query');q.add_argument('--request',required=True);q.add_argument('--output',required=True)
a=S.add_parser('attest-selection');a.add_argument('--round',type=int,required=True);a.add_argument('--selection',required=True);a.add_argument('--committee',required=True);a.add_argument('--training-data',required=True);a.add_argument('--training-ids',required=True);a.add_argument('--pool',required=True)
f=S.add_parser('fit-member')
for k in ('training-data','training-ids','reference-data','output-dir','round','member','seed'):f.add_argument('--'+k,required=True)
p=S.add_parser('predict');p.add_argument('--model',required=True);p.add_argument('--structures',required=True);p.add_argument('--output',required=True)
b=S.add_parser('budget-check');b.add_argument('--limit-active-seconds',type=int,required=True);b.add_argument('--receipt-out',required=True)
x=P.parse_args()
def call(path,doc):
 raw=json.dumps({'path':path,'document':doc},separators=(',',':')).encode();sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);sock.settimeout(1900 if path=='/fit-member' else 700);sock.connect(os.environ.get('CASE07_QUERY_SOCKET','/run/case07/query.sock'));sock.sendall(struct.pack('!I',len(raw))+raw);head=sock.recv(4)
 if len(head)!=4: raise SystemExit('ERROR: short trusted query response')
 size=struct.unpack('!I',head)[0];data=b''
 while len(data)<size:
  chunk=sock.recv(min(1024*1024,size-len(data)))
  if not chunk: raise SystemExit('ERROR: truncated trusted query response')
  data+=chunk
 result=json.loads(data)
 if 'error' in result: print(result['error'],file=sys.stderr);raise SystemExit(2)
 if result.get('peer_uid')!=10001 or result.get('broker_uid')!=0: raise SystemExit('ERROR: trusted broker identity is missing')
 return result
if x.command=='begin-run': print(json.dumps(call('/begin-run',{})['result']))
elif x.command=='query':
 doc=json.load(open(x.request));res=call('/query',doc);open(x.output,'wb').write(base64.b64decode(res['labels_base64']));print(json.dumps(res['result']))
elif x.command=='attest-selection':
 sel=json.load(open(x.selection));req=json.load(open(os.path.splitext(x.selection)[0]+'.request.json'));committee=open(x.committee,'rb').read();training=open(x.training_data,'rb').read();ids=[z.strip() for z in open(x.training_ids) if z.strip()];pool=open(x.pool,'rb').read();bindings={'committee_sha256':hashlib.sha256(committee).hexdigest(),'training_sha256':hashlib.sha256(training).hexdigest(),'training_ids':ids,'pool_sha256':hashlib.sha256(pool).hexdigest()};doc={'round':x.round,'selection':{'selected_ids':list(req.get('ids',[])),'selection':sel,'request':req,'candidate_bindings':bindings}};print(json.dumps(call('/attest-selection',doc)['result']))
elif x.command=='fit-member':
 training=open(x.training_data,'rb').read();reference=open(x.reference_data,'rb').read();ids=[z.strip() for z in open(x.training_ids) if z.strip()];doc={'round':int(x.round),'member':int(x.member),'seed':int(x.seed),'timeout_seconds':1800,'training_ids':ids,'training_sha256':hashlib.sha256(training).hexdigest(),'training_data_base64':base64.b64encode(training).decode(),'reference_data_base64':base64.b64encode(reference).decode()};result=call('/fit-member',doc)['result'];out=os.path.abspath(x.output_dir);os.makedirs(out,exist_ok=True);allowed={'potential.yace','potential.yaml','manifest.json','timing.json','train.log'}
 for name,value in result.get('files_base64',{}).items():
  if name not in allowed: raise SystemExit('ERROR: unexpected trusted fit filename')
  open(os.path.join(out,name),'wb').write(base64.b64decode(value,validate=True))
 open(os.path.join(out,'trusted-fit-receipt.json'),'w').write(json.dumps(result['trusted_fit_receipt'],indent=2)+'\n');print(json.dumps({'status':result.get('status'),'model_sha256':result.get('model_sha256'),'manifest_sha256':result.get('manifest_sha256')}))
elif x.command=='predict':
 model=open(x.model,'rb').read();pool=open(x.structures,'rb').read();msha=hashlib.sha256(model).hexdigest();psha=hashlib.sha256(pool).hexdigest();result=call('/predict-candidate-model',{'model_sha256':msha,'pool_sha256':psha})['result'];result.update({'model_sha256':msha,'model_path':x.model,'structures_sha256':psha,'structures_path':x.structures,'frame_count':len(result.get('predictions',[]))});open(x.output,'w').write(json.dumps(result,indent=2)+'\n');print(json.dumps({'status':result.get('status'),'receipt_sha256':result.get('receipt_sha256')}))
elif x.command=='budget-check':
 result=call('/budget-check',{})['result'];open(x.receipt_out,'w').write(json.dumps(result,indent=2)+'\n');print(json.dumps({'status':'BUDGET_RECORDED','receipt_sha256':result['receipt_sha256']}))

PY_CASE07_QUERY
RUN chmod 0444 /opt/case07/runtime.py /opt/case07/entrypoint.py \
    && chmod 0555 /usr/local/bin/case07-query \
    && sha256sum /opt/case07/runtime.py | awk '{print $1}' > /opt/case07/runtime-closure.sha256 \
    && chmod 0444 /opt/case07/runtime-closure.sha256

ENTRYPOINT ["/usr/bin/python3", "-B", "-I", "/opt/case07/entrypoint.py"]
