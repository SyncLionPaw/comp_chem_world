# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check native records, run evidence and their linkage where required by this task.
# L3 Science: benzophenone excited-state energies and carbonyl state character across methods.
"""Data-internal checks for benzophenone method and state evidence."""
from __future__ import annotations

import hashlib, json, math, os, re, sys
from pathlib import Path

try:
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    from pyscf import gto, hessian
    from pyscf.dft import libxc
    from pyscf.hessian import thermo
    from pyscf.data.nist import HARTREE2EV
    DEPENDENCY_ERROR = None
except ImportError as exc:
    np = None
    gto = None
    libxc = None
    linear_sum_assignment = None
    DEPENDENCY_ERROR = exc

INPUT_HASHES = json.loads((Path(__file__).resolve().parent / "refs.json").read_text(encoding="utf-8"))["inputs"]
ACCEPTANCE = json.loads((Path(__file__).resolve().parent / "refs.json").read_text(encoding="utf-8"))["acceptance"]

class EnvironmentError(RuntimeError):
    pass


def xc_fingerprint(label: str):
    """Canonical PySCF/libxc functional identity, independent of aliases."""
    try:
        hybrid, components = libxc.parse_xc(label)
    except Exception as exc:
        raise ValueError(f"cannot parse functional {label!r} with PySCF/libxc: {exc}") from exc
    hybrid = tuple(round(float(value), 12) for value in hybrid)
    merged = {}
    for functional_id, coefficient in components:
        key = int(functional_id)
        merged[key] = merged.get(key, 0.0) + float(coefficient)
    normalized = tuple((key, round(value, 12)) for key, value in sorted(merged.items())
                       if abs(value) > 1e-12)
    return hybrid, normalized


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"{path.name} missing or invalid: {exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return obj


def atoms_from_xyz(path: Path):
    lines = path.read_text(encoding="utf-8").splitlines()
    if int(lines[0]) != 24 or len(lines) != 26:
        raise ValueError("structure.xyz must contain exactly 24 atoms")
    atoms = []
    for line in lines[2:]:
        f = line.split()
        atoms.append((f[0], tuple(float(x) for x in f[1:4])))
    if sorted(x[0] for x in atoms) != sorted(["C"] * 13 + ["H"] * 10 + ["O"]):
        raise ValueError("structure.xyz formula is not C13H10O")
    if any(not math.isfinite(v) for _, xyz in atoms for v in xyz):
        raise ValueError("structure.xyz contains nonfinite coordinates")
    return atoms


def validate_benzophenone_graph(atoms):
    xyz = np.asarray([a[1] for a in atoms], dtype=float)
    symbols = [a[0] for a in atoms]
    graph = [set() for _ in symbols]
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            distance = float(np.linalg.norm(xyz[i] - xyz[j]))
            a, b = symbols[i], symbols[j]
            cutoff = {"C": {"C": 1.80, "O": 1.48, "H": 1.22},
                      "O": {"C": 1.48, "O": 0.0, "H": 0.0},
                      "H": {"C": 1.22, "O": 0.0, "H": 0.0}}[a][b]
            if cutoff and distance < cutoff:
                graph[i].add(j)
                graph[j].add(i)
    carbonyls = [i for i, s in enumerate(symbols) if s == "C" and
                 sum(symbols[j] == "O" for j in graph[i]) == 1]
    if len(carbonyls) != 1:
        raise ValueError("geometry must contain one carbonyl carbon bonded to oxygen")
    center = carbonyls[0]
    oxygens = [j for j in graph[center] if symbols[j] == "O"]
    if len(oxygens) != 1 or len(graph[oxygens[0]]) != 1 or len(graph[center]) != 3:
        raise ValueError("carbonyl connectivity is invalid")
    if not 1.15 <= np.linalg.norm(xyz[center] - xyz[oxygens[0]]) <= 1.40:
        raise ValueError("C=O bond length is inconsistent with benzophenone")
    carbon_neighbors = [j for j in graph[center] if symbols[j] == "C"]
    if len(carbon_neighbors) != 2:
        raise ValueError("carbonyl carbon must connect to two phenyl ipso carbons")
    ring_graph = {i: {j for j in graph[i] if symbols[j] == "C" and j != center}
                  for i, s in enumerate(symbols) if s == "C" and i != center}
    components = []
    unseen = set(ring_graph)
    while unseen:
        seed = unseen.pop()
        stack, comp = [seed], {seed}
        while stack:
            node = stack.pop()
            for nxt in ring_graph[node] & unseen:
                unseen.remove(nxt); comp.add(nxt); stack.append(nxt)
        components.append(comp)
    if len(components) != 2 or any(len(c) != 6 for c in components):
        raise ValueError("benzophenone geometry must contain two six-carbon phenyl rings")
    for ipso in carbon_neighbors:
        component = next((c for c in components if ipso in c), set())
        if not component or any(sum(j in component for j in ring_graph[i]) != 2 for i in component):
            raise ValueError("phenyl ring connectivity is not a six-membered cycle")
    return center, oxygens[0]


def check_inputs(app: Path):
    for name, digest in INPUT_HASHES.items():
        path = app / "inputs" / name
        if path.is_symlink() or not path.is_file() or sha(path) != digest:
            raise EnvironmentError(f"evaluation input missing or damaged: {name}")


def check_native_log(path: Path, require_scf: bool = True):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing native PySCF log: {path.name}")
    text = path.read_text(errors="replace")
    if require_scf and "converged SCF energy" not in text:
        raise ValueError(f"{path.name} lacks converged SCF evidence")
    summaries = []
    for line in text.splitlines():
        if line.startswith("NATIVE_QC_ROOT "):
            summaries.append(json.loads(line[len("NATIVE_QC_ROOT "):]))
    if len(summaries) != 6:
        raise ValueError(f"{path.name} must contain six machine-readable native root records")
    return summaries


def method_scf_log(method_log: Path, method_name: str, method: dict,
                   structure: Path, optimization: dict):
    """Validate SCF and grid evidence present in the method's own TD log."""
    text = method_log.read_text(errors="replace")
    if "converged SCF energy" not in text or not re.search(r"grids dens level:\s*(\d+)", text):
        raise ValueError(f"{method_name} TD log lacks its own converged SCF/grid evidence")
    if "converged SCF energy" not in text or "XC functionals =" not in text:
        raise ValueError("native SCF evidence lacks a converged PySCF functional calculation")
    if not re.search(rf"XC functionals =\s*{re.escape(method_name)}\b", text, re.IGNORECASE):
        raise ValueError("native SCF evidence functional does not match the TD method")
    basis_match = re.search(r"^basis = (.+)$", text, re.MULTILINE)
    grid_match = re.search(r"grids dens level:\s*(\d+)", text)
    energy_match = re.search(r"converged SCF energy\s*=\s*([-+0-9.eE]+)", text)
    if not basis_match or basis_match.group(1).strip() != method.get("basis") or not grid_match or not energy_match:
        raise ValueError("native SCF evidence lacks matching basis, grid, or converged energy")
    grid = int(grid_match.group(1))
    expected_grid = int(optimization.get("grid_level", -1))
    if grid != expected_grid:
        raise ValueError("native method SCF grid differs from the optimization/numerical protocol")
    density = method.get("density_fitting", {})
    if density.get("enabled"):
        auxbasis = re.search(r"^auxbasis = (.+)$", text, re.MULTILINE)
        if not auxbasis or auxbasis.group(1).strip() != density.get("auxbasis"):
            raise ValueError("native method SCF auxiliary basis differs from the method record")
    # PySCF's native input report provides the atom order and Angstrom geometry.
    input_atoms = []
    for line in text.splitlines():
        if not line.startswith("[INPUT]"):
            continue
        fields = line.replace("[INPUT]", "", 1).split()
        if len(fields) >= 6 and fields[0].isdigit() and re.fullmatch(r"[A-Z][a-z]?", fields[1]):
            input_atoms.append((fields[1], tuple(float(x) for x in fields[2:5])))
    if len(input_atoms) != 24:
        raise ValueError("native method SCF input does not report all 24 atoms")
    final_atoms = atoms_from_xyz(structure)
    if [a[0] for a in input_atoms] != [a[0] for a in final_atoms] or not np.allclose(
            np.asarray([a[1] for a in input_atoms]), np.asarray([a[1] for a in final_atoms]),
            rtol=0, atol=1e-9):
        raise ValueError("native method SCF input geometry differs from final structure.xyz")
    energy = float(energy_match.group(1))
    if not math.isclose(energy, float(method.get("ground_state_energy_hartree", math.nan)),
                        rel_tol=0, abs_tol=1e-6):
        raise ValueError("native method SCF energy disagrees with the method's TD ground-state energy")
    return grid


def normalize_result_report(report: dict, final: Path):
    """Expand concise scientific results to the legacy verifier's internal view.

    The native evidence remains mandatory. This adapter only fills fields that
    can be read or derived from the submission; it does not choose methods,
    roots, state mappings, or scientific interpretations.
    """
    if report.get("schema") == "organic-emitter-task147/v1":
        return report
    if "schema" not in report and (
            {"task_id", "molecule", "optimization", "frequency", "methods", "decision"} <= set(report)
            or (isinstance(report.get("methods"), list) and report["methods"]
                and isinstance(report["methods"][0], dict) and "method" in report["methods"][0])):
        return report
    if "schema" in report:
        raise ValueError("unsupported compact result.json schema")
    allowed_top = {"response_approximation", "engine_version", "functional_pair_rationale",
                   "methods", "comparison"}
    if set(report) - allowed_top:
        raise ValueError("compact result.json cannot mix in legacy or unknown top-level fields")
    methods_input = report.get("methods")
    if not isinstance(methods_input, list) or len(methods_input) != 2 or not all(
            isinstance(item, dict) and set(item) == {"functional", "singlet", "triplet"}
            for item in methods_input):
        raise ValueError("compact result.json requires exactly two functional records")
    for item in methods_input:
        name = item.get("functional")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError("method labels must be simple functional identifiers")
    declared_version = report.get("engine_version")
    if "engine_version" in report and (not isinstance(declared_version, str) or not declared_version.strip()):
        raise ValueError("engine_version, when supplied, must be a nonempty version string")
    native = final / "native"
    summary = read_json(native / "optimization_summary.json")
    with np.load(native / "normal_modes.npz") as modes:
        frequencies = np.asarray(modes["frequencies_cm1"], dtype=float)
        projections = np.asarray(modes["co_stretch_overlap_squared"], dtype=float)
    if frequencies.shape != (66,) or projections.shape != (66,):
        raise ValueError("native frequency and mode arrays are required for concise result normalization")
    response = report.get("response_approximation")
    if response not in ("full TDDFT", "TDA"):
        raise ValueError("result.json must declare one supported common response approximation")
    structure_path = final / "structure.xyz"
    if structure_path.is_symlink() or not structure_path.is_file():
        raise ValueError("final/structure.xyz is required for compact population normalization")
    atoms = atoms_from_xyz(structure_path)
    carbonyl_c, carbonyl_o = validate_benzophenone_graph(atoms)
    methods = []
    observed_versions = set()
    for entry in methods_input:
        name = entry.get("functional")
        if not isinstance(name, str) or not name:
            raise ValueError("each concise method record must identify its functional")
        log_path = native / f"{name.lower()}_tddft.log"
        if log_path.is_symlink() or not log_path.is_file():
            raise ValueError(f"missing native method log: {log_path.name}")
        text = log_path.read_text(errors="replace")
        version_match = re.search(r"PySCF(?:\s+version)?\s*[:=]?\s*v?([0-9]+(?:\.[0-9A-Za-z]+)+)", text, re.IGNORECASE)
        if version_match:
            observed_versions.add(version_match.group(1))
        basis_match = re.search(r"^basis = (.+)$", text, re.MULTILINE)
        grid_match = re.search(r"grids dens level:\s*(\d+)", text)
        energy_match = re.search(r"converged SCF energy\s*=\s*([-+0-9.eE]+)", text)
        if not basis_match or not grid_match or not energy_match:
            raise ValueError(f"{log_path.name} lacks native basis, grid, or converged SCF evidence")
        xc_match = re.search(r"^XC functionals =\s*(\S+)", text, re.MULTILINE)
        if not xc_match or xc_match.group(1).lower() != name.lower():
            raise ValueError(f"{log_path.name} does not verify the submitted functional")
        aux_match = re.search(r"^auxbasis = (.+)$", text, re.MULTILINE)
        density_fitting = {"enabled": bool(aux_match)}
        if aux_match:
            density_fitting["auxbasis"] = aux_match.group(1).strip()
        normalized = {
            "method": name, "basis": basis_match.group(1).strip(),
            "response_approximation": response, "engine": "PySCF",
            "engine_version": "",
            "scf_converged": "converged SCF energy" in text,
            "density_fitting": density_fitting,
            "ground_state_energy_hartree": float(energy_match.group(1)),
        }
        for spin in ("singlet", "triplet"):
            roots = entry.get(spin)
            required_root = {
                "excitation_energy_hartree", "oscillator_strength", "leading_nto_pair_weight",
                "hole_atom_mulliken", "particle_atom_mulliken",
            }
            if not isinstance(roots, list) or len(roots) != 3 or any(
                    not isinstance(root, dict)
                    or not required_root <= set(root) <= required_root | {"excitation_energy_eV"}
                    for root in roots):
                raise ValueError(f"concise {name} record must contain three complete {spin} root results")
            normalized[spin] = []
            for index, root in enumerate(roots, 1):
                hole = np.asarray(root["hole_atom_mulliken"], dtype=float)
                particle = np.asarray(root["particle_atom_mulliken"], dtype=float)
                if hole.shape != (24,) or particle.shape != (24,):
                    raise ValueError("compact Mulliken hole/particle vectors must contain 24 atom populations")
                energy_ev = (root["excitation_energy_eV"] if "excitation_energy_eV" in root
                             else float(root["excitation_energy_hartree"]) * HARTREE2EV)
                normalized[spin].append({
                    "root": index,
                    "excitation_energy_hartree": root["excitation_energy_hartree"],
                    "excitation_energy_eV": energy_ev,
                    "oscillator_strength": root["oscillator_strength"],
                    "leading_nto_pair_weight": root["leading_nto_pair_weight"],
                    "hole_atom_mulliken_population": root["hole_atom_mulliken"],
                    "particle_atom_mulliken_population": root["particle_atom_mulliken"],
                    "hole_oxygen_population": float(hole[carbonyl_o]),
                    "particle_carbonyl_group_population": float(particle[carbonyl_c] + particle[carbonyl_o]),
                })
        methods.append(normalized)
    if len(observed_versions) > 1:
        raise ValueError("native method logs report inconsistent PySCF versions")
    observed_version = next(iter(observed_versions), None)
    if observed_version and declared_version and declared_version != observed_version:
        raise ValueError("declared PySCF version disagrees with native method logs")
    version = observed_version or declared_version
    if not isinstance(version, str) or not version.strip():
        raise ValueError("declare the PySCF version once when it is not available in native logs")
    for item in methods:
        item["engine_version"] = version
    comparison = report.get("comparison")
    if not isinstance(comparison, dict) or set(comparison) != {"singlet", "triplet"} or any(
            not isinstance(comparison[spin], dict) or set(comparison[spin]) !=
            {"nto_similarity_3x3", "root_mapping"} for spin in ("singlet", "triplet")):
        raise ValueError("report one NTO similarity matrix and root mapping for each spin")
    sensitivity = {}
    for spin in ("singlet", "triplet"):
        item = comparison.get(spin, {})
        sensitivity.setdefault("leading_nto_orbital_pair_similarity_method1_to_method2", {})[spin] = {
            "matrix": item.get("nto_similarity_3x3"),
            "one_to_one_root_mapping": item.get("root_mapping"),
        }
        sensitivity.setdefault("root_energy_shifts_eV_method2_minus_method1", {})[spin] = [
            float(b["excitation_energy_eV"]) - float(a["excitation_energy_eV"])
            for a, b in zip(methods[0][spin], methods[1][spin])
        ]
    return {
        "schema": "organic-emitter-task147/v1", "task_id": "carbonyl-state-method",
        "molecule": {"formula": "C13H10O", "atom_count": 24, "charge": 0,
                     "multiplicity": 1, "connectivity": "O=C(c1ccccc1)c1ccccc1"},
        "optimization": {
            "functional": summary.get("functional"), "basis": summary.get("basis"),
            "scf_converged": summary.get("scf_converged"),
            "max_abs_gradient_hartree_per_bohr": summary.get("max_abs_gradient_hartree_per_bohr"),
        },
        "frequency": {
            "frequencies_cm-1": frequencies.tolist(),
            "imaginary_frequency_count": int(np.sum(frequencies < 0)),
            "hessian_shape": [24, 24, 3, 3], "hessian_units": "hartree/bohr^2",
            "selected_co_stretch_mode_index": int(np.argmax(projections)),
            "selected_co_stretch_overlap_squared": float(projections[np.argmax(projections)]),
        },
        "methods": methods,
        "decision": {
            "method_sensitivity": sensitivity,
            "absolute_isc_conclusion": "unsupported_without_spin_orbit_and_interstate_vibronic_couplings",
        },
    }


def grade(app: Path, final: Path):
    if DEPENDENCY_ERROR is not None:
        raise EnvironmentError(f"PySCF/NumPy/SciPy scorer dependencies unavailable: {DEPENDENCY_ERROR}")
    check_inputs(app)
    result = normalize_result_report(read_json(final / "result.json"), final)
    native = final / "native"
    structure = final / "structure.xyz"
    if structure.is_symlink() or not structure.is_file():
        raise ValueError("final/structure.xyz is required")
    atoms = atoms_from_xyz(structure)
    carbonyl_c, carbonyl_o = validate_benzophenone_graph(atoms)
    if result.get("task_id") != "carbonyl-state-method":
        raise ValueError("wrong task_id")
    if result.get("molecule") != {"formula": "C13H10O", "atom_count": 24, "charge": 0,
                                   "multiplicity": 1, "connectivity": "O=C(c1ccccc1)c1ccccc1"}:
        raise ValueError("molecule identity/charge/multiplicity mismatch")
    opt = result.get("optimization", {})
    opt_summary_path = native / "optimization_summary.json"
    opt_geometry_path = native / "optimized_geometry.xyz"
    frequency_log = native / "frequency.log"
    if any(p.is_symlink() or not p.is_file() for p in (opt_summary_path, opt_geometry_path, frequency_log)):
        raise ValueError("native optimization summary, geometry, and frequency log are required")
    opt_summary = read_json(opt_summary_path)
    if not opt_summary.get("scf_converged") or opt_summary.get("functional") != opt.get("functional") or opt_summary.get("basis") != opt.get("basis"):
        raise ValueError("native optimization summary does not match the reported level/convergence")
    native_atoms = atoms_from_xyz(opt_geometry_path)
    if [x[0] for x in native_atoms] != [x[0] for x in atoms] or not np.allclose(
            np.asarray([x[1] for x in native_atoms]), np.asarray([x[1] for x in atoms]), rtol=0, atol=1e-10):
        raise ValueError("native optimized geometry differs from final structure.xyz")
    ftext = frequency_log.read_text(errors="replace")
    if "converged SCF energy" not in ftext or "RKS" not in ftext:
        raise ValueError("native frequency log lacks converged RKS evidence")
    if opt_summary.get("accepted_attempt") is None:
        raise ValueError("native optimization summary lacks its accepted optimization attempt")
    opt_attempt = native / str(opt_summary["accepted_attempt"])
    eval_artifacts = sorted(opt_attempt.glob("evaluation_*.npz"))
    if not eval_artifacts:
        raise ValueError("native optimization evaluation arrays are required to verify stationarity")
    final_coords = np.asarray([xyz for _, xyz in atoms], dtype=float)
    closest = None
    for artifact in eval_artifacts:
        if artifact.is_symlink():
            continue
        with np.load(artifact) as data:
            coords = np.asarray(data["coordinates_angstrom"], dtype=float)
            grad = np.asarray(data["gradient_hartree_per_bohr"], dtype=float).reshape(-1)
            energy = float(np.asarray(data["energy_hartree"]).reshape(-1)[0])
        distance = float(np.max(np.abs(coords - final_coords))) if coords.shape == final_coords.shape else math.inf
        if closest is None or distance < closest[0]:
            closest = (distance, grad, energy)
    if closest is None or closest[0] > 1e-8 or closest[1].size != 72 or not np.isfinite(closest[1]).all():
        raise ValueError("no native optimization gradient matches the reported optimized geometry")
    final_gradient_path = native / "final_gradient.npz"
    if final_gradient_path.is_symlink() or not final_gradient_path.is_file():
        raise ValueError("canonical native final_gradient.npz is required")
    with np.load(final_gradient_path) as data:
        canonical_coords = np.asarray(data["coordinates_angstrom"], dtype=float)
        canonical_gradient = np.asarray(data["gradient_hartree_per_bohr"], dtype=float).reshape(-1)
        canonical_energy = float(np.asarray(data["energy_hartree"]).reshape(-1)[0])
    if not np.allclose(canonical_coords, final_coords, rtol=0, atol=1e-8) or not np.allclose(
            canonical_gradient, closest[1], rtol=1e-10, atol=1e-12) or not math.isclose(
            canonical_energy, closest[2], rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("canonical final gradient differs from its native optimizer evaluation")
    eval_max_gradient = float(np.max(np.abs(closest[1])))
    eval_rms_gradient = float(np.sqrt(np.mean(closest[1] ** 2)))
    gtol = float(opt_summary.get("gtol_hartree_per_bohr", math.nan))
    stationarity_limit = ACCEPTANCE["max_abs_gradient_hartree_per_bohr"]
    if not math.isfinite(gtol) or gtol <= 0 or eval_max_gradient > stationarity_limit:
        raise ValueError("native optimizer gradient exceeds the task's fixed 1e-4 Eh/bohr stationarity limit")
    if not math.isclose(eval_max_gradient, float(opt_summary["max_abs_gradient_hartree_per_bohr"]), rel_tol=2e-6, abs_tol=2e-9) or not math.isclose(
            eval_rms_gradient, float(opt_summary["rms_gradient_hartree_per_bohr"]), rel_tol=2e-6, abs_tol=2e-9):
        raise ValueError("optimization gradient summary disagrees with native evaluation array")
    frequency_gradient_path = native / "final_frequency_gradient.npz"
    frequency_gradient_log = native / "final_frequency_gradient.log"
    if frequency_gradient_path.is_symlink() or not frequency_gradient_path.is_file() or frequency_gradient_log.is_symlink() or not frequency_gradient_log.is_file():
        raise ValueError("independent final-frequency gradient recheck is required")
    frequency_gradient_text = frequency_gradient_log.read_text(errors="replace")
    if "converged SCF energy" not in frequency_gradient_text or "Gradients" not in frequency_gradient_text:
        raise ValueError("final-frequency gradient log lacks native converged SCF/gradient evidence")
    with np.load(frequency_gradient_path) as data:
        freq_coords = np.asarray(data["coordinates_angstrom"], dtype=float)
        freq_gradient = np.asarray(data["gradient_hartree_per_bohr"], dtype=float).reshape(-1)
        freq_energy = float(np.asarray(data["energy_hartree"]).reshape(-1)[0])
    if not np.allclose(freq_coords, final_coords, rtol=0, atol=1e-8) or freq_gradient.size != 72 or not np.isfinite(freq_gradient).all():
        raise ValueError("independent final-frequency gradient does not match the optimized geometry")
    freq_max = float(np.max(np.abs(freq_gradient)))
    freq_rms = float(np.sqrt(np.mean(freq_gradient ** 2)))
    if freq_max > stationarity_limit or not math.isclose(
            freq_max, float(opt_summary.get("frequency_recheck_max_abs_gradient_hartree_per_bohr", math.nan)),
            rel_tol=2e-6, abs_tol=2e-9) or not math.isclose(
            freq_rms, float(opt_summary.get("frequency_recheck_rms_gradient_hartree_per_bohr", math.nan)),
            rel_tol=2e-6, abs_tol=2e-9) or not math.isclose(
            freq_energy, float(opt_summary.get("frequency_recheck_energy_hartree", math.nan)),
            rel_tol=1e-10, abs_tol=1e-8):
        raise ValueError("independent final-frequency gradient recheck is nonstationary or disagrees with its summary")
    if not math.isclose(closest[2], float(opt_summary["final_energy_hartree"]), rel_tol=1e-10, abs_tol=1e-9):
        raise ValueError("final optimizer energy disagrees with native evaluation array")
    if not isinstance(opt.get("basis"), str) or not opt.get("basis") or not isinstance(
            opt.get("functional"), str) or not opt.get("functional") or not opt.get("scf_converged"):
        raise ValueError("optimization method or SCF convergence evidence missing")
    if float(opt.get("max_abs_gradient_hartree_per_bohr", math.inf)) > ACCEPTANCE["max_abs_gradient_hartree_per_bohr"]:
        raise ValueError("optimized geometry is not stationary at the recorded criterion")
    freq = result.get("frequency", {})
    if int(freq.get("imaginary_frequency_count", -1)) != 0:
        raise ValueError("ground-state Hessian does not attest a minimum")
    modes_path = native / "normal_modes.npz"
    hess_path = native / "cartesian_hessian_hartree_per_bohr2.npy"
    if not modes_path.is_file() or not hess_path.is_file():
        raise ValueError("native Hessian and normal modes are required")
    if freq.get("hessian_shape") != [24, 24, 3, 3] or freq.get("hessian_units") != "hartree/bohr^2":
        raise ValueError("reported Hessian shape or units mismatch")
    hess = np.load(hess_path)
    if hess.shape != (24, 24, 3, 3) or not np.isfinite(hess).all():
        raise ValueError("native Cartesian Hessian is malformed")
    hess_transpose = hess.transpose(1, 0, 3, 2)
    hess_symmetric = 0.5 * (hess + hess_transpose)
    hess_antisymmetric = hess - hess_transpose
    hess_scale = float(np.max(np.abs(hess_symmetric)))
    max_antisymmetry_ratio = float(np.max(np.abs(hess_antisymmetric)) / max(hess_scale, np.finfo(float).tiny))
    fro_antisymmetry_ratio = float(np.linalg.norm(hess_antisymmetric) /
                                    max(np.linalg.norm(hess_symmetric), np.finfo(float).tiny))
    if max_antisymmetry_ratio > ACCEPTANCE["max_entry_antisymmetry_ratio"] or fro_antisymmetry_ratio > ACCEPTANCE["frobenius_antisymmetry_ratio"]:
        raise ValueError("native Hessian violates the documented relative Cartesian symmetry error protocol")
    with np.load(modes_path) as modes:
        frequencies = np.asarray(modes["frequencies_cm1"], dtype=float)
        co_projection = np.asarray(modes["co_stretch_overlap_squared"], dtype=float)
        mass_weighted_modes = np.asarray(modes["mass_weighted_modes"], dtype=float)
        if frequencies.size != 66 or not np.isfinite(frequencies).all() or np.min(frequencies) <= 0:
            raise ValueError("native vibrational spectrum is incomplete or unstable")
        if not np.allclose(frequencies, freq.get("frequencies_cm-1", []), rtol=2e-7, atol=1e-5):
            raise ValueError("reported frequencies disagree with native normal_modes.npz")
        selected_index = int(freq.get("selected_co_stretch_mode_index", -1))
        selected_overlap = float(freq.get("selected_co_stretch_overlap_squared", math.nan))
        if co_projection.shape != (66,) or not np.isfinite(co_projection).all() or selected_index != int(np.argmax(co_projection)) or not math.isclose(
                selected_overlap, float(co_projection[selected_index]), rel_tol=1e-8, abs_tol=1e-10):
            raise ValueError("reported selected C=O stretch mode does not match native projection evidence")
    if mass_weighted_modes.shape != (66, 24, 3) or not np.isfinite(mass_weighted_modes).all():
        raise ValueError("native mass-weighted normal-mode array has invalid shape or values")
    if not np.allclose(canonical_coords, np.asarray([x for _, x in atoms]), rtol=0, atol=ACCEPTANCE["geometry_match_angstrom"]):
        raise ValueError("canonical optimizer coordinates differ from structure.xyz by more than 1e-9 Angstrom")
    # Either exact optimizer coordinates or serialized XYZ may have generated
    # the reported modes. Validate one source as a whole to avoid combining
    # frequencies from one geometry with projections/eigenvectors from another.
    mode_routes = []
    symbols = [s for s, _ in atoms]
    for route_name, route_coords in (("canonical optimizer coordinates", canonical_coords),
                                     ("serialized structure coordinates", np.asarray([x for _, x in atoms]))):
        route_mol = gto.M(atom=[(s, tuple(x)) for s, x in zip(symbols, route_coords)], basis=opt["basis"],
                          unit="Angstrom", charge=0, spin=0, symmetry=False, verbose=0)
        masses = np.asarray(route_mol.atom_mass_list(isotope_avg=True), dtype=float)
        ha = thermo.harmonic_analysis(route_mol, hess, exclude_trans=True,
                                      exclude_rot=True, imaginary_freq=True)
        independent_freq_complex = np.asarray(ha["freq_wavenumber"])
        independent_freq = independent_freq_complex.real - np.abs(independent_freq_complex.imag)
        sym_ha = thermo.harmonic_analysis(route_mol, hess_symmetric,
                                          exclude_trans=True, exclude_rot=True,
                                          imaginary_freq=True)
        sym_freq_complex = np.asarray(sym_ha["freq_wavenumber"])
        sym_freq = sym_freq_complex.real - np.abs(sym_freq_complex.imag)
        eigenvectors = np.asarray(ha["norm_mode"], dtype=float) * np.sqrt(masses)[None, :, None]
        eigenvectors /= np.linalg.norm(eigenvectors.reshape((len(eigenvectors), -1)), axis=1)[:, None, None]
        axis = route_coords[carbonyl_o] - route_coords[carbonyl_c]
        axis /= np.linalg.norm(axis)
        stretch = np.zeros((24, 3), dtype=float)
        stretch[carbonyl_c] = -axis / math.sqrt(masses[carbonyl_c])
        stretch[carbonyl_o] = axis / math.sqrt(masses[carbonyl_o])
        stretch /= np.linalg.norm(stretch)
        independent_projection = (eigenvectors.reshape((66, -1)) @ stretch.reshape(-1)) ** 2
        selected_eigenvector_overlap = np.abs(
            np.sum(eigenvectors * mass_weighted_modes, axis=(1, 2)))
        route_passes = (
            int(ha["freq_error"]) == 0 and int(sym_ha["freq_error"]) == 0
            and independent_freq.shape == (66,) and np.isfinite(independent_freq).all()
            and np.isfinite(sym_freq).all() and np.max(np.abs(sym_freq - independent_freq)) <= ACCEPTANCE["max_frequency_spectrum_delta_cm-1"]
            and np.allclose(independent_freq, frequencies, rtol=0, atol=ACCEPTANCE["frequency_match_cm-1"])
            and np.allclose(independent_freq, np.asarray(freq["frequencies_cm-1"], dtype=float), rtol=0, atol=ACCEPTANCE["frequency_match_cm-1"])
            and selected_index == int(np.argmax(independent_projection))
            and np.allclose(independent_projection, co_projection, rtol=2e-7, atol=2e-9)
            and selected_eigenvector_overlap[selected_index] >= 1.0 - 1e-7
        )
        if route_passes:
            mode_routes.append(route_name)
    if not mode_routes:
        raise ValueError("neither complete optimizer-coordinate source reproduces the submitted Hessian mode evidence")
    methods = result.get("methods")
    if not isinstance(methods, list) or len(methods) != 2:
        raise ValueError("exactly two electronic-structure methods are required")
    method_names = [m["method"] for m in methods]
    if any(not re.fullmatch(r"[A-Za-z0-9_-]+", str(name)) for name in method_names):
        raise ValueError("method labels must be simple functional identifiers")
    if xc_fingerprint(str(method_names[0])) == xc_fingerprint(str(method_names[1])):
        raise ValueError("the two labels resolve to the same PySCF/libxc functional; choose distinct functionals, not aliases")
    method_basis = [m.get("basis") for m in methods]
    if any(not isinstance(x, str) or not x for x in method_basis) or method_basis[0] != method_basis[1]:
        raise ValueError("the two method comparison records must use and report the same basis")
    if any(m.get("response_approximation") != methods[0].get("response_approximation") for m in methods):
        raise ValueError("the two methods must use the same response approximation")
    comparison_mol = gto.M(atom=[(s, tuple(x)) for s, x in atoms], basis=method_basis[0],
                           unit="Angstrom", charge=0, spin=0, symmetry=False, verbose=0)
    ao_overlap = np.asarray(comparison_mol.intor("int1e_ovlp"), dtype=float)
    ao_slices = comparison_mol.aoslice_by_atom()
    mol_results = {}
    nto_data = {}
    method_grids = []
    for method in methods:
        name = method["method"].lower()
        if method.get("engine") != "PySCF" or not isinstance(method.get("engine_version"), str) or not method.get("engine_version"):
            raise ValueError("method engine/version metadata mismatch")
        if not isinstance(method.get("response_approximation"), str) or not method["response_approximation"]:
            raise ValueError("response approximation must be stated")
        method_log = native / f"{name}_tddft.log"
        native_roots = check_native_log(method_log, require_scf=False)
        method_grids.append(method_scf_log(method_log, method["method"], method,
                                           structure, opt_summary))
        if not method.get("scf_converged"):
            raise ValueError(f"{name} ground-state SCF is not converged")
        mol_results[name] = {}
        native_lookup = {(r["spin"], int(r["root"])): r for r in native_roots}
        for spin in ("singlet", "triplet"):
            rows = method.get(spin)
            if not isinstance(rows, list) or len(rows) != 3:
                raise ValueError(f"{name} must contain three {spin} roots")
            energies = []
            for index, row in enumerate(rows, 1):
                e = float(row["excitation_energy_eV"])
                if row.get("root") != index or not math.isfinite(e) or e <= 0:
                    raise ValueError("root numbering/energy invalid")
                if not math.isfinite(float(row["oscillator_strength"])):
                    raise ValueError("oscillator strength missing/nonfinite")
                native_row = native_lookup[(spin, index)]
                if native_row.get("method") != method["method"] or any(
                        not math.isclose(float(native_row[field]), float(row[field]), rel_tol=2e-8, abs_tol=2e-9)
                        for field in ("excitation_energy_hartree", "excitation_energy_eV", "oscillator_strength")):
                    raise ValueError("submitted TDDFT roots disagree with the native PySCF root records")
                if spin == "triplet" and abs(float(row["oscillator_strength"])) > 1e-10:
                    raise ValueError("spin-forbidden TDDFT triplet oscillator strengths should be zero")
                nto_file = native / f"{name}_{spin}_root{index}_nto.npz"
                if nto_file.is_symlink() or not nto_file.is_file():
                    raise ValueError(f"missing native NTO coefficients for {name} {spin} root {index}")
                with np.load(nto_file) as data:
                    coeff = np.asarray(data["coefficients"], dtype=float)
                    overlap = np.asarray(data["overlap"], dtype=float)
                    weight = float(np.asarray(data["weights"]).reshape(-1)[0])
                    native_energy = float(np.asarray(data["excitation_energy_hartree"]).reshape(-1)[0])
                    native_oscillator = float(np.asarray(data["oscillator_strength"]).reshape(-1)[0])
                    mo_coeff = np.asarray(data["mo_coeff"], dtype=float)
                    mo_occ = np.asarray(data["mo_occ"], dtype=float)
                    td_x = np.asarray(data["td_x"], dtype=float)
                    td_y = np.asarray(data["td_y"], dtype=float)
                if not math.isclose(native_energy * HARTREE2EV, e, rel_tol=2e-8, abs_tol=2e-8) or not math.isclose(
                        native_oscillator, float(row["oscillator_strength"]), rel_tol=2e-8, abs_tol=2e-9):
                    raise ValueError("submitted root values disagree with native NPZ data")
                nto_data[(name, spin, index)] = (coeff, overlap)
                nao = int(comparison_mol.nao_nr())
                if coeff.shape != (nao, nao) or overlap.shape != (nao, nao) or not 0 <= weight <= 1:
                    raise ValueError("NTO coefficient artifact has invalid dimensions/weight")
                if mo_coeff.ndim != 2 or mo_coeff.shape[0] != nao or mo_occ.shape != (mo_coeff.shape[1],):
                    raise ValueError("native MO dimensions are inconsistent with the declared structure/basis")
                occupied, virtual = np.isclose(mo_occ, 2.0), np.isclose(mo_occ, 0.0)
                if not np.all(occupied | virtual) or int(round(float(mo_occ.sum()))) != comparison_mol.nelectron:
                    raise ValueError("native MO occupations disagree with molecular electron count")
                if td_x.shape != (int(occupied.sum()), int(virtual.sum())) or td_y.shape != td_x.shape or not np.isfinite(td_x).all() or not np.isfinite(td_y).all():
                    raise ValueError("native TD amplitudes have invalid shape or values")
                if not np.allclose(mo_coeff.T @ ao_overlap @ mo_coeff, np.eye(mo_coeff.shape[1]),
                                   rtol=2e-6, atol=2e-7):
                    raise ValueError("native molecular orbitals are not AO-overlap orthonormal")
                if not np.allclose(overlap, ao_overlap, rtol=2e-8, atol=2e-9):
                    raise ValueError("saved NTO AO overlap differs from the structure/basis integral")
                if not np.isclose(coeff[:, 0] @ ao_overlap @ coeff[:, 0], 1.0, rtol=2e-6, atol=2e-7) or not np.isclose(
                        coeff[:, comparison_mol.nelectron // 2] @ ao_overlap @ coeff[:, comparison_mol.nelectron // 2],
                        1.0, rtol=2e-6, atol=2e-7):
                    raise ValueError("native leading NTO hole/particle is not normalized in AO overlap metric")
                if not math.isclose(weight, float(row["leading_nto_pair_weight"]), rel_tol=2e-7, abs_tol=2e-9):
                    raise ValueError("reported NTO pair weight differs from native coefficient file")
                nocc = comparison_mol.nelectron // 2
                for column, field in ((0, "hole_atom_mulliken_population"),
                                      (nocc, "particle_atom_mulliken_population")):
                    pop = np.asarray(row[field], dtype=float)
                    if pop.shape != (24,) or not np.isfinite(pop).all() or not math.isclose(float(pop.sum()), 1.0, abs_tol=2e-5):
                        raise ValueError(f"invalid {field}; populations are AO-overlap gross values")
                    vector = coeff[:, column]
                    gross = vector * (ao_overlap @ vector)
                    recomputed = np.asarray([gross[int(a):int(b)].sum() for a, b in ao_slices[:, 2:4]])
                    if not np.allclose(pop, recomputed, rtol=2e-7, atol=2e-8):
                        raise ValueError(f"{field} disagrees with AO-overlap Mulliken populations recomputed from the native NTO")
                    if field == "hole_atom_mulliken_population" and not math.isclose(
                            float(row["hole_oxygen_population"]), float(recomputed[carbonyl_o]),
                            rel_tol=2e-7, abs_tol=2e-8):
                        raise ValueError("oxygen-hole descriptor disagrees with native NTO populations")
                    if field == "particle_atom_mulliken_population" and not math.isclose(
                            float(row["particle_carbonyl_group_population"]),
                            float(recomputed[carbonyl_c] + recomputed[carbonyl_o]),
                            rel_tol=2e-7, abs_tol=2e-8):
                        raise ValueError("carbonyl-particle descriptor disagrees with native NTO populations")
                energies.append(e)
            if energies != sorted(energies):
                raise ValueError(f"{name} {spin} roots are not energy ordered")
            mol_results[name][spin] = rows
    shifts = result.get("decision", {}).get("method_sensitivity", {}).get("root_energy_shifts_eV_method2_minus_method1")
    if len(set(method_grids)) != 1:
        raise ValueError("the two methods must use the same DFT quadrature grid")
    density_fitting = [m.get("density_fitting", {}) for m in methods]
    if density_fitting[0] != density_fitting[1]:
        raise ValueError("the two methods must use the same density-fitting settings")
    if not isinstance(shifts, dict):
        raise ValueError("numeric method sensitivity evidence missing")
    for spin in ("singlet", "triplet"):
        expected = [float(p["excitation_energy_eV"] - b["excitation_energy_eV"])
                    for b, p in zip(mol_results[method_names[0].lower()][spin], mol_results[method_names[1].lower()][spin])]
        if not np.allclose(np.asarray(shifts.get(spin, []), dtype=float), expected, rtol=1e-9, atol=1e-10):
            raise ValueError("method sensitivity shifts disagree with reported roots")
        matrix = np.zeros((3, 3), dtype=float)
        for bi in (1, 2, 3):
            bcoeff, overlap = nto_data[(method_names[0].lower(), spin, bi)]
            for pi in (1, 2, 3):
                pcoeff, _ = nto_data[(method_names[1].lower(), spin, pi)]
                hole = abs(float(bcoeff[:, 0] @ overlap @ pcoeff[:, 0]))
                nocc = comparison_mol.nelectron // 2
                particle = abs(float(bcoeff[:, nocc] @ overlap @ pcoeff[:, nocc]))
                matrix[bi - 1, pi - 1] = min(1.0, max(0.0, hole * particle))
        sim_key = "leading_nto_orbital_pair_similarity_method1_to_method2"
        sim = result["decision"]["method_sensitivity"].get(sim_key, {}).get(spin, {})
        if not np.allclose(np.asarray(sim.get("matrix"), dtype=float), matrix, rtol=1e-8, atol=1e-9):
            raise ValueError("method-pair NTO similarity matrix disagrees with native orbitals")
        br, pr = linear_sum_assignment(-matrix)
        mapping = {str(int(i) + 1): int(j) + 1 for i, j in zip(br, pr)}
        if sim.get("one_to_one_root_mapping") != mapping:
            raise ValueError("method-pair NTO root mapping is inconsistent")
    if result.get("decision", {}).get("absolute_isc_conclusion") != "unsupported_without_spin_orbit_and_interstate_vibronic_couplings":
        raise ValueError("unsupported absolute ISC inference must be stated")
    return {"status": "PASS", "reward": 1.0, "exit_code": 0,
            "detail": "Structure, native Hessian/frequencies, six TDDFT root sets, NTO consistency and method shifts passed data-internal checks."}


if __name__ == "__main__":
    app = Path(os.environ.get("APP", "/app"))
    log = Path(os.environ.get("LOGS", "/logs/verifier"))
    log.mkdir(parents=True, exist_ok=True)
    try:
        result = grade(app, app / "final")
    except EnvironmentError as exc:
        result = {"status": "ENV_INVALID", "reward": None, "exit_code": 2, "detail": str(exc)}
    except Exception as exc:
        result = {"status": "FAIL", "reward": 0.0, "exit_code": 1, "detail": str(exc)}
    (log / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    if result["reward"] is not None:
        (log / "reward.txt").write_text(f"{result['reward']}\n")
    elif (log / "reward.txt").exists():
        (log / "reward.txt").unlink()
    print(json.dumps(result))
    raise SystemExit(result["exit_code"])
