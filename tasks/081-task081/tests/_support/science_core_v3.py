"""Shared, versioned Case06 v3 native optimizer checks.

This module is deliberately separate from the v2 minimum/curvature verifier.
Both host Oracle and Agent adapters must pass native input/output bytes here;
metadata statuses are never accepted as scientific results.
"""
from __future__ import annotations

import math
import re

try:
    import native_science as _native
except ImportError:  # package import when tests are addressed as a namespace
    from . import native_science as _native

# CP2K GEO_OPT default criteria, frozen from author runs and CP2K 2024.2/2024.3
# manual. M3 sTDA has explicit, stricter input criteria and keeps those values.
DEFAULT_LIMITS = (0.003, 0.0015, 0.00045, 0.00030)  # bohr, bohr, Ha/bohr, Ha/bohr
M3_STDA_LIMITS = (1e-5, 1e-5, 1e-6, 1e-6)  # bohr, bohr, Ha/bohr, Ha/bohr

class ScienceInputError(ValueError):
    pass


def _last_invocation(output: str, *, allow_incomplete: bool = False) -> str:
    starts = list(re.finditer(r"(?im)^.*PROGRAM STARTED AT\b", output))
    if not starts:
        raise ScienceInputError("native output has no PROGRAM STARTED AT")
    tail = output[starts[-1].start():]
    ends = list(re.finditer(r"(?im)^.*PROGRAM ENDED AT\b", tail))
    if not ends and allow_incomplete:
        return tail
    if len(ends) != 1:
        raise ScienceInputError(f"last invocation has {len(ends)} normal-end markers; expected exactly one")
    return tail[:ends[0].end()]


def _last_float(pattern: str, text: str, label: str) -> float:
    values = re.findall(pattern, text, re.I | re.M)
    if not values:
        raise ScienceInputError(f"last invocation has no {label}")
    value = float(values[-1].replace("D", "E").replace("d", "e"))
    if not math.isfinite(value):
        raise ScienceInputError(f"last invocation {label} is nonfinite")
    return value


def _last_stop_block(tail: str) -> str:
    opt_steps = list(re.finditer(r"(?im)^\s*OPT\|\s*Step number\s+\d+\s*$", tail))
    completed = list(re.finditer(r"GEOMETRY OPTIMIZATION COMPLETED", tail, re.I))
    if opt_steps:
        if not completed:
            raise ScienceInputError("native OPT-format optimizer has no completed stop block")
        stop = completed[-1].start()
        candidates = [match for match in opt_steps if match.start() < stop]
        if not candidates:
            raise ScienceInputError("native OPT-format completed optimizer has no step block")
        return tail[candidates[-1].end():stop]
    if not completed:
        raise ScienceInputError("native optimizer has no completed stop block")
    stop = completed[-1].start()
    starts = list(re.finditer(r"Convergence check\s*:", tail[:stop], re.I))
    if not starts:
        raise ScienceInputError("native completed optimizer has no Convergence check block")
    return tail[starts[-1].end():stop]


def _value_once(pattern: str, block: str, label: str) -> float:
    values = re.findall(pattern, block, re.I | re.M)
    if len(values) != 1:
        raise ScienceInputError(f"optimizer stop block has {len(values)} {label} values; expected one")
    value = float(values[0].replace("D", "E").replace("d", "e"))
    if not math.isfinite(value) or value < 0:
        raise ScienceInputError(f"optimizer stop block {label} is not finite and nonnegative")
    return value


def optimizer_sequence(output: str) -> tuple[list[float], list[int]]:
    """Return the complete native energy and optimizer-step sequence for either CP2K format."""
    energies = [float(value.replace("D", "E").replace("d", "e")) for value in re.findall(
        r"ENERGY\| Total FORCE_EVAL \( QS \) energy \[a\.u\.\]:\s*([-+\d.EeDd]+)", output)]
    legacy_steps = [int(value) for value in re.findall(
        r"Informations at step\s*=\s*(\d+)", output, re.I)]
    opt_steps = [int(value) for value in re.findall(
        r"(?im)^\s*OPT\|\s*Step number\s+(\d+)\s*$", output)]
    if legacy_steps and opt_steps:
        raise ScienceInputError("native output mixes legacy and OPT-format step records")
    step_ids = legacy_steps or opt_steps
    if (len(energies) < 2 or step_ids != list(range(len(step_ids)))
            or len(energies) != len(step_ids) + 1
            or any(not math.isfinite(value) for value in energies)):
        raise ScienceInputError("native optimizer ENERGY/step sequence is incomplete or inconsistent")
    return energies, step_ids


def optimizer_stop_values(tail: str) -> tuple[tuple[float, ...], tuple[float, ...], tuple[str, ...]]:
    """Normalize the last completed legacy or CP2K 2024.3 OPT stop block."""
    opt_format = bool(re.search(r"(?im)^\s*OPT\|\s*Step number\s+\d+\s*$", tail))
    block = _last_stop_block(tail)
    if opt_format:
        patterns = (
            r"OPT\|\s*Maximum step size\s+([-+\d.EeDd]+)",
            r"OPT\|\s*Convergence limit for maximum step size\s+([-+\d.EeDd]+)",
            r"OPT\|\s*RMS step size\s+([-+\d.EeDd]+)",
            r"OPT\|\s*Convergence limit for RMS step size\s+([-+\d.EeDd]+)",
            r"OPT\|\s*Maximum gradient\s+([-+\d.EeDd]+)",
            r"OPT\|\s*Convergence limit for maximum gradient\s+([-+\d.EeDd]+)",
            r"OPT\|\s*RMS gradient\s+([-+\d.EeDd]+)",
            r"OPT\|\s*Convergence limit for RMS gradient\s+([-+\d.EeDd]+)",
        )
        flag_patterns = (
            r"OPT\|\s*Maximum step size is converged\s+(YES|NO)",
            r"OPT\|\s*RMS step size is converged\s+(YES|NO)",
            r"OPT\|\s*Maximum gradient is converged\s+(YES|NO)",
            r"OPT\|\s*RMS gradient is converged\s+(YES|NO)",
        )
    else:
        patterns = (
            r"Max\. step size\s*=\s*([-+\d.EeDd]+)",
            r"Conv\. limit for step size\s*=\s*([-+\d.EeDd]+)",
            r"RMS step size\s*=\s*([-+\d.EeDd]+)",
            r"Conv\. limit for RMS step\s*=\s*([-+\d.EeDd]+)",
            r"Max\. gradient\s*=\s*([-+\d.EeDd]+)",
            r"Conv\. limit for gradients\s*=\s*([-+\d.EeDd]+)",
            r"RMS gradient\s*=\s*([-+\d.EeDd]+)",
            r"Conv\. limit for RMS grad\.\s*=\s*([-+\d.EeDd]+)",
        )
        flag_patterns = (r"Convergence in step size\s*=\s*(YES|NO)",
                         r"Convergence in RMS step\s*=\s*(YES|NO)",
                         r"Conv\. in gradients\s*=\s*(YES|NO)",
                         r"Conv\. in RMS gradients\s*=\s*(YES|NO)")
    values = tuple(_value_once(pattern, block, pattern) for pattern in patterns)
    flags = []
    for pattern in flag_patterns:
        found = re.findall(pattern, block, re.I)
        if len(found) != 1:
            raise ScienceInputError("native optimizer stop block lacks a unique convergence flag")
        flags.append(found[0].upper())
    return values[::2], values[1::2], tuple(flags)


def evaluate_optimizer_run(record_id: str, input_text: str, output_text: str) -> dict:
    """Recompute route, S1, native stop block and fixed optimizer criteria."""
    parts = record_id.split("/")
    if len(parts) != 3 or parts[1] not in {"GS", "ES"}:
        raise ScienceInputError(f"invalid route id: {record_id}")
    molecule, state, route = parts
    is_m14_default = record_id == "M14/ES/stda-pbe0-tzvp"
    tail = _last_invocation(output_text, allow_incomplete=is_m14_default)
    clean = "\n".join(line.split("!")[0].split("#")[0] for line in input_text.splitlines())
    global_body = re.search(r"(?is)&GLOBAL\b(.*?)&END\s+GLOBAL", clean)
    if not global_body or not re.search(r"(?im)^\s*RUN_TYPE\s+GEO_OPT\b", global_body.group(1)):
        raise ScienceInputError("effective input is not a GEO_OPT run")
    force_eval = _native._input_root_section(clean, "FORCE_EVAL")
    dft_body = _native._input_direct_section(force_eval, "DFT")
    if not dft_body:
        raise ScienceInputError("effective input has no DFT section")
    admm = _native._input_direct_section(dft_body, "AUXILIARY_DENSITY_MATRIX_METHOD")
    has_admm = bool(admm)
    admm_method = _native._input_direct_keyword_values(admm, "METHOD")
    admm_scaling = _native._input_direct_keyword_values(admm, "EXCH_SCALING_MODEL")
    properties = _native._input_direct_section(force_eval, "PROPERTIES")
    td = _native._input_direct_section(properties, "TDDFPT")
    stda = _native._input_direct_section(td, "STDA")
    has_stda = bool(stda)
    kernel = _native._input_direct_keyword_values(td, "KERNEL")
    fractions = _native._input_direct_keyword_values(stda, "FRACTION") if stda else []
    fraction = float(fractions[0].replace("D", "E").replace("d", "e")) if len(fractions) == 1 else None
    nstates = _native._input_direct_keyword_values(td, "NSTATES")
    triplets = _native._input_direct_keyword_values(td, "RKS_TRIPLETS")
    excited_sections = _native._input_direct_named_sections(dft_body, "EXCITED_STATES")
    excited_on = len(excited_sections) == 1 and (excited_sections[0][0] or "").upper() in {"T", "TRUE"}
    state_values = _native._input_direct_keyword_values(excited_sections[0][1], "STATE") if excited_on else []
    pbe0_ok = _native.pbe0_semantics(input_text) is not None

    expected_species = {"M2": {"C", "O", "H"}, "M3": {"C", "S", "H"},
                        "M14": {"C", "O", "CL", "H"}, "M19": {"C", "O", "H"},
                        "M29": {"C", "N", "H"}}[molecule]
    kind_basis = {}
    for match in re.finditer(r"(?ims)^\s*&KIND\s+([\w-]+)\b(.*?)^\s*&END(?:\s+KIND)?\b", clean):
        name, body = match.group(1), match.group(2)
        element = re.search(r"(?im)^\s*ELEMENT\s+([A-Za-z]{1,2})\s*$", body)
        species = (element.group(1) if element else re.match(r"[A-Za-z]+", name).group(0)).upper()
        if species in kind_basis:
            raise ScienceInputError(f"duplicate KIND definition: {species}")
        kind_basis[species] = re.findall(r"(?im)^\s*BASIS_SET\s+(ORB|AUX_FIT)\s+(\S+)", body)
    if not expected_species.issubset(kind_basis):
        raise ScienceInputError("effective KIND sections do not cover the frozen molecule topology")
    for species, assignments in kind_basis.items():
        orbitals = [basis.upper() for role, basis in assignments if role.upper() == "ORB"]
        auxiliaries = [basis.upper() for role, basis in assignments if role.upper() == "AUX_FIT"]
        if len(orbitals) != 1 or "TZVP-MOLOPT-PBE0-GTH" not in orbitals[0]:
            raise ScienceInputError(f"KIND {species} does not have exactly one frozen TZVP orbital basis")
        if has_admm and (len(auxiliaries) != 1 or "ADMM-TZP" not in auxiliaries[0]):
            raise ScienceInputError(f"active ADMM KIND {species} lacks exactly one frozen TZVP+tzp auxiliary basis")
    mgrid = _native._input_direct_section(dft_body, "MGRID")
    cutoff = _native._input_direct_keyword_values(mgrid, "CUTOFF")
    rel_cutoff = _native._input_direct_keyword_values(mgrid, "REL_CUTOFF")
    if has_admm and (admm_method != ["BASIS_PROJECTION"] or admm_scaling != ["NONE"]):
        raise ScienceInputError("active ADMM method or KIND basis is not the frozen BASIS_PROJECTION/TZVP+tzp family")
    if cutoff != ["800"] or rel_cutoff != ["80"]:
        raise ScienceInputError("effective MGRID cutoff differs from the frozen 800/80 profile")
    if route == "pbe0-tzvp":
        method_ok = not has_admm and not has_stda and pbe0_ok and (state != "ES" or kernel == ["FULL"])
    elif route == "admm-tzvp-tzp":
        method_ok = has_admm and not has_stda and pbe0_ok and (state != "ES" or kernel == ["FULL"])
    elif route == "stda-pbe0-tzvp":
        method_ok = (has_stda and not has_admm and pbe0_ok and kernel == ["sTDA"]
                     and nstates == ["1"] and len(fractions) == 1 and fraction is not None
                     and abs(fraction - 0.2) <= 1e-10)
    elif route == "stda-pbe0-tzvp-aex0.25-remedy":
        method_ok = (has_stda and not has_admm and pbe0_ok and kernel == ["sTDA"] and nstates == ["1"]
                     and len(fractions) == 1
                     and fraction is not None and abs(fraction - 0.25) <= 1e-10)
    else:
        raise ScienceInputError(f"unsupported route id: {record_id}")
    if not method_ok:
        raise ScienceInputError("effective input method does not match the requested route")
    if state == "ES" and (not excited_on or state_values != ["1"] or triplets != ["F"]):
        raise ScienceInputError("effective ES input must request singlet STATE 1 in the native excited-state sections")
    if state == "GS" and any((arg or "").upper() in {"T", "TRUE"} for arg, _body in excited_sections):
        raise ScienceInputError("GS input unexpectedly activates EXCITED_STATES")

    if state == "ES":
        if not ("R-TDDFPT states of multiplicity 1" in tail
                or "Spin symmetry of excitations Singlet" in tail):
            raise ScienceInputError("native last invocation lacks the singlet manifold marker")
        if is_m14_default:
            return {"id": record_id, "method_binding": "PASS", "s1_native_binding": "PASS",
                    "optimizer_status": "DIAGNOSTIC_REQUIRES_PHYSICAL_CLASSIFIER"}
        for name, pattern in (("SCF", r"SCF run (NOT )?converged"),
                              ("TDDFPT", r"TDDFPT run (NOT )?converged"),
                              ("linear solver", r"(?:The )?linear solver (NOT )?converged")):
            markers = re.findall(pattern, tail, re.I)
            if not markers or any(mark for mark in markers):
                raise ScienceInputError(f"native last invocation has missing/nonconverged {name} evidence")
    else:
        markers = re.findall(r"SCF run (NOT )?converged", tail, re.I)
        if not markers or any(markers):
            raise ScienceInputError("native last invocation has missing/nonconverged SCF evidence")

    if "PROGRAM ENDED AT" not in tail:
        raise ScienceInputError("native last invocation did not end normally")
    energies, step_ids = optimizer_sequence(tail)

    if "GEOMETRY OPTIMIZATION COMPLETED" not in tail:
        raise ScienceInputError("native last invocation did not complete geometry optimization")

    measured, limits, flags = optimizer_stop_values(tail)
    expected = M3_STDA_LIMITS if molecule == "M3" and route == "stda-pbe0-tzvp" else DEFAULT_LIMITS
    if any(abs(a - b) > 5.1e-11 for a, b in zip(limits, expected)):
        raise ScienceInputError(f"native optimizer limits differ from frozen profile: {limits}")
    if flags != ("YES", "YES", "YES", "YES"):
        raise ScienceInputError("native completed optimizer block lacks positive RMS convergence flags")
    if any(value > limit + 5.1e-11 for value, limit in zip(measured, limits)):
        raise ScienceInputError("native last optimizer criteria exceed their frozen limits")
    return {"id": record_id, "method_binding": "PASS", "s1_native_binding": "PASS" if state == "ES" else "not_applicable",
            "optimizer_status": "PASS", "optimizer_measured": measured, "optimizer_limits": limits,
            "optimizer_units": ["bohr", "bohr", "Ha/bohr", "Ha/bohr"],
            "native_energy_count": len(energies), "native_step_ids": step_ids}
