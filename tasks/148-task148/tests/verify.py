# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check native records, run evidence and their linkage where required by this task.
# L3 Science: convergence of a mode-projected excitation-energy derivative with state tracking.
"""Data-internal checks for the mode, displacements and state tracking."""
from __future__ import annotations

import csv, hashlib, json, math, os, re
from pathlib import Path

try:
    import numpy as np
    from pyscf import gto, hessian
    from pyscf.hessian import thermo
    from pyscf.data.nist import BOHR, HARTREE2EV
    from scipy.optimize import linear_sum_assignment
    DEPENDENCY_ERROR = None
except ImportError as exc:
    np = None
    gto = hessian = linear_sum_assignment = None
    DEPENDENCY_ERROR = exc

INPUT_HASHES = json.loads((Path(__file__).resolve().parent / "refs.json").read_text(encoding="utf-8"))["inputs"]
ACCEPTANCE = json.loads((Path(__file__).resolve().parent / "refs.json").read_text(encoding="utf-8"))["acceptance"]

class EnvironmentError(RuntimeError):
    pass


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"{path.name} must be an object")
    return obj


def read_xyz(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    if int(lines[0]) != 24 or len(lines) != 26:
        raise ValueError(f"invalid 24-atom XYZ: {path.name}")
    atoms = []
    for line in lines[2:]:
        f = line.split()
        atoms.append((f[0], np.asarray([float(x) for x in f[1:4]], dtype=float)))
    return atoms


def validate_benzophenone_graph(atoms):
    coords = np.asarray([x for _, x in atoms])
    symbols = [s for s, _ in atoms]
    graph = [set() for _ in symbols]
    cutoffs = {"C": {"C": 1.80, "O": 1.48, "H": 1.22},
               "O": {"C": 1.48, "O": 0.0, "H": 0.0},
               "H": {"C": 1.22, "O": 0.0, "H": 0.0}}
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            cutoff = cutoffs[symbols[i]][symbols[j]]
            if cutoff and np.linalg.norm(coords[i] - coords[j]) < cutoff:
                graph[i].add(j); graph[j].add(i)
    carbonyl = [i for i, s in enumerate(symbols) if s == "C" and
                sum(symbols[j] == "O" for j in graph[i]) == 1]
    if len(carbonyl) != 1:
        raise ValueError("geometry does not contain one carbonyl carbon")
    c = carbonyl[0]
    oxygen = next(j for j in graph[c] if symbols[j] == "O")
    phenyl = [j for j in graph[c] if symbols[j] == "C"]
    if len(phenyl) != 2 or len(graph[c]) != 3 or len(graph[oxygen]) != 1 or not 1.15 <= np.linalg.norm(
            coords[c] - coords[oxygen]) <= 1.40:
        raise ValueError("carbonyl connectivity or C=O bond length is invalid")
    ring_graph = {i: {j for j in graph[i] if symbols[j] == "C" and j != c}
                  for i, s in enumerate(symbols) if s == "C" and i != c}
    unseen = set(ring_graph)
    components = []
    while unseen:
        seed = unseen.pop(); stack = [seed]; comp = {seed}
        while stack:
            i = stack.pop()
            for j in ring_graph[i] & unseen:
                unseen.remove(j); comp.add(j); stack.append(j)
        components.append(comp)
    if len(components) != 2 or any(len(comp) != 6 for comp in components):
        raise ValueError("benzophenone must contain two six-carbon rings")
    for ipso in phenyl:
        comp = next((x for x in components if ipso in x), set())
        if not comp or any(sum(j in comp for j in ring_graph[i]) != 2 for i in comp):
            raise ValueError("phenyl ring is not a six-membered cycle")
    return c, oxygen


def load_native_root(path, root):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing native TDDFT root artifact: {path.name}")
    with np.load(path) as data:
        item = {k: np.asarray(data[k]).copy() for k in data.files}
    for key in ("td_x", "td_y", "mo_coeff", "mo_occ", "excitation_energy_hartree", "oscillator_strength", "response_approximation"):
        if key not in item:
            raise ValueError(f"native root artifact lacks {key}: {path.name}")
    energy = float(item["excitation_energy_hartree"].reshape(-1)[0])
    f = float(item["oscillator_strength"].reshape(-1)[0])
    if not math.isfinite(energy) or energy <= 0 or not math.isfinite(f):
        raise ValueError(f"invalid native root values: {path.name}")
    return item


def validate_native_orbitals(item, mol, path):
    coeff = np.asarray(item["mo_coeff"], dtype=float)
    occ = np.asarray(item["mo_occ"], dtype=float)
    x = np.asarray(item["td_x"], dtype=float)
    y = np.asarray(item["td_y"], dtype=float)
    if y.ndim == 0 and float(y) == 0.0:
        y = np.zeros_like(x)
        item["td_y"] = y
    if coeff.ndim != 2 or coeff.shape[0] != mol.nao_nr() or occ.shape != (coeff.shape[1],):
        raise ValueError(f"invalid native MO dimensions: {Path(path).name}")
    occupied = np.isclose(occ, 2.0)
    virtual = np.isclose(occ, 0.0)
    if not np.all(occupied | virtual) or int(round(float(occ.sum()))) != mol.nelectron:
        raise ValueError(f"native MO occupations disagree with molecular electron count: {Path(path).name}")
    if x.shape != (int(np.count_nonzero(occupied)), int(np.count_nonzero(virtual))) or not np.isfinite(x).all() or y.shape != x.shape or not np.isfinite(y).all():
        raise ValueError(f"native TD X-amplitude dimensions are invalid: {Path(path).name}")
    overlap = np.asarray(mol.intor("int1e_ovlp"), dtype=float)
    metric = coeff.T @ overlap @ coeff
    if not np.allclose(metric, np.eye(coeff.shape[1]), rtol=2e-6, atol=2e-7):
        raise ValueError(f"native molecular orbitals are not AO-overlap orthonormal: {Path(path).name}")


def transition_overlap_proxy(left, right, mol_left, mol_right):
    occ_left = left["mo_occ"] == 2
    vir_left = left["mo_occ"] == 0
    occ_right = right["mo_occ"] == 2
    vir_right = right["mo_occ"] == 0
    mo_left, mo_right = left["mo_coeff"], right["mo_coeff"]
    t_left = mo_left[:, occ_left] @ left["td_x"] @ mo_left[:, vir_left].T
    t_right = mo_right[:, occ_right] @ right["td_x"] @ mo_right[:, vir_right].T
    cross = np.asarray(gto.intor_cross("int1e_ovlp_sph", mol_left, mol_right), dtype=float)
    s_left = np.asarray(mol_left.intor("int1e_ovlp"), dtype=float)
    s_right = np.asarray(mol_right.intor("int1e_ovlp"), dtype=float)
    numerator = float(np.trace(t_left.T @ cross @ t_right @ cross.T))
    norm_left = float(np.trace(t_left.T @ s_left @ t_left @ s_left))
    norm_right = float(np.trace(t_right.T @ s_right @ t_right @ s_right))
    if norm_left <= 0 or norm_right <= 0:
        raise ValueError("native transition density has nonpositive norm")
    return max(-1.0, min(1.0, numerator / math.sqrt(norm_left * norm_right)))


def native_log_roots(path, expected_response=None, expected_functional=None, expected_basis=None,
                     expected_grid=None, expected_density_fitting=None):
    if not path.is_file():
        raise ValueError(f"missing TDDFT log: {path.name}")
    text = path.read_text(errors="replace")
    if "converged SCF energy" not in text:
        raise ValueError(f"{path.name} lacks converged SCF evidence")
    roots = []
    for line in text.splitlines():
        if line.startswith("NATIVE_QC_ROOT "):
            roots.append(json.loads(line[len("NATIVE_QC_ROOT "):]))
    if len(roots) != 6:
        raise ValueError(f"{path.name} lacks six native TDDFT root summaries")
    if expected_functional is not None and any(x.get("method", "").casefold() != str(
            expected_functional).casefold() for x in roots):
        raise ValueError(f"{path.name} native root method labels disagree with the selected functional")
    basis_match = re.search(r"^basis = (.+)$", text, re.MULTILINE)
    if expected_basis is not None and basis_match and basis_match.group(1).strip() != expected_basis:
        raise ValueError(f"{path.name} native basis disagrees with the selected route")
    if expected_functional is not None and not re.search(
            rf"XC functionals =\s*{re.escape(str(expected_functional))}\b", text, re.IGNORECASE):
        raise ValueError(f"{path.name} native SCF functional disagrees with root labels")
    grid_match = re.search(r"grids dens level:\s*(\d+)", text)
    if expected_grid is not None and (not grid_match or int(grid_match.group(1)) != int(expected_grid)):
        raise ValueError(f"{path.name} native numerical grid disagrees with the selected route")
    if expected_density_fitting is not None:
        density = expected_density_fitting
        aux_match = re.search(r"^auxbasis = (.+)$", text, re.MULTILINE)
        if density.get("enabled") and (not aux_match or aux_match.group(1).strip() != density.get("auxbasis")):
            raise ValueError(f"{path.name} native auxiliary basis disagrees with the selected route")
        if not density.get("enabled") and aux_match:
            raise ValueError(f"{path.name} native log uses density fitting absent from the selected route")
    if expected_response is not None:
        if any(x.get("response_approximation") != expected_response for x in roots):
            raise ValueError(f"{path.name} root response metadata disagrees with the selected route")
        for x in roots:
            if expected_response == "TDA" and x.get("response_approximation") != "TDA":
                raise ValueError(f"{path.name} does not attest TDA roots")
    return {(x["spin"], int(x["root"])): x for x in roots}


def _validate_operator_derivative_binding(source_marker, result, expected_file):
    if source_marker.get("derivatives_file") != expected_file or result.get("derivatives_file") != expected_file:
        raise ValueError("operator source marker/result must bind the selected derivative file")


def verify_offdiag_operator(final, native, atoms, mode, reference_native, ref_mol, derivatives_source_file="derivatives.json"):
    if derivatives_source_file not in ("derivatives.json", "derivatives.csv"):
        raise ValueError("unsupported derivative source file")
    result_path = final / "s0_s1_offdiag_operator.json"
    evidence_path = native / "s0_s1_offdiag_operator_evidence.npz"
    log_path = native / "s0_s1_offdiag_operator.log"
    if any(p.is_symlink() or not p.is_file() for p in (result_path, evidence_path, log_path)):
        raise ValueError("off-diagonal S0-S1 operator approximation JSON, native arrays and PySCF log are required")
    result = read_json(result_path)
    if result.get("status") != "computed_linear_response_operator_approximation" or result.get("target") != "S0-S1 off-diagonal nuclear-attraction derivative operator projection":
        raise ValueError("off-diagonal S0-S1 operator must identify the scoped LR S0-S1 approximation")
    response_approximation = mode.get("response_approximation")
    if response_approximation not in ("full TDDFT", "TDA"):
        raise ValueError("mode.json must declare a supported full-TDDFT or TDA response approximation")
    if result.get("functional") != mode.get("functional") or result.get("basis") != mode.get("basis") or result.get("response_approximation") != response_approximation:
        raise ValueError("off-diagonal S0-S1 operator electronic settings do not match the task reference route")
    if result.get("density_fitting") != mode.get("optimization", {}).get("density_fitting"):
        raise ValueError("off-diagonal S0-S1 operator density-fitting approximation differs from the mode calculation")
    if int(result.get("grid_level", -1)) != int(mode.get("optimization", {}).get("grid_level", -2)):
        raise ValueError("off-diagonal S0-S1 operator quadrature grid differs from the independent optimization/reference route")
    if result.get("quantity_type") != "off_diagonal_electronic_nuclear_attraction_derivative_operator_projection" or result.get("approximation_kind") != "single_reference_linear_response_one_electron_transition_density" or result.get("literature_equivalence") is not False or result.get("triplet_generalization") is not False:
        raise ValueError("off-diagonal S0-S1 operator quantity and approximation scope are not explicitly identified")
    with np.load(evidence_path) as archive:
        data = {key: np.asarray(archive[key]).copy() for key in archive.files}
    coords_bohr = np.asarray(ref_mol.atom_coords(), dtype=float)
    charges = np.asarray(ref_mol.atom_charges(), dtype=float)
    masses = np.asarray(ref_mol.atom_mass_list(isotope_avg=True), dtype=float)
    symbols = [s for s, _ in atoms]
    if not np.allclose(data["coordinates_bohr"], coords_bohr, rtol=0, atol=1e-9) or not np.array_equal(data["atom_charges"], charges) or not np.allclose(data["masses_amu"], masses, rtol=1e-12, atol=1e-12):
        raise ValueError("off-diagonal S0-S1 operator native coordinates, nuclear charges or masses do not match the molecular input")
    expected_mode = np.asarray(mode["mass_weighted_eigenvector"], dtype=float).reshape((24, 3))
    expected_mode *= int(np.asarray(data["mode_phase_sign"]).reshape(-1)[0])
    if not np.allclose(data["mass_weighted_mode"], expected_mode, rtol=1e-10, atol=1e-12):
        raise ValueError("off-diagonal S0-S1 operator native mode vector differs from the Hessian-selected mode/phase")
    mo = np.asarray(data["mo_coeff"], dtype=float)
    occ = np.asarray(data["mo_occ"], dtype=float)
    x = np.asarray(data["raw_td_x"], dtype=float)
    y = np.asarray(data["raw_td_y"], dtype=float)
    mode_sign = int(np.asarray(data["mode_phase_sign"]).reshape(-1)[0])
    state_sign = int(np.asarray(data["state_phase_sign"]).reshape(-1)[0])
    if mo.ndim != 2 or mo.shape[0] != ref_mol.nao_nr() or occ.shape != (mo.shape[1],):
        raise ValueError("off-diagonal S0-S1 operator native molecular orbital dimensions are invalid")
    occupied, virtual = np.isclose(occ, 2.0), np.isclose(occ, 0.0)
    if not np.all(occupied | virtual) or int(round(float(occ.sum()))) != ref_mol.nelectron:
        raise ValueError("off-diagonal S0-S1 operator MO occupations disagree with molecular electron count")
    overlap = np.asarray(ref_mol.intor("int1e_ovlp"), dtype=float)
    if not np.allclose(mo.T @ overlap @ mo, np.eye(mo.shape[1]), rtol=2e-6, atol=2e-7):
        raise ValueError("off-diagonal S0-S1 operator MOs are not AO-overlap orthonormal")
    if x.shape != y.shape or x.shape != (int(occupied.sum()), int(virtual.sum())):
        raise ValueError("off-diagonal S0-S1 operator X/Y response amplitudes have invalid dimensions")
    if response_approximation == "TDA" and not np.allclose(y, 0.0, rtol=0, atol=1e-14):
        raise ValueError("TDA off-diagonal S0-S1 operator evidence must contain zero Y amplitudes")
    if not math.isclose(float(result.get("td_eigenvector_x2_minus_y2_norm", math.nan)),
                        2.0 * (float(np.sum(x*x)) - float(np.sum(y*y))), rel_tol=1e-9, abs_tol=1e-10) or not math.isclose(
            float(result["td_eigenvector_x2_minus_y2_norm"]), 1.0, rel_tol=2e-6, abs_tol=2e-7):
        raise ValueError("off-diagonal S0-S1 operator TDDFT eigenvector does not satisfy the PySCF X²−Y² normalization")
    cocc, cvir = mo[:, occupied], mo[:, virtual]
    unphased_transition = cocc @ (x + y) @ cvir.T
    phase_idx = np.unravel_index(int(np.argmax(np.abs(unphased_transition))), unphased_transition.shape)
    expected_state_sign = 1 if unphased_transition[phase_idx] >= 0 else -1
    if state_sign != expected_state_sign or not np.allclose(
            data["phase_aligned_td_x"], state_sign * x, rtol=1e-12, atol=1e-12) or not np.allclose(
            data["phase_aligned_td_y"], state_sign * y, rtol=1e-12, atol=1e-12):
        raise ValueError("off-diagonal S0-S1 operator electronic-state phase sign does not follow the AO transition-density convention")
    transition = state_sign * unphased_transition
    if not np.allclose(transition, data["ao_transition_density"], rtol=2e-8, atol=2e-9):
        raise ValueError("saved off-diagonal S0-S1 operator AO transition density differs from the raw LR amplitudes")
    mw = np.asarray(mode["mass_weighted_eigenvector"], dtype=float).reshape((24, 3))
    if mode_sign not in (-1, 1) or state_sign not in (-1, 1):
        raise ValueError("off-diagonal S0-S1 operator phase signs must be +/-1")
    mw *= mode_sign
    c, o = validate_benzophenone_graph(atoms)
    coords_ang = np.asarray([xyz for _, xyz in atoms], dtype=float)
    axis = coords_ang[o] - coords_ang[c]
    axis /= np.linalg.norm(axis)
    stretch = np.zeros((24, 3), dtype=float)
    stretch[c] = -axis / math.sqrt(masses[c])
    stretch[o] = axis / math.sqrt(masses[o])
    stretch /= np.linalg.norm(stretch)
    if mode_sign != (1 if float(np.sum(np.asarray(mode["mass_weighted_eigenvector"]).reshape(24,3) * stretch)) >= 0 else -1):
        raise ValueError("off-diagonal S0-S1 operator mode phase sign is inconsistent with the declared C=O phase convention")
    factor = mw / np.sqrt(masses)[:, None]
    if not np.allclose(factor, data["contribution_factor"], rtol=1e-10, atol=1e-12):
        raise ValueError("off-diagonal S0-S1 operator mass-weighted projection factors do not match the Hessian mode/masses")
    if int(np.asarray(data["state_phase_sign"]).reshape(-1)[0]) not in (-1, 1):
        raise ValueError("invalid off-diagonal S0-S1 operator electronic state phase convention")

    analytic_moments = np.zeros((24, 3), dtype=float)
    for atom, origin in enumerate(coords_bohr):
        with ref_mol.with_rinv_origin(origin):
            ip = np.asarray(ref_mol.intor("int1e_iprinv", comp=3), dtype=float)
        operator = -charges[atom] * (ip + ip.transpose(0, 2, 1))
        analytic_moments[atom] = 2.0 * np.einsum("ij,kij->k", transition, operator)
    if not np.allclose(analytic_moments, data["analytic_transition_moments_hartree_per_bohr"], rtol=2e-8, atol=2e-10):
        raise ValueError("off-diagonal S0-S1 operator analytic nuclear-attraction operator contractions disagree with native AO integrals")
    analytic_projection = float(np.sum(factor * analytic_moments))
    if not math.isclose(analytic_projection, float(result["analytic_projection_hartree_per_bohr_sqrt_amu"]), rel_tol=2e-8, abs_tol=2e-10):
        raise ValueError("off-diagonal S0-S1 operator analytic mass-weighted projection is inconsistent")
    steps = np.asarray(data["fd_steps_bohr"], dtype=float).reshape(-1)
    if len(steps) != 3 or not np.isfinite(steps).all() or np.any(steps <= 0) or not math.isclose(
            steps[1], steps[0] / 2.0, rel_tol=1e-12, abs_tol=1e-15) or not math.isclose(
            steps[2], steps[1] / 2.0, rel_tol=1e-12, abs_tol=1e-15):
        raise ValueError("off-diagonal S0-S1 operator operator finite-difference steps are malformed")
    finite_moments = np.zeros((3, 24, 3), dtype=float)
    finite_projections = np.zeros(3, dtype=float)
    for step_index, delta in enumerate(steps):
        for atom, origin in enumerate(coords_bohr):
            for axis_index in range(3):
                shift = np.zeros(3); shift[axis_index] = delta
                with ref_mol.with_rinv_origin(origin + shift):
                    plus = np.asarray(ref_mol.intor("int1e_rinv"), dtype=float)
                with ref_mol.with_rinv_origin(origin - shift):
                    minus = np.asarray(ref_mol.intor("int1e_rinv"), dtype=float)
                operator = -charges[atom] * (plus - minus) / (2.0 * delta)
                finite_moments[step_index, atom, axis_index] = 2.0 * float(np.einsum("ij,ij", transition, operator))
        finite_projections[step_index] = float(np.sum(factor * finite_moments[step_index]))
    if not np.allclose(finite_moments, data["finite_difference_transition_moments_hartree_per_bohr"], rtol=2e-8, atol=2e-10) or not np.allclose(
            finite_projections, data["finite_difference_projection_hartree_per_bohr_sqrt_amu"], rtol=2e-8, atol=2e-10):
        raise ValueError("off-diagonal S0-S1 operator origin finite-difference evidence does not reproduce from native amplitudes")
    moment_errors = np.max(np.abs(finite_moments - analytic_moments[None, :, :]), axis=(1, 2))
    projection_errors = np.abs(finite_projections - analytic_projection)
    moment_roundoff_floor = float(64.0 * np.finfo(float).eps * ref_mol.nao_nr() ** 2 * max(
        1.0, float(np.max(np.abs(finite_moments))), float(np.max(np.abs(analytic_moments)))))
    projection_roundoff_floor = float(64.0 * np.finfo(float).eps * ref_mol.nao_nr() ** 2 * max(
        1.0, float(np.max(np.abs(finite_projections))), abs(analytic_projection)))
    moment_envelope = (2.0 / 3.0) * np.abs(finite_moments[1] - finite_moments[2]) + moment_roundoff_floor
    projection_envelope = (2.0 / 3.0) * abs(finite_projections[1] - finite_projections[2]) + projection_roundoff_floor
    agreement_pass = bool(np.all(np.abs(finite_moments[2] - analytic_moments) <= moment_envelope) and
                          projection_errors[2] <= projection_envelope)
    fd_report = result["finite_difference_validation"]
    if not agreement_pass or fd_report.get("richardson_agreement_pass") is not True or not math.isclose(
            float(fd_report.get("finest_step_absolute_error_envelope_hartree_per_bohr", math.nan)),
            float(np.max(moment_envelope)), rel_tol=2e-8, abs_tol=2e-10) or not math.isclose(
            float(fd_report.get("projected_finest_step_absolute_error_envelope_hartree_per_bohr_sqrt_amu", math.nan)),
            projection_envelope, rel_tol=2e-8, abs_tol=2e-10):
        raise ValueError("off-diagonal S0-S1 operator analytic and finite-difference moments do not agree within the Richardson truncation/roundoff envelope")
    if not np.allclose(data.get("finite_difference_moment_absolute_errors_hartree_per_bohr"),
                       np.abs(finite_moments - analytic_moments[None, :, :]), rtol=2e-8, atol=2e-10) or not np.allclose(
            data.get("finite_difference_projection_absolute_errors_hartree_per_bohr_sqrt_amu"),
            projection_errors, rtol=2e-8, atol=2e-10):
        raise ValueError("off-diagonal S0-S1 operator native absolute-error arrays disagree with analytic/finite-difference reconstruction")
    if not np.allclose(data.get("finite_difference_moment_error_envelope_hartree_per_bohr"),
                       moment_envelope, rtol=2e-8, atol=2e-10) or not np.allclose(
            data.get("finite_difference_projection_error_envelope_hartree_per_bohr_sqrt_amu"),
            np.asarray([projection_envelope]), rtol=2e-8, atol=2e-10) or not np.array_equal(
            np.asarray(data.get("finite_difference_analytic_agreement"), dtype=bool),
            np.asarray([agreement_pass], dtype=bool)):
        raise ValueError("off-diagonal S0-S1 operator native Richardson envelopes/agreement flag disagree with independent reconstruction")
    for json_key, expected in (("projection_hartree_per_bohr_sqrt_amu", finite_projections),
                               ("projection_eV_per_angstrom_sqrt_amu", finite_projections * HARTREE2EV / BOHR)):
        got = result["finite_difference_validation"][json_key]
        if not np.allclose(got, expected, rtol=2e-8, atol=2e-9):
            raise ValueError("off-diagonal S0-S1 operator JSON finite-difference projection disagrees with independent reconstruction")
    reported_projection_errors = result["finite_difference_validation"].get(
        "absolute_error_vs_analytic_hartree_per_bohr_sqrt_amu")
    reported_moment_errors = result["finite_difference_validation"].get(
        "max_component_absolute_error_vs_analytic_hartree_per_bohr")
    if not np.allclose(reported_projection_errors, projection_errors, rtol=2e-8, atol=2e-10) or not np.allclose(
            reported_moment_errors, moment_errors, rtol=2e-8, atol=2e-10):
        raise ValueError("off-diagonal S0-S1 operator JSON finite-difference absolute errors disagree with independent reconstruction")
    value_ev = analytic_projection * HARTREE2EV / BOHR
    if not math.isclose(float(result["analytic_projection_eV_per_angstrom_sqrt_amu"]), value_ev, rel_tol=2e-9, abs_tol=2e-9) or not math.isclose(
            float(result["absolute_analytic_projection_eV_per_angstrom_sqrt_amu"]), abs(value_ev), rel_tol=2e-9, abs_tol=2e-9):
        raise ValueError("off-diagonal S0-S1 operator unit conversion or magnitude is inconsistent")
    reference = reference_native[("singlet", 1)]
    if not math.isclose(float(data["excitation_energy_hartree"]), float(reference["excitation_energy_hartree"].reshape(-1)[0]), rel_tol=2e-7, abs_tol=2e-8) or not math.isclose(
            float(data["oscillator_strength"]), float(reference["oscillator_strength"].reshape(-1)[0]), rel_tol=2e-7, abs_tol=2e-8):
        raise ValueError("off-diagonal S0-S1 operator S1 energy/oscillator strength differs from the independent task-reference root")
    if not math.isclose(float(result["transition_energy_hartree"]), float(data["excitation_energy_hartree"]), rel_tol=1e-12, abs_tol=1e-12) or not math.isclose(
            float(result["transition_energy_eV"]), float(data["excitation_energy_hartree"]) * HARTREE2EV,
            rel_tol=2e-9, abs_tol=2e-9) or not math.isclose(float(result["oscillator_strength"]),
            float(data["oscillator_strength"]), rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("off-diagonal S0-S1 operator reported S1 energies/oscillator strength disagree with the native calculation")
    log_text = log_path.read_text(errors="replace")
    if "NATIVE_OFFDIAG_OP " not in log_text or "NATIVE_OFFDIAG_OP_SOURCE " not in log_text:
        raise ValueError("off-diagonal S0-S1 operator native log lacks its saved-reference source and projection records")
    source_marker = next(json.loads(line[len("NATIVE_OFFDIAG_OP_SOURCE "):])
        for line in log_text.splitlines() if line.startswith("NATIVE_OFFDIAG_OP_SOURCE "))
    reference_root_path = native / "reference_tddft_singlet_root1.npz"
    reference_log_path = native / "reference_tddft.log"
    if source_marker.get("source_kind") != "reused_exact_saved_task_reference_singlet_root1" or source_marker.get(
            "reference_root_file") != reference_root_path.name or source_marker.get(
            "reference_log_file") != reference_log_path.name:
        raise ValueError("off-diagonal S0-S1 operator operator calculation is not tied to the saved task-reference S1 native root")
    if source_marker.get("mode_file") != "mode.json":
        raise ValueError("off-diagonal S0-S1 operator source marker does not bind mode.json")
    _validate_operator_derivative_binding(source_marker, result, derivatives_source_file)
    if result.get("reference_source_kind") != source_marker.get("source_kind"):
        raise ValueError("off-diagonal S0-S1 operator JSON reference source kind disagrees with its native provenance marker")
    for field in ("reference_root_file", "reference_log_file", "mode_file", "derivatives_file"):
        if result.get(field) != source_marker.get(field):
            raise ValueError(f"off-diagonal S0-S1 operator JSON source field {field} disagrees with the native provenance marker")
    if source_marker.get(
            "response_approximation") != response_approximation or source_marker.get(
            "functional") != mode.get("functional") or source_marker.get(
            "basis") != mode.get("basis") or int(source_marker.get("grid_level", -1)) != int(
            mode.get("optimization", {}).get("grid_level", -2)) or source_marker.get(
            "density_fitting") != mode.get("optimization", {}).get("density_fitting"):
        raise ValueError("off-diagonal S0-S1 operator saved-reference source has mismatched geometry or electronic settings")
    reference = reference_native[("singlet", 1)]
    for saved_key, reference_key in (("raw_td_x", "td_x"), ("raw_td_y", "td_y"),
            ("mo_coeff", "mo_coeff"), ("mo_occ", "mo_occ")):
        if not np.allclose(data[saved_key], reference[reference_key], rtol=1e-12, atol=1e-13):
            raise ValueError(f"off-diagonal S0-S1 operator {saved_key} differs from the preserved task-reference root")
    for saved_key in ("excitation_energy_hartree", "oscillator_strength"):
        if not math.isclose(float(np.asarray(data[saved_key]).reshape(-1)[0]),
                float(np.asarray(reference[saved_key]).reshape(-1)[0]), rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(f"off-diagonal S0-S1 operator {saved_key} differs from the preserved task-reference root")
    marker = next(json.loads(line[len("NATIVE_OFFDIAG_OP "):]) for line in log_text.splitlines()
                  if line.startswith("NATIVE_OFFDIAG_OP "))
    if not math.isclose(
            float(marker["analytic_projection_hartree_per_bohr_sqrt_amu"]), analytic_projection,
            rel_tol=2e-8, abs_tol=2e-10) or not np.allclose(
            marker["finite_difference_projection_hartree_per_bohr_sqrt_amu"], finite_projections,
            rtol=2e-8, atol=2e-10):
        raise ValueError("off-diagonal S0-S1 operator native log summary disagrees with independently reconstructed arrays")
    if not isinstance(result.get("scientific_scope"), str) or not result["scientific_scope"].strip():
        raise ValueError("off-diagonal S0-S1 operator approximation scope must be identified")
    return value_ev


def grade(app: Path, final: Path, derivatives_source_file="derivatives.json"):
    if DEPENDENCY_ERROR is not None:
        raise EnvironmentError(f"PySCF/NumPy/SciPy scorer dependencies unavailable: {DEPENDENCY_ERROR}")
    for name, digest in INPUT_HASHES.items():
        path = app / "inputs" / name
        if path.is_symlink() or not path.is_file() or sha(path) != digest:
            raise EnvironmentError(f"evaluation input missing or changed: {name}")
    native = final / "native"
    structure = final / "structure.xyz"
    atoms = read_xyz(structure)
    symbols = [s for s, _ in atoms]
    if sorted(symbols) != sorted(["C"] * 13 + ["H"] * 10 + ["O"]):
        raise ValueError("optimized structure is not neutral benzophenone C13H10O")
    carbonyl_c, carbonyl_o = validate_benzophenone_graph(atoms)
    mode = read_json(final / "mode.json")
    if mode.get("task_id") != "vibronic-derivative-convergence":
        raise ValueError("mode geometry identity/hash mismatch")
    optimization_summary_path = native / "optimization_summary.json"
    optimization_geometry_path = native / "optimized_geometry.xyz"
    frequency_log = native / "frequency.log"
    if any(p.is_symlink() or not p.is_file() for p in
           (optimization_summary_path, optimization_geometry_path, frequency_log)):
        raise ValueError("native optimization summary, geometry, and frequency log are required")
    optimization_summary = read_json(optimization_summary_path)
    if not optimization_summary.get("scf_converged") or optimization_summary.get("functional") != mode.get("functional") or optimization_summary.get("basis") != mode.get("basis"):
        raise ValueError("native optimization summary does not match the mode calculation")
    opt_atoms = read_xyz(optimization_geometry_path)
    if [s for s, _ in opt_atoms] != symbols or not np.allclose(
            np.asarray([x for _, x in opt_atoms]), np.asarray([x for _, x in atoms]), rtol=0, atol=1e-10):
        raise ValueError("native optimized geometry does not match final structure.xyz")
    ftext = frequency_log.read_text(errors="replace")
    if "converged SCF energy" not in ftext or "RKS" not in ftext:
        raise ValueError("native frequency log lacks converged RKS evidence")
    if optimization_summary.get("accepted_attempt") is None:
        raise ValueError("native optimization summary lacks an accepted optimization attempt")
    eval_artifacts = sorted((native / str(optimization_summary["accepted_attempt"])).glob("evaluation_*.npz"))
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
        raise ValueError("no native optimizer gradient matches the reported final geometry")
    canonical_path = native / "final_gradient.npz"
    if canonical_path.is_symlink() or not canonical_path.is_file():
        raise ValueError("canonical native final_gradient.npz is required")
    with np.load(canonical_path) as data:
        canonical_coords = np.asarray(data["coordinates_angstrom"], dtype=float)
        canonical_gradient = np.asarray(data["gradient_hartree_per_bohr"], dtype=float).reshape(-1)
        canonical_energy = float(np.asarray(data["energy_hartree"]).reshape(-1)[0])
    if not np.allclose(canonical_coords, final_coords, rtol=0, atol=1e-8) or not np.allclose(
            canonical_gradient, closest[1], rtol=1e-10, atol=1e-12) or not math.isclose(
            canonical_energy, closest[2], rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("canonical final gradient differs from its native optimizer evaluation")
    eval_max_gradient = float(np.max(np.abs(closest[1])))
    eval_rms_gradient = float(np.sqrt(np.mean(closest[1] ** 2)))
    gtol = float(optimization_summary.get("gtol_hartree_per_bohr", math.nan))
    stationarity_limit = ACCEPTANCE["max_abs_gradient_hartree_per_bohr"]
    if not math.isfinite(gtol) or gtol <= 0 or eval_max_gradient > stationarity_limit:
        raise ValueError("native optimizer gradient exceeds the task's fixed 1e-4 Eh/bohr stationarity limit")
    if not math.isclose(eval_max_gradient, float(optimization_summary["max_abs_gradient_hartree_per_bohr"]),
                        rel_tol=2e-6, abs_tol=2e-9) or not math.isclose(
            eval_rms_gradient, float(optimization_summary["rms_gradient_hartree_per_bohr"]),
            rel_tol=2e-6, abs_tol=2e-9):
        raise ValueError("reported optimization gradients disagree with native evaluation arrays")
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
            freq_max, float(optimization_summary.get("frequency_recheck_max_abs_gradient_hartree_per_bohr", math.nan)),
            rel_tol=2e-6, abs_tol=2e-9) or not math.isclose(
            freq_rms, float(optimization_summary.get("frequency_recheck_rms_gradient_hartree_per_bohr", math.nan)),
            rel_tol=2e-6, abs_tol=2e-9) or not math.isclose(
            freq_energy, float(optimization_summary.get("frequency_recheck_energy_hartree", math.nan)),
            rel_tol=1e-10, abs_tol=1e-8):
        raise ValueError("independent final-frequency gradient recheck is nonstationary or disagrees with its summary")
    if not math.isclose(closest[2], float(optimization_summary["final_energy_hartree"]),
                        rel_tol=1e-10, abs_tol=1e-9):
        raise ValueError("reported optimization energy disagrees with native evaluation array")
    hess_path = native / "independent_cartesian_hessian_hartree_per_bohr2.npy"
    if hess_path.is_symlink() or not hess_path.is_file():
        raise ValueError("independent native Hessian missing or hash mismatch")
    hess = np.load(hess_path)
    if hess.shape != (24, 24, 3, 3) or not np.isfinite(hess).all():
        raise ValueError("native Hessian has invalid dimensions/values")
    hess_transpose = hess.transpose(1, 0, 3, 2)
    hess_symmetric = 0.5 * (hess + hess_transpose)
    hess_antisymmetric = hess - hess_transpose
    hess_scale = float(np.max(np.abs(hess_symmetric)))
    max_antisymmetry_ratio = float(np.max(np.abs(hess_antisymmetric)) /
                                    max(hess_scale, np.finfo(float).tiny))
    fro_antisymmetry_ratio = float(np.linalg.norm(hess_antisymmetric) /
                                    max(np.linalg.norm(hess_symmetric), np.finfo(float).tiny))
    if max_antisymmetry_ratio > ACCEPTANCE["max_entry_antisymmetry_ratio"] or fro_antisymmetry_ratio > ACCEPTANCE["frobenius_antisymmetry_ratio"]:
        raise ValueError("native Hessian violates the documented relative Cartesian symmetry error protocol")
    if not np.allclose(canonical_coords, final_coords, rtol=0, atol=ACCEPTANCE["geometry_match_angstrom"]):
        raise ValueError("canonical Hessian coordinates differ from the submitted structure by more than 1e-9 Angstrom")
    # Either exact optimizer coordinates or their serialized XYZ may have been
    # the consistent source used for the submitted mode set. Check each source
    # as a whole; never mix its spectrum, eigenvector, and C=O projection.
    symbols = [s for s, _ in atoms]
    mol = gto.M(atom=[(s, tuple(x)) for s, x in zip(symbols, canonical_coords)], basis=mode["basis"],
                unit="Angstrom", charge=0, spin=0, symmetry=False, verbose=0)
    masses = np.asarray(mol.atom_mass_list(isotope_avg=True), dtype=float)
    if mode.get("engine") != "PySCF" or not isinstance(mode.get("engine_version"), str) or not mode.get("engine_version").strip():
        raise ValueError("engine/version metadata mismatch")
    if not np.allclose(masses, np.asarray(mode.get("atom_masses_amu"), dtype=float), rtol=1e-10, atol=1e-10):
        raise ValueError("reported atomic masses disagree with element identities")
    mw = np.asarray(mode.get("mass_weighted_eigenvector"), dtype=float).reshape(24, 3)
    if not np.isclose(np.linalg.norm(mw), 1.0, rtol=1e-8, atol=1e-8):
        raise ValueError("mass-weighted mode is not Euclidean normalized")
    modes_path = native / "mode_evidence.npz"
    with np.load(modes_path) as data:
        all_modes = np.asarray(data["mass_weighted_modes"], dtype=float)
        frequencies = np.asarray(data["frequencies_cm1"], dtype=float)
        projection = np.asarray(data["co_stretch_overlap_squared"], dtype=float)
    if all_modes.shape != (66, 24, 3) or not np.isfinite(all_modes).all():
        raise ValueError("native mass-weighted normal-mode array has invalid shape or values")
    selected = int(mode.get("selected_mode_index_zero_based", -1))
    if selected < 0 or selected >= 66 or int(mode.get("imaginary_frequency_count", -1)) != 0:
        raise ValueError("selected mode index or imaginary-frequency count is invalid")
    mode_routes = []
    for route_name, route_coords in (("canonical optimizer coordinates", canonical_coords),
                                     ("serialized structure coordinates", final_coords)):
        route_mol = gto.M(atom=[(s, tuple(x)) for s, x in zip(symbols, route_coords)], basis=mode["basis"],
                          unit="Angstrom", charge=0, spin=0, symmetry=False, verbose=0)
        ha = thermo.harmonic_analysis(route_mol, hess, exclude_trans=True,
                                      exclude_rot=True, imaginary_freq=True)
        freq_complex = np.asarray(ha["freq_wavenumber"])
        freq = freq_complex.real - np.abs(freq_complex.imag)
        sym_ha = thermo.harmonic_analysis(route_mol, hess_symmetric, exclude_trans=True,
                                          exclude_rot=True, imaginary_freq=True)
        sym_freq_complex = np.asarray(sym_ha["freq_wavenumber"])
        sym_freq = sym_freq_complex.real - np.abs(sym_freq_complex.imag)
        eigenvectors = np.asarray(ha["norm_mode"], dtype=float) * np.sqrt(masses)[None, :, None]
        norms = np.linalg.norm(eigenvectors.reshape((len(eigenvectors), -1)), axis=1)
        eigenvectors /= norms[:, None, None]
        axis = route_coords[carbonyl_o] - route_coords[carbonyl_c]
        axis /= np.linalg.norm(axis)
        stretch = np.zeros((24, 3), dtype=float)
        stretch[carbonyl_c] = -axis / math.sqrt(masses[carbonyl_c])
        stretch[carbonyl_o] = axis / math.sqrt(masses[carbonyl_o])
        stretch /= np.linalg.norm(stretch)
        independent_projection = (eigenvectors.reshape((len(eigenvectors), -1)) @ stretch.reshape(-1)) ** 2
        reported_overlap = np.abs(eigenvectors.reshape((len(eigenvectors), -1)) @ mw.reshape(-1))
        matched = int(np.argmax(reported_overlap))
        route_passes = (
            int(ha["freq_error"]) == 0 and int(sym_ha["freq_error"]) == 0
            and freq.shape == (66,) and np.isfinite(freq).all() and np.isfinite(sym_freq).all()
            and np.max(np.abs(sym_freq - freq)) <= ACCEPTANCE["max_frequency_spectrum_delta_cm-1"]
            and np.allclose(frequencies, freq, rtol=0, atol=ACCEPTANCE["frequency_match_cm-1"])
            and np.allclose(np.asarray(mode.get("frequency_spectrum_cm-1"), dtype=float), freq,
                            rtol=0, atol=ACCEPTANCE["frequency_match_cm-1"])
            and math.isclose(float(mode["frequency_cm-1"]), float(freq[selected]), rel_tol=0, abs_tol=ACCEPTANCE["selected_frequency_match_cm-1"])
            and matched == selected and reported_overlap[matched] >= 1.0 - 1e-7
            and np.allclose(projection, independent_projection, rtol=2e-7, atol=2e-9)
            and selected == int(np.argmax(independent_projection))
            and np.allclose(all_modes[selected], mw, rtol=1e-8, atol=1e-9)
            and math.isclose(float(projection[selected]), float(mode["co_stretch_overlap_squared"]),
                             rel_tol=1e-8, abs_tol=1e-9)
        )
        if route_passes:
            mode_routes.append(route_name)
    if not mode_routes:
        raise ValueError("neither complete optimizer-coordinate source reproduces the submitted Hessian mode evidence")
    if not math.isclose(float(projection[selected]), float(mode["co_stretch_overlap_squared"]),
                        rel_tol=1e-8, abs_tol=1e-9):
        raise ValueError("reported C=O projection differs from native mode evidence")

    coords = np.asarray([xyz for _, xyz in atoms])
    vec_ang = mw / np.sqrt(masses)[:, None]
    response_approximation = mode.get("response_approximation")
    method = mode.get("optimization", {})
    reference_logs = native_log_roots(native / "reference_tddft.log", response_approximation,
        mode.get("functional"), mode.get("basis"), method.get("grid_level"),
        method.get("density_fitting", {}))
    basis = mode["basis"]
    ref_mol = gto.M(atom=[(s, tuple(x)) for s, x in atoms], basis=basis,
                    unit="Angstrom", charge=0, spin=0, symmetry=False, verbose=0)
    reference_native = {}
    for spin in ("singlet", "triplet"):
        for root in (1, 2, 3):
            item = load_native_root(native / f"reference_tddft_{spin}_root{root}.npz", root)
            validate_native_orbitals(item, ref_mol, native / f"reference_tddft_{spin}_root{root}.npz")
            summary = reference_logs[(spin, root)]
            if str(item["response_approximation"].item()) != response_approximation or summary.get("response_approximation") != response_approximation:
                raise ValueError("reference native root response approximation differs from mode.json")
            if response_approximation == "TDA" and not np.allclose(item["td_y"], 0.0, rtol=0, atol=1e-14):
                raise ValueError("TDA native root must carry zero Y amplitudes")
            if any(not math.isclose(float(summary[k]), float(item[k].reshape(-1)[0]), rel_tol=2e-8, abs_tol=2e-9)
                   for k in ("excitation_energy_hartree", "oscillator_strength")):
                raise ValueError("reference root log disagrees with saved native root arrays")
            reference_native[(spin, root)] = item
    operator_value = verify_offdiag_operator(final, native, atoms, mode, reference_native, ref_mol, derivatives_source_file)
    with (final / "derivatives.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    displaced = [r for r in rows if r["record_type"] == "displaced_state"]
    central = [r for r in rows if r["record_type"] == "central_difference"]
    step_sizes = sorted({float(r["step_Q_Angstrom_sqrt_amu"]) for r in displaced}, reverse=True)
    if len(step_sizes) != 3 or any(not math.isfinite(x) or x <= 0 for x in step_sizes):
        raise ValueError("three positive displacement step sizes are required")
    if not math.isclose(step_sizes[1], step_sizes[0] / 2, rel_tol=1e-12, abs_tol=1e-14) or not math.isclose(
            step_sizes[2], step_sizes[1] / 2, rel_tol=1e-12, abs_tol=1e-14):
        raise ValueError("the three displacement steps must halve successively")
    if len(displaced) != 36 or len(central) != 18:
        raise ValueError("expected 36 displaced-root and 18 central-derivative records")
    for step_idx, qstep in enumerate(step_sizes, start=1):
        group = [r for r in displaced if int(r["step_index"]) == step_idx]
        if len(group) != 12 or not all(math.isclose(float(r["step_Q_Angstrom_sqrt_amu"]), qstep, rel_tol=0, abs_tol=1e-12) for r in group):
            raise ValueError("three displacement steps must be exactly halved")
        for sign in ("minus", "plus"):
            target = coords + (-1 if sign == "minus" else 1) * qstep * vec_ang
            xyz_path = native / f"q{step_idx}_{sign}.xyz"
            got = read_xyz(xyz_path)
            if [s for s, _ in got] != symbols or not np.allclose(
                    np.asarray([x for _, x in got]), target, rtol=0, atol=2e-8):
                raise ValueError(f"{xyz_path.name} does not follow the mass-weighted mode displacement")
            log_path = native / f"q{step_idx}_{sign}_tddft.log"
            log_roots = native_log_roots(log_path, response_approximation,
                mode.get("functional"), mode.get("basis"), method.get("grid_level"),
                method.get("density_fitting", {}))
            displaced_atoms = read_xyz(xyz_path)
            displaced_mol = gto.M(atom=[(s, tuple(x)) for s, x in displaced_atoms], basis=basis,
                                   unit="Angstrom", charge=0, spin=0, symmetry=False, verbose=0)
            for spin in ("singlet", "triplet"):
                displaced_native = {}
                for root in (1, 2, 3):
                    item = load_native_root(native / f"q{step_idx}_{sign}_tddft_{spin}_root{root}.npz", root)
                    validate_native_orbitals(item, displaced_mol,
                        native / f"q{step_idx}_{sign}_tddft_{spin}_root{root}.npz")
                    summary = log_roots[(spin, root)]
                    if str(item["response_approximation"].item()) != response_approximation or summary.get("response_approximation") != response_approximation:
                        raise ValueError("displaced native root response approximation differs from mode.json")
                    if response_approximation == "TDA" and not np.allclose(item["td_y"], 0.0, rtol=0, atol=1e-14):
                        raise ValueError("TDA displaced root must carry zero Y amplitudes")
                    if any(not math.isclose(float(summary[k]), float(item[k].reshape(-1)[0]), rel_tol=2e-8, abs_tol=2e-9)
                           for k in ("excitation_energy_hartree", "oscillator_strength")):
                        raise ValueError("displaced root log disagrees with saved native root arrays")
                    displaced_native[root] = item
                signed = np.asarray([[transition_overlap_proxy(reference_native[(spin, ref_root)],
                    displaced_native[root], ref_mol, displaced_mol) for root in (1, 2, 3)]
                    for ref_root in (1, 2, 3)])
                logged = sorted([x for x in group if x["multiplicity"] == spin and x["sign"] == sign],
                                key=lambda x: int(x["reference_root"]))
                submitted = np.asarray([[float(r[f"signed_overlap_to_root_{j}"]) for j in (1, 2, 3)]
                                        for r in logged])
                if not np.allclose(signed, submitted, rtol=2e-7, atol=2e-8):
                    raise ValueError("submitted root-overlap matrix disagrees with native transition densities and AO cross-overlaps")
                for row in logged:
                    rq = int(row["selected_displaced_root"])
                    energy_ev = float(displaced_native[rq]["excitation_energy_hartree"].reshape(-1)[0] * HARTREE2EV)
                    if not math.isclose(energy_ev, float(row["excitation_energy_eV"]), rel_tol=2e-8, abs_tol=2e-8):
                        raise ValueError("displaced excitation energy differs from the native TDDFT root")
                    if not math.isclose(float(displaced_native[rq]["oscillator_strength"].reshape(-1)[0]),
                                        float(row["oscillator_strength"]), rel_tol=2e-8, abs_tol=2e-9):
                        raise ValueError("displaced oscillator strength differs from the native root")
        for spin in ("singlet", "triplet"):
            for sign in ("minus", "plus"):
                selected_rows = sorted(
                    [x for x in group if x["multiplicity"] == spin and x["sign"] == sign],
                    key=lambda x: int(x["reference_root"]))
                matrix = np.asarray([[float(r[f"signed_overlap_to_root_{i}"]) for i in (1, 2, 3)]
                                     for r in selected_rows])
                if matrix.shape != (3, 3) or not np.isfinite(matrix).all() or np.max(np.abs(matrix)) > 1.000001:
                    raise ValueError("transition-density overlap proxy is invalid")
                ref_idx, disp_idx = linear_sum_assignment(-np.abs(matrix))
                assignment = {int(i) + 1: int(j) + 1 for i, j in zip(ref_idx, disp_idx)}
                for r in selected_rows:
                    root = int(r["reference_root"])
                    if int(r["selected_displaced_root"]) != assignment[root]:
                        raise ValueError("root assignment disagrees with the one-to-one overlap matching")
                    selected_overlap = float(matrix[root - 1, assignment[root] - 1])
                    expected_sign = 1 if selected_overlap >= 0 else -1
                    if int(r["phase_alignment_sign"]) != expected_sign or not math.isclose(
                            float(r["selected_transition_density_overlap_proxy"]), abs(selected_overlap),
                            rel_tol=2e-7, abs_tol=2e-8):
                        raise ValueError("selected overlap magnitude or phase sign disagrees with the signed overlap matrix")
    lookup = {(r["step_index"], r["multiplicity"], int(r["reference_root"]), r["sign"]): r
              for r in displaced}
    derivatives = read_json(final / "derivatives.json")
    if derivatives.get("derivative_quantity_type") != "diagonal_excitation_energy_derivative":
        raise ValueError("finite-difference rows must remain typed as diagonal excitation-energy derivatives")
    method_meta = derivatives.get("electronic_method", {})
    if method_meta.get("response_approximation") != mode.get("response_approximation") or method_meta.get(
            "functional") != mode.get("functional") or method_meta.get("basis") != mode.get("basis") or int(
            method_meta.get("grid_level", -1)) != int(mode.get("optimization", {}).get("grid_level", -2)) or method_meta.get(
            "density_fitting") != mode.get("optimization", {}).get("density_fitting"):
        raise ValueError("reference/displaced derivative settings do not match the mode and off-diagonal S0-S1 operator route")
    refinement = derivatives.get("derivative_refinement_diagnostics")
    if not isinstance(refinement, list) or len(refinement) != 6:
        raise ValueError("per-state derivative refinement diagnostics are required")
    refinement_lookup = {(x.get("multiplicity"), int(x.get("reference_root", -1))): x for x in refinement}
    for spin in ("singlet", "triplet"):
        for root in (1, 2, 3):
            values = [float(next(x for x in central if x["multiplicity"] == spin
                                 and int(x["reference_root"]) == root
                                 and int(x["step_index"]) == i)["central_derivative_eV_per_Angstrom_sqrt_amu"])
                      for i in (1, 2, 3)]
            changes = [abs(values[1] - values[0]), abs(values[2] - values[1])]
            item = refinement_lookup.get((spin, root))
            if item is None or not np.allclose(item.get("central_derivatives_eV_per_Angstrom_sqrt_amu", []),
                                               values, rtol=1e-9, atol=1e-10) or not np.allclose(
                    item.get("successive_absolute_changes_eV_per_Angstrom_sqrt_amu", []),
                    changes, rtol=1e-9, atol=1e-10):
                raise ValueError("reported finite-step refinement diagnostics disagree with the central derivatives")
            if bool(item.get("change_decreases_on_refinement")) != bool(changes[1] < changes[0]):
                raise ValueError("finite-step refinement interpretation disagrees with observed change")
    ref = {(r["multiplicity"], int(r["reference_root"]), int(r["step_index"])): r for r in central}
    for r in central:
        q = float(r["step_Q_Angstrom_sqrt_amu"])
        expected_q = step_sizes[int(r["step_index"]) - 1]
        if not math.isclose(q, expected_q, rel_tol=0, abs_tol=1e-12):
            raise ValueError("central derivative step size mismatch")
        derived = (float(r["energy_plus_eV"]) - float(r["energy_minus_eV"])) / (2 * q)
        if not math.isclose(derived, float(r["central_derivative_eV_per_Angstrom_sqrt_amu"]),
                            rel_tol=1e-9, abs_tol=1e-10):
            raise ValueError("central derivative is not recomputed from +/- energies")
        minus = lookup[(r["step_index"], r["multiplicity"], int(r["reference_root"]), "minus")]
        plus = lookup[(r["step_index"], r["multiplicity"], int(r["reference_root"]), "plus")]
        if int(r["minus_displaced_root"]) != int(minus["selected_displaced_root"]) or int(
                r["plus_displaced_root"]) != int(plus["selected_displaced_root"]):
            raise ValueError("central difference root labels disagree with displaced-state records")
        if not math.isclose(float(r["energy_minus_eV"]), float(minus["excitation_energy_eV"]),
                            rel_tol=1e-9, abs_tol=1e-9) or not math.isclose(
                float(r["energy_plus_eV"]), float(plus["excitation_energy_eV"]),
                rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError("central difference energies disagree with displaced-state records")
        if r.get("quantity_type") != "diagonal_excitation_energy_derivative" or not isinstance(
                r.get("quantity_definition"), str) or not r["quantity_definition"].strip():
            raise ValueError("central finite difference must be typed as a diagonal excitation-energy derivative")
    coupling = derivatives.get("s0_s1_offdiag_operator", {})
    if coupling.get("status") != "computed_lr_one_electron_operator_approximation" or coupling.get("quantity_type") != "off_diagonal_electronic_nuclear_attraction_derivative_operator_projection" or coupling.get("operator_artifact") != "s0_s1_offdiag_operator.json":
        raise ValueError("the off-diagonal S0-S1 operator approximation is not linked as a separately typed off-diagonal quantity")
    if derivatives.get("spin_orbit_coupling", {}).get("status") != "not_computed":
        raise ValueError("off-diagonal S0-S1 operator operator projection must not be conflated with spin-orbit coupling")
    return {"status": "PASS", "reward": 1.0, "exit_code": 0,
            "detail": f"Independent Hessian/mode reconstruction, displaced-state overlaps and diagonal derivatives passed. The scoped LR response S0-S1 one-electron off-diagonal S0-S1 operator operator approximation ({operator_value:.8g} eV/(angstrom*sqrt(amu))) and origin finite-difference validation passed; SOC/absolute ISC remain uncomputed."}



"""Temporary Task 148 compact-output adapter candidate; canonicalizes syntax only."""
import csv
import json
import math
import os
import shutil
import stat
import tempfile
from pathlib import Path

import numpy as np


def _compact_rows(path: Path, columns: set[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        header = reader.fieldnames
        if header is None or len(header) != len(set(header)) or set(header) != columns:
            raise ValueError(f"{path.name} header must be exactly {sorted(columns)}")
        rows = list(reader)
    if any(None in row or any(v is None for v in row.values()) for row in rows):
        raise ValueError(f"{path.name} has a row with a mismatched column count")
    return rows


def _integer(value: str, label: str, low: int, high: int) -> int:
    number = float(value)
    if not math.isfinite(number) or number != math.floor(number) or not low <= number <= high:
        raise ValueError(f"{label} must be an integer in [{low}, {high}]")
    return int(number)


def _finite(value: str, label: str, low: float | None = None) -> float:
    number = float(value)
    if not math.isfinite(number) or (low is not None and number <= low):
        raise ValueError(f"{label} must be finite" + (f" and > {low}" if low is not None else ""))
    return number


def _safe_copy_final(source: Path, destination: Path) -> None:
    """Reject unsafe entries before copying; never dereference links into the normalized view."""
    if source.is_symlink() or not source.is_dir():
        raise ValueError("candidate final must be a real directory")
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise ValueError("candidate final must be a real directory")
    for root, dirs, files in os.walk(source, topdown=True, followlinks=False):
        for name in dirs + files:
            item = Path(root) / name
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise ValueError(f"candidate artifact is a symlink: {item.relative_to(source)}")
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError(f"candidate artifact is not a single-link regular file: {item.relative_to(source)}")
    shutil.copytree(source, destination, copy_function=shutil.copy2, symlinks=False)
    for root, _, files in os.walk(source):
        for name in files:
            original, copied = Path(root) / name, destination / (Path(root) / name).relative_to(source)
            if original.read_bytes() != copied.read_bytes():
                raise ValueError(f"candidate artifact changed while making the normalized view: {original.relative_to(source)}")


def _compact_is_requested(final: Path) -> bool:
    if final.is_symlink():
        raise ValueError("candidate final must be a real directory")
    state = final / "state_tracking.csv"
    deriv = final / "derivatives.csv"
    mode_path = final / "mode.json"
    if not (state.exists() and deriv.exists() and mode_path.exists()):
        return False
    if any(path.is_symlink() or not path.is_file() for path in (state, deriv, mode_path)):
        raise ValueError("compact report files must be regular files")
    with deriv.open(newline="", encoding="utf-8") as stream:
        fields = csv.DictReader(stream).fieldnames or []
    return "record_type" not in fields


def _resolve_engine_version(optimization: dict, compact_mode: dict) -> str:
    native_version = optimization.get("pyscf_version")
    declared_version = compact_mode.get("engine_version")
    for label, value in (("native optimization summary", native_version),
                         ("compact mode.json", declared_version)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"{label} PySCF version must be a non-empty string")
    if native_version and declared_version and native_version != declared_version:
        raise ValueError("compact engine_version conflicts with native optimization summary")
    version = native_version or declared_version
    if not version:
        raise ValueError("report the PySCF version in optimization_summary.json or compact mode.json")
    return version


def _normalize_compact(final: Path, normalized: Path) -> None:
    """Create old reader objects from candidate scientific evidence and compact selections."""
    from pyscf import gto
    from pyscf.data.nist import HARTREE2EV, BOHR

    _safe_copy_final(final, normalized)
    native = normalized / "native"
    compact_mode = json.loads((final / "mode.json").read_text(encoding="utf-8"))
    if not isinstance(compact_mode, dict):
        raise ValueError("compact mode.json must be a JSON object")
    if set(compact_mode) not in ({"selected_mode_index_zero_based"},
                                  {"selected_mode_index_zero_based", "engine_version"}):
        raise ValueError("compact mode.json requires selected_mode_index_zero_based and permits only an optional engine_version")
    selected = compact_mode["selected_mode_index_zero_based"]
    if isinstance(selected, bool) or not isinstance(selected, int) or not 0 <= selected < 66:
        raise ValueError("selected_mode_index_zero_based must be an integer from 0 to 65")
    opt_path = native / "optimization_summary.json"
    optimization = json.loads(opt_path.read_text(encoding="utf-8"))
    structure_atoms = __import__("verify").read_xyz(normalized / "structure.xyz")
    basis = optimization.get("basis")
    if not isinstance(basis, str) or not basis:
        raise ValueError("candidate optimization summary must report the basis")
    mol = gto.M(atom=[(s, tuple(x)) for s, x in structure_atoms], basis=basis,
                unit="Angstrom", charge=0, spin=0, symmetry=False, verbose=0)
    with np.load(native / "mode_evidence.npz") as data:
        all_modes = np.asarray(data["mass_weighted_modes"], dtype=float)
        frequencies = np.asarray(data["frequencies_cm1"], dtype=float)
        projection = np.asarray(data["co_stretch_overlap_squared"], dtype=float)
    if all_modes.shape != (66, 24, 3) or frequencies.shape != (66,) or projection.shape != (66,):
        raise ValueError("candidate mode_evidence.npz has invalid shapes")
    from verify import native_log_roots
    ref_roots = native_log_roots(native / "reference_tddft.log")
    approximations = {str(x.get("response_approximation")) for x in ref_roots.values()}
    if len(ref_roots) != 6 or len(approximations) != 1 or next(iter(approximations)) not in ("full TDDFT", "TDA"):
        raise ValueError("candidate reference log does not identify one supported response approximation")
    pyscf_version = _resolve_engine_version(optimization, compact_mode)
    mode = {
        "task_id": "vibronic-derivative-convergence",
        "functional": optimization.get("functional"), "basis": basis,
        "response_approximation": next(iter(approximations)),
        "engine": "PySCF", "engine_version": pyscf_version,
        "frequency_cm-1": float(frequencies[selected]),
        "frequency_spectrum_cm-1": frequencies.tolist(),
        "imaginary_frequency_count": int(np.count_nonzero(frequencies <= 0)),
        "selected_mode_index_zero_based": selected,
        "atom_masses_amu": np.asarray(mol.atom_mass_list(isotope_avg=True), dtype=float).tolist(),
        "mass_weighted_eigenvector": all_modes[selected].reshape(-1).tolist(),
        "co_stretch_overlap_squared": float(projection[selected]),
        "optimization": optimization,
    }
    (normalized / "mode.json").write_text(json.dumps(mode, indent=2) + "\n", encoding="utf-8")

    state_columns = {"step_index", "step_Q_Angstrom_sqrt_amu", "multiplicity", "sign",
                     "reference_root", "selected_displaced_root"}
    derivative_columns = {"step_index", "step_Q_Angstrom_sqrt_amu", "multiplicity",
                          "reference_root", "central_derivative_eV_per_Angstrom_sqrt_amu"}
    state_rows = _compact_rows(final / "state_tracking.csv", state_columns)
    derivative_rows = _compact_rows(final / "derivatives.csv", derivative_columns)
    state_map = {}
    q_by_step = {}
    for row in state_rows:
        step = _integer(row["step_index"], "state_tracking.step_index", 1, 3)
        q = _finite(row["step_Q_Angstrom_sqrt_amu"], "state_tracking.step_Q", 0)
        spin, sign = row["multiplicity"], row["sign"]
        ref_root = _integer(row["reference_root"], "state_tracking.reference_root", 1, 3)
        displaced_root = _integer(row["selected_displaced_root"], "state_tracking.selected_displaced_root", 1, 3)
        if spin not in ("singlet", "triplet") or sign not in ("minus", "plus"):
            raise ValueError("state tracking spin/sign enum is invalid")
        key = (step, spin, sign, ref_root)
        if key in state_map:
            raise ValueError(f"duplicate state tracking key: {key}")
        state_map[key] = {"q": q, "selected": displaced_root}
        if step in q_by_step and not math.isclose(q_by_step[step], q, rel_tol=0, abs_tol=1e-14):
            raise ValueError(f"state tracking Q is inconsistent within step {step}")
        q_by_step[step] = q
    expected_state_keys = {(i, s, sign, root) for i in (1, 2, 3)
                           for s in ("singlet", "triplet") for sign in ("minus", "plus")
                           for root in (1, 2, 3)}
    if set(state_map) != expected_state_keys or len(state_rows) != 36:
        raise ValueError("state_tracking.csv must cover all 36 step/sign/spin/reference-root records exactly once")
    if not (math.isclose(q_by_step[2], q_by_step[1] / 2, rel_tol=1e-12, abs_tol=1e-14)
            and math.isclose(q_by_step[3], q_by_step[2] / 2, rel_tol=1e-12, abs_tol=1e-14)):
        raise ValueError("state tracking steps must halve successively")
    deriv_map = {}
    for row in derivative_rows:
        step = _integer(row["step_index"], "derivatives.step_index", 1, 3)
        q = _finite(row["step_Q_Angstrom_sqrt_amu"], "derivatives.step_Q", 0)
        spin = row["multiplicity"]
        root = _integer(row["reference_root"], "derivatives.reference_root", 1, 3)
        value = _finite(row["central_derivative_eV_per_Angstrom_sqrt_amu"], "derivatives.value")
        key = (step, spin, root)
        if spin not in ("singlet", "triplet") or key in deriv_map:
            raise ValueError(f"invalid or duplicate derivative key: {key}")
        if not math.isclose(q, q_by_step[step], rel_tol=0, abs_tol=1e-14):
            raise ValueError(f"derivative Q disagrees with state tracking for step {step}")
        deriv_map[key] = {"q": q, "value": value}
    expected_deriv_keys = {(i, s, root) for i in (1, 2, 3)
                           for s in ("singlet", "triplet") for root in (1, 2, 3)}
    if set(deriv_map) != expected_deriv_keys or len(derivative_rows) != 18:
        raise ValueError("derivatives.csv must cover all 18 step/spin/reference-root derivatives exactly once")

    from verify import read_xyz, load_native_root, validate_native_orbitals, transition_overlap_proxy
    atoms = read_xyz(normalized / "structure.xyz")
    ref_mol = gto.M(atom=[(s, tuple(x)) for s, x in atoms], basis=basis,
                    unit="Angstrom", charge=0, spin=0, symmetry=False, verbose=0)
    reference = {(spin, root): load_native_root(native / f"reference_tddft_{spin}_root{root}.npz", root)
                 for spin in ("singlet", "triplet") for root in (1, 2, 3)}
    for item in reference.values():
        validate_native_orbitals(item, ref_mol, "reference native root")
    displaced_cache = {}
    for step in (1, 2, 3):
        for sign in ("minus", "plus"):
            xyz_path = native / f"q{step}_{sign}.xyz"
            displaced_atoms = read_xyz(xyz_path)
            displaced_mol = gto.M(atom=[(s, tuple(x)) for s, x in displaced_atoms], basis=basis,
                                  unit="Angstrom", charge=0, spin=0, symmetry=False, verbose=0)
            for spin in ("singlet", "triplet"):
                roots = {root: load_native_root(native / f"q{step}_{sign}_tddft_{spin}_root{root}.npz", root)
                         for root in (1, 2, 3)}
                for item in roots.values():
                    validate_native_orbitals(item, displaced_mol, f"q{step}_{sign} native root")
                displaced_cache[(step, sign, spin)] = (displaced_mol, roots)
    expanded = []
    for key in sorted(state_map):
        step, spin, sign, ref_root = key
        q = state_map[key]["q"]
        displaced_mol, roots = displaced_cache[(step, sign, spin)]
        overlaps = [transition_overlap_proxy(reference[(spin, ref_root)], roots[root], ref_mol, displaced_mol)
                    for root in (1, 2, 3)]
        selected = state_map[key]["selected"]
        picked = roots[selected]
        overlap = overlaps[selected - 1]
        expanded.append({
            "record_type": "displaced_state", "step_index": step,
            "step_Q_Angstrom_sqrt_amu": q, "sign": sign, "multiplicity": spin,
            "reference_root": ref_root, "selected_displaced_root": selected,
            "signed_overlap_to_root_1": overlaps[0], "signed_overlap_to_root_2": overlaps[1],
            "signed_overlap_to_root_3": overlaps[2],
            "selected_transition_density_overlap_proxy": abs(overlap),
            "phase_alignment_sign": 1 if overlap >= 0 else -1,
            "excitation_energy_eV": float(picked["excitation_energy_hartree"].reshape(-1)[0]) * HARTREE2EV,
            "oscillator_strength": float(picked["oscillator_strength"].reshape(-1)[0]),
        })
    for key in sorted(deriv_map):
        step, spin, root = key
        q = deriv_map[key]["q"]
        minus_root = state_map[(step, spin, "minus", root)]["selected"]
        plus_root = state_map[(step, spin, "plus", root)]["selected"]
        minus = displaced_cache[(step, "minus", spin)][1][minus_root]
        plus = displaced_cache[(step, "plus", spin)][1][plus_root]
        em = float(minus["excitation_energy_hartree"].reshape(-1)[0]) * HARTREE2EV
        ep = float(plus["excitation_energy_hartree"].reshape(-1)[0]) * HARTREE2EV
        expanded.append({
            "record_type": "central_difference", "step_index": step,
            "step_Q_Angstrom_sqrt_amu": q, "sign": "central", "multiplicity": spin,
            "reference_root": root, "selected_displaced_root": "",
            "minus_displaced_root": minus_root, "plus_displaced_root": plus_root,
            "energy_minus_eV": em, "energy_plus_eV": ep,
            "central_derivative_eV_per_Angstrom_sqrt_amu": deriv_map[key]["value"],
            "quantity_type": "diagonal_excitation_energy_derivative",
            "quantity_definition": "[E_n(+Q)-E_n(-Q)]/(2Q) for one state n; not an off-diagonal operator projection",
        })
    fields = sorted({field for row in expanded for field in row})
    with (normalized / "derivatives.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(expanded)

    operator_compact = json.loads((final / "s0_s1_offdiag_operator.json").read_text(encoding="utf-8"))
    if not isinstance(operator_compact, dict):
        raise ValueError("compact operator JSON must be a JSON object")
    required_operator = {"analytic_projection_hartree_per_bohr_sqrt_amu", "origin_steps_bohr",
                         "projection_hartree_per_bohr_sqrt_amu", "scientific_scope"}
    ev_key = "analytic_projection_eV_per_angstrom_sqrt_amu"
    if not required_operator <= set(operator_compact) <= required_operator | {ev_key}:
        raise ValueError(f"compact operator JSON requires {sorted(required_operator)} and permits optional {ev_key}")
    analytic_projection = float(operator_compact["analytic_projection_hartree_per_bohr_sqrt_amu"])
    analytic_projection_ev = (float(operator_compact[ev_key]) if ev_key in operator_compact
                              else analytic_projection * HARTREE2EV / BOHR)
    with np.load(native / "s0_s1_offdiag_operator_evidence.npz") as archive:
        op_evidence = {key: np.asarray(archive[key]).copy() for key in archive.files}
    steps = np.asarray(operator_compact["origin_steps_bohr"], dtype=float)
    projections = np.asarray(operator_compact["projection_hartree_per_bohr_sqrt_amu"], dtype=float)
    if steps.shape != (3,) or projections.shape != (3,) or not np.isfinite(steps).all() or not np.isfinite(projections).all():
        raise ValueError("compact operator must provide three finite origin steps and three projections")
    if not np.allclose(steps, np.asarray(op_evidence["fd_steps_bohr"], dtype=float).reshape(3), rtol=0, atol=1e-15):
        raise ValueError("compact operator origin steps disagree with candidate native finite-difference evidence")
    reference_s1 = reference[("singlet", 1)]
    x = np.asarray(reference_s1["td_x"], dtype=float)
    y = np.asarray(reference_s1["td_y"], dtype=float)
    finite_moments = np.asarray(op_evidence["finite_difference_transition_moments_hartree_per_bohr"], dtype=float)
    analytic_moments = np.asarray(op_evidence["analytic_transition_moments_hartree_per_bohr"], dtype=float)
    moment_errors = np.max(np.abs(finite_moments - analytic_moments[None, :, :]), axis=(1, 2))
    projection_errors = np.abs(projections - float(operator_compact["analytic_projection_hartree_per_bohr_sqrt_amu"]))
    eps_floor = 64.0 * np.finfo(float).eps * ref_mol.nao_nr() ** 2
    moment_floor = eps_floor * max(1.0, float(np.max(np.abs(finite_moments))), float(np.max(np.abs(analytic_moments))))
    projection_floor = eps_floor * max(1.0, float(np.max(np.abs(projections))), abs(float(operator_compact["analytic_projection_hartree_per_bohr_sqrt_amu"])))
    moment_envelope = (2.0 / 3.0) * np.abs(finite_moments[1] - finite_moments[2]) + moment_floor
    projection_envelope = (2.0 / 3.0) * abs(projections[1] - projections[2]) + projection_floor
    agreement = bool(np.all(np.abs(finite_moments[2] - analytic_moments) <= moment_envelope)
                     and projection_errors[2] <= projection_envelope)
    fd_report = {
        "origin_steps_bohr": steps.tolist(),
        "projection_hartree_per_bohr_sqrt_amu": projections.tolist(),
        "projection_eV_per_angstrom_sqrt_amu": (projections * HARTREE2EV / BOHR).tolist(),
        "absolute_error_vs_analytic_hartree_per_bohr_sqrt_amu": projection_errors.tolist(),
        "max_component_absolute_error_vs_analytic_hartree_per_bohr": moment_errors.tolist(),
        "finest_step_absolute_error_envelope_hartree_per_bohr": float(np.max(moment_envelope)),
        "projected_finest_step_absolute_error_envelope_hartree_per_bohr_sqrt_amu": float(projection_envelope),
        "richardson_agreement_pass": agreement,
    }
    full_operator = {
        "status": "computed_linear_response_operator_approximation",
        "target": "S0-S1 off-diagonal nuclear-attraction derivative operator projection",
        "quantity_type": "off_diagonal_electronic_nuclear_attraction_derivative_operator_projection",
        "approximation_kind": "single_reference_linear_response_one_electron_transition_density",
        "literature_equivalence": False, "triplet_generalization": False,
        "functional": mode["functional"], "basis": mode["basis"],
        "response_approximation": mode["response_approximation"],
        "density_fitting": optimization["density_fitting"], "grid_level": optimization["grid_level"],
        "reference_source_kind": "reused_exact_saved_task_reference_singlet_root1",
        "reference_root_file": "reference_tddft_singlet_root1.npz",
        "reference_log_file": "reference_tddft.log", "mode_file": "mode.json",
        "derivatives_file": "derivatives.csv",
        "transition_energy_hartree": float(reference_s1["excitation_energy_hartree"].reshape(-1)[0]),
        "transition_energy_eV": float(reference_s1["excitation_energy_hartree"].reshape(-1)[0]) * HARTREE2EV,
        "oscillator_strength": float(reference_s1["oscillator_strength"].reshape(-1)[0]),
        "td_eigenvector_x2_minus_y2_norm": 2.0 * (float(np.sum(x*x)) - float(np.sum(y*y))),
        "analytic_projection_hartree_per_bohr_sqrt_amu": float(operator_compact["analytic_projection_hartree_per_bohr_sqrt_amu"]),
        "analytic_projection_eV_per_angstrom_sqrt_amu": analytic_projection_ev,
        "absolute_analytic_projection_eV_per_angstrom_sqrt_amu": abs(analytic_projection_ev),
        "finite_difference_validation": fd_report,
        "scientific_scope": operator_compact["scientific_scope"],
    }
    (normalized / "s0_s1_offdiag_operator.json").write_text(json.dumps(full_operator, indent=2) + "\n", encoding="utf-8")

    refinement = []
    for spin in ("singlet", "triplet"):
        for root in (1, 2, 3):
            values = [deriv_map[(step, spin, root)]["value"] for step in (1, 2, 3)]
            changes = [abs(values[1] - values[0]), abs(values[2] - values[1])]
            refinement.append({"multiplicity": spin, "reference_root": root,
                "central_derivatives_eV_per_Angstrom_sqrt_amu": values,
                "successive_absolute_changes_eV_per_Angstrom_sqrt_amu": changes,
                "change_decreases_on_refinement": bool(changes[1] < changes[0])})
    derivatives = {
        "derivative_quantity_type": "diagonal_excitation_energy_derivative",
        "electronic_method": {"functional": mode["functional"], "basis": mode["basis"],
            "response_approximation": mode["response_approximation"],
            "grid_level": optimization["grid_level"], "density_fitting": optimization["density_fitting"]},
        "derivative_refinement_diagnostics": refinement,
        "s0_s1_offdiag_operator": {"status": "computed_lr_one_electron_operator_approximation",
            "quantity_type": "off_diagonal_electronic_nuclear_attraction_derivative_operator_projection",
            "operator_artifact": "s0_s1_offdiag_operator.json"},
        "spin_orbit_coupling": {"status": "not_computed"},
    }
    (normalized / "derivatives.json").write_text(json.dumps(derivatives, indent=2) + "\n", encoding="utf-8")


def grade_submission(app: Path, final: Path):
    """Use a private canonical view for compact reports; leave historical submissions untouched."""
    if DEPENDENCY_ERROR is not None:
        raise EnvironmentError(f"PySCF/NumPy/SciPy scorer dependencies unavailable: {DEPENDENCY_ERROR}")
    for name, digest in INPUT_HASHES.items():
        path = app / "inputs" / name
        if path.is_symlink() or not path.is_file() or sha(path) != digest:
            raise EnvironmentError(f"evaluation input missing or changed: {name}")
    if not _compact_is_requested(final):
        return grade(app, final)
    with tempfile.TemporaryDirectory(prefix="bench22-task148-normalized-") as directory:
        normalized = Path(directory) / "final"
        _normalize_compact(final, normalized)
        return grade(app, normalized, derivatives_source_file="derivatives.csv")


if __name__ == "__main__":
    app = Path(os.environ.get("APP", "/app"))
    log = Path(os.environ.get("LOGS", "/logs/verifier"))
    log.mkdir(parents=True, exist_ok=True)
    try:
        result = grade_submission(app, app / "final")
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
