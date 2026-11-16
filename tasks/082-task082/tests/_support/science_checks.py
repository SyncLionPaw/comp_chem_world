"""Deterministic, printed-token checks for the case-07 native evidence.

This module intentionally contains no scientific accuracy thresholds.  It
checks only fixed task contracts and algebraic identities whose tolerance is
the rounding interval implied by the native tokens.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import math
import re
from typing import Any

SCHEMA = "bench12.case07.provenance/v1"
CASE_ID = "case-07-cof-excited-state-screening"
CRITERIA_VERSION = "case07-definition-2026-10-07"
EV_PER_HA_CODATA_2006 = Decimal("27.2113838565563")
FLOAT = r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[EeDd][-+]?\d+)?"
NUMBER_WITH_NONFINITE = rf"(?:{FLOAT}|[-+]?(?:nan|inf(?:inity)?))"
NATIVE_STATE_RE = re.compile(
    rf"^\s*TDDFPT\|\s+(\d+)\s+({FLOAT})\s+({FLOAT})\s+({FLOAT})\s+({FLOAT})\s+({FLOAT})\s*$",
    re.IGNORECASE,
)
NATIVE_STATE_PREFIX_RE = re.compile(r"^\s*TDDFPT\|\s+(\d+)\b", re.IGNORECASE)
SCF_TOTAL_RE = re.compile(rf"^\s*Total energy:\s*({FLOAT})\s*$", re.IGNORECASE)
FORCE_ENERGY_RE = re.compile(
    rf"^\s*ENERGY\|\s*Total FORCE_EVAL(?:\s*\([^)]*\))?\s+energy\s+\[(?:a\.u\.|hartree)\]\s*:?\s*({FLOAT})\s*$",
    re.IGNORECASE,
)
PROGRAM_ENDED_RE = re.compile(r"^.*PROGRAM ENDED AT.*$", re.IGNORECASE)
PROGRAM_STOPPED_RE = re.compile(r"^.*PROGRAM STOPPED IN.*$", re.IGNORECASE)
ABORT_RE = re.compile(r"\[ABORT\]|SCF run\s+not converged|TDDFPT run\s+not converged", re.IGNORECASE)


class ScienceCheckError(ValueError):
    """A deterministic candidate-evidence or schema failure."""


class UnsupportedFormat(ValueError):
    """The native format is outside the frozen automatic parser profile."""


def parse_xyz_frames(text: str, label: str) -> list[dict[str, Any]]:
    """Parse plain/extxyz coordinate frames without executing candidate code."""
    lines = text.splitlines()
    frames = []
    cursor = 0
    while cursor < len(lines):
        if not lines[cursor].strip():
            cursor += 1
            continue
        count_token = lines[cursor].strip()
        if not re.fullmatch(r"\d+", count_token):
            raise UnsupportedFormat(f"{label} is not a supported XYZ trajectory")
        count = int(count_token)
        if count <= 0 or cursor + count + 1 >= len(lines):
            raise ScienceCheckError(f"{label} has a truncated or empty XYZ frame")
        comment = lines[cursor + 1]
        atoms = []
        for offset in range(count):
            fields = lines[cursor + 2 + offset].split()
            if len(fields) < 4:
                raise ScienceCheckError(f"{label} has a malformed coordinate row")
            symbol = fields[0].strip().capitalize()
            coords = [decimal_token(x, f"{label} coordinate") for x in fields[1:4]]
            atoms.append({"element": symbol, "coords": coords,
                          "tokens": fields[1:4]})
        frames.append({"atom_count": count, "comment": comment, "atoms": atoms,
                       "line_start": cursor + 1, "line_end": cursor + count + 2})
        cursor += count + 2
    if not frames:
        raise ScienceCheckError(f"{label} contains no coordinate frames")
    if any(frame["atom_count"] != 192 for frame in frames):
        raise ScienceCheckError(f"{label} must contain 192 atoms in every frame")
    return frames


def compare_xyz_frames(first: dict[str, Any], last: dict[str, Any], label: str) -> dict[str, Any]:
    if first["atom_count"] != last["atom_count"] or len(first["atoms"]) != len(last["atoms"]):
        raise ScienceCheckError(f"{label} atom counts differ")
    max_difference = Decimal(0)
    if sorted(a["element"] for a in first["atoms"]) != sorted(b["element"] for b in last["atoms"]):
        raise ScienceCheckError(f"{label} elemental composition differs")
    if [a["element"] for a in first["atoms"]] != [b["element"] for b in last["atoms"]]:
        raise UnsupportedFormat(f"{label} atom ordering requires independent structure mapping")
    coordinate_differences = []
    for index, (a, b) in enumerate(zip(first["atoms"], last["atoms"]), 1):
        for axis, av, bv, at, bt in zip("xyz", a["coords"], b["coords"], a["tokens"], b["tokens"]):
            difference = abs(av - bv)
            envelope = half_ulp(at, f"{label} trajectory coordinate") + half_ulp(bt, f"{label} endpoint coordinate")
            if difference > envelope:
                coordinate_differences.append({"atom": index, "axis": axis,
                                               "delta_angstrom": str(difference)})
            max_difference = max(max_difference, difference)
    if coordinate_differences:
        raise UnsupportedFormat(f"{label} coordinate mapping/periodic wrapping requires independent review")
    return {"passed": True, "max_abs_coordinate_delta_angstrom": str(max_difference)}


def validate_gs_optimization(text: str, *, label: str) -> dict[str, Any]:
    lines = text.splitlines()
    boundaries = [(i + 1, m.group(1)) for i, line in enumerate(lines)
                  if (m := FORCE_ENERGY_RE.fullmatch(line))]
    if not boundaries:
        raise UnsupportedFormat(f"{label} has no recognized CP2K ENERGY boundary")
    reevaluations = [i + 1 for i, line in enumerate(lines) if "Reevaluating energy at the minimum" in line]
    if not reevaluations:
        raise UnsupportedFormat(f"{label} uses a minimum-endpoint format outside the automatic parser profile")
    last_line, total_token = boundaries[-1]
    if reevaluations[-1] >= last_line:
        raise ScienceCheckError(f"{label} final minimum marker is not before its endpoint energy")
    scf = [(i + 1, m.group(1)) for i, line in enumerate(lines[:last_line - 1])
           if (m := SCF_TOTAL_RE.fullmatch(line))]
    if not scf:
        raise ScienceCheckError(f"{label} final endpoint lacks a native E0 SCF total")
    if not any("GEOMETRY OPTIMIZATION COMPLETED" in line.upper() for line in lines):
        raise UnsupportedFormat(f"{label} optimization termination requires independent review")
    if not any(PROGRAM_ENDED_RE.fullmatch(line) for line in lines) or not any(PROGRAM_STOPPED_RE.fullmatch(line) for line in lines):
        raise ScienceCheckError(f"{label} lacks a normal program end")
    if any("[ABORT]" in line.upper() for line in lines):
        raise ScienceCheckError(f"{label} contains an abort record")
    convergence_review_reasons = _convergence_evidence(lines[:last_line - 1],
                                                       ("SCF", "outer SCF"), label)
    return {"energy_evaluations": len(boundaries), "endpoint_line": last_line,
            "endpoint_total_Ha_token": total_token, "endpoint_E0_Ha_token": scf[-1][1],
            "endpoint_E0_line": scf[-1][0], "minimum_reevaluation_line": reevaluations[-1],
            "normal_end": True, "convergence_review_reasons": convergence_review_reasons}


def decimal_token(token: str, label: str) -> Decimal:
    if not isinstance(token, str) or not token or "d" in token.lower():
        if not isinstance(token, str) or not token:
            raise ScienceCheckError(f"{label} is not a native numeric token")
    try:
        value = Decimal(token.replace("D", "E").replace("d", "e"))
    except InvalidOperation:
        raise ScienceCheckError(f"{label} is not a valid decimal token") from None
    if not value.is_finite():
        raise ScienceCheckError(f"{label} must be finite")
    return value


def half_ulp(token: str, label: str) -> Decimal:
    value = decimal_token(token, label)
    return Decimal(1).scaleb(value.as_tuple().exponent) / 2


def rounding_envelope(*tokens: tuple[str, str]) -> Decimal:
    """Conservative sum of independent printed-token half-ULPs."""
    return sum((half_ulp(token, label) for token, label in tokens), Decimal(0))


def _native_rows(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        match = NATIVE_STATE_RE.fullmatch(line)
        if match:
            state = int(match.group(1))
            energy = decimal_token(match.group(2), f"line {line_no} excitation energy")
            dipole = [decimal_token(match.group(i), f"line {line_no} dipole") for i in (3, 4, 5)]
            strength = decimal_token(match.group(6), f"line {line_no} oscillator strength")
            if state < 1 or energy <= 0 or strength < 0:
                raise ScienceCheckError(f"line {line_no} has invalid state ID, energy, or oscillator strength")
            rows.append({"state": state, "energy_eV": energy, "energy_token": match.group(2),
                         "dipole": dipole, "oscillator_strength": strength,
                         "oscillator_strength_token": match.group(6), "line": line_no})
    return rows


def _native_energies(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    total_rows, scf_rows = [], []
    for line_no, line in enumerate(text.splitlines(), 1):
        match = FORCE_ENERGY_RE.fullmatch(line)
        if match:
            total_rows.append({"token": match.group(1), "value_Ha": decimal_token(match.group(1), f"line {line_no} ENERGY"), "line": line_no})
        match = SCF_TOTAL_RE.fullmatch(line)
        if match:
            scf_rows.append({"token": match.group(1), "value_Ha": decimal_token(match.group(1), f"line {line_no} SCF total"), "line": line_no})
    return total_rows, scf_rows


def _convergence_evidence(lines: list[str], labels: tuple[str, ...], stage: str) -> list[str]:
    patterns = {
        "SCF": r"SCF run\s+(?:NOT\s+)?converged in",
        "outer SCF": r"outer SCF loop\s+(?:NOT\s+)?converged",
        "TDDFPT": r"TDDFPT run\s+(?:NOT\s+)?converged in",
    }
    missing = []
    for name in labels:
        events = [line for line in lines if re.search(patterns[name], line, re.IGNORECASE)]
        if not events:
            missing.append(f"{stage} lacks a recognized final {name} convergence record")
        elif re.search(r"\bNOT\s+converged\b", events[-1], re.IGNORECASE):
            raise ScienceCheckError(f"{stage} ends with {name} unconverged")
    return missing


def _checked_state_table(text: str, expected_count: int, label: str,
                         *, line_offset: int = 0) -> list[dict[str, Any]]:
    lines = text.splitlines()
    marker_re = re.compile(r"^\s*R-TDDFPT states of multiplicity\s+1\s*$", re.IGNORECASE)
    checksum_re = re.compile(r"^\s*TDDFPT\s*:\s*CheckSum\s*=", re.IGNORECASE)
    markers = [i for i, line in enumerate(lines) if marker_re.fullmatch(line)]
    checksums = [i for i, line in enumerate(lines) if checksum_re.match(line)]
    if not markers or not checksums:
        raise UnsupportedFormat(f"{label} state table markers are not supported by the automatic parser")
    # Stage callers pass one ENERGY-bounded evaluation at a time. A table must
    # have exactly one start and one close, with no second table hidden inside.
    if len(markers) != 1 or len(checksums) != 1 or checksums[0] <= markers[0]:
        raise ScienceCheckError(f"{label} must contain exactly one ordered singlet state table")
    rows = []
    for line_no in range(markers[0] + 1, checksums[0]):
        match = NATIVE_STATE_RE.fullmatch(lines[line_no])
        if match:
            state = int(match.group(1))
            energy = decimal_token(match.group(2), f"line {line_no + 1} excitation energy")
            dipole = [decimal_token(match.group(i), f"line {line_no + 1} dipole") for i in (3, 4, 5)]
            strength = decimal_token(match.group(6), f"line {line_no + 1} oscillator strength")
            if state < 1 or energy <= 0 or strength < 0:
                raise ScienceCheckError(f"line {line_no + 1} has invalid state ID, energy, or oscillator strength")
            rows.append({"state": state, "energy_eV": energy, "energy_token": match.group(2),
                         "dipole": dipole, "oscillator_strength": strength,
                         "oscillator_strength_token": match.group(6), "line": line_offset + line_no + 1})
        elif NATIVE_STATE_PREFIX_RE.match(lines[line_no]):
            # A state-like record in the canonical table that cannot be parsed
            # as finite native tokens is a candidate data defect, not an absent
            # optional row.
            fields = lines[line_no].split()
            for token in fields[2:]:
                if re.fullmatch(r"[-+]?(?:nan|inf(?:inity)?)", token, re.IGNORECASE):
                    decimal_token(token, f"line {line_offset + line_no + 1} state value")
            raise UnsupportedFormat(f"{label} contains an unsupported TDDFPT state-row representation")
    ids = [r["state"] for r in rows]
    expected = list(range(1, expected_count + 1))
    if ids != expected:
        raise ScienceCheckError(f"{label} native state IDs must be exactly ordered 1..{expected_count}")
    if any(a["line"] >= b["line"] for a, b in zip(rows, rows[1:])):
        raise ScienceCheckError(f"{label} native state table order is invalid")
    if any(a["energy_eV"] > b["energy_eV"] for a, b in zip(rows, rows[1:])):
        raise ScienceCheckError(f"{label} native excitation energies are not ordered")
    return rows


def validate_spectrum(text: str, *, kernel: str, label: str) -> dict[str, Any]:
    """Validate the raw 500-state table for a spectrum stage."""
    rows = _checked_state_table(text, 500, label)
    kernel_rows = re.findall(r"^\s*KERNEL\|\s*(?:Kernel\s+)?(FULL|STDA)\s*$", text, re.IGNORECASE | re.MULTILINE)
    # Some supported CP2K versions print the functional/kernel in different
    # places. The explicit schema's kernel remains reviewable; only an explicit
    # contradictory native declaration is a hard failure here.
    if kernel_rows and any(x.upper() != kernel.upper() for x in kernel_rows):
        raise ScienceCheckError(f"{label} native kernel contradicts its schema stage")
    if not kernel_rows:
        raise UnsupportedFormat(f"{label} native output does not expose a recognized kernel declaration")
    spin_rows = re.findall(r"^\s*KERNEL\|\s*Spin symmetry of excitations\s+(Singlet|Triplet)\s*$",
                           text, re.IGNORECASE | re.MULTILINE)
    if spin_rows and any(x.upper() != "SINGLET" for x in spin_rows):
        raise ScienceCheckError(f"{label} native output declares a non-singlet excitation")
    if not spin_rows:
        raise UnsupportedFormat(f"{label} native output does not expose a recognized spin declaration")
    convergence_review_reasons = _convergence_evidence(text.splitlines(),
                                                       ("SCF", "outer SCF", "TDDFPT"), label)
    return {"kernel": kernel, "state_count": len(rows), "state_ids": [r["state"] for r in rows],
            "state_rows": rows, "first_state_line": rows[0]["line"], "last_state_line": rows[-1]["line"],
            "convergence_review_reasons": convergence_review_reasons}


def validate_s1_trajectory(text: str, *, kernel: str, label: str) -> dict[str, Any]:
    """Extract each optimization evaluation's 8 states and endpoint energies.

    This is necessary record validation. State continuity and minimum quality
    remain independent-review criteria.
    """
    lines = text.splitlines()
    kernel_rows = re.findall(r"^\s*KERNEL\|\s*(?:Kernel\s+)?(FULL|STDA)\s*$", text, re.IGNORECASE | re.MULTILINE)
    spin_rows = re.findall(r"^\s*KERNEL\|\s*Spin symmetry of excitations\s+(Singlet|Triplet)\s*$",
                           text, re.IGNORECASE | re.MULTILINE)
    if not kernel_rows or not spin_rows:
        raise UnsupportedFormat(f"{label} native kernel/spin declaration is outside the automatic parser profile")
    if any(x.upper() != kernel.upper() for x in kernel_rows):
        raise ScienceCheckError(f"{label} native kernel contradicts its schema stage")
    if any(x.upper() != "SINGLET" for x in spin_rows):
        raise ScienceCheckError(f"{label} native output declares a non-singlet excitation")
    energy_matches = [(i + 1, FORCE_ENERGY_RE.fullmatch(line)) for i, line in enumerate(lines)]
    bounds = [(line, match.group(1)) for line, match in energy_matches if match]
    if not bounds:
        raise ScienceCheckError(f"{label} has no native ENERGY boundary")
    evaluations = []
    convergence_review_reasons: list[str] = []
    previous = 0
    for j, (line_no, energy_token) in enumerate(bounds):
        end = line_no
        next_line = bounds[j + 1][0] if j + 1 < len(bounds) else len(lines) + 1
        segment = "\n".join(lines[previous:end])
        states = _checked_state_table(segment, 8, f"{label} evaluation {j + 1}", line_offset=previous)
        scf = [(i + 1, m.group(1)) for i, line in enumerate(lines[previous:end])
               if (m := SCF_TOTAL_RE.fullmatch(line))]
        if not scf:
            raise ScienceCheckError(f"{label} evaluation {j + 1} lacks a native E0 SCF total")
        scf_global_line = previous + scf[-1][0]
        if scf_global_line >= line_no:
            raise ScienceCheckError(f"{label} evaluation {j + 1} E0/S1 total ordering is invalid")
        evaluations.append({"line_start": previous + 1, "line_end": line_no,
                            "total_Ha_token": energy_token,
                            "total_Ha": decimal_token(energy_token, f"{label} S1 total"),
                            "e0_Ha_token": scf[-1][1],
                            "e0_Ha": decimal_token(scf[-1][1], f"{label} E0"),
                            "e0_line": scf_global_line,
                            "state_rows": states})
        previous = line_no
        if next_line <= line_no:
            raise ScienceCheckError(f"{label} evaluation boundaries are not ordered")
    ended = any(PROGRAM_ENDED_RE.fullmatch(x) for x in lines)
    stopped = any(PROGRAM_STOPPED_RE.fullmatch(x) for x in lines)
    if not ended or not stopped or any("[ABORT]" in x.upper() for x in lines):
        raise ScienceCheckError(f"{label} native execution is incomplete, aborted, or unconverged")
    reevaluations = [i + 1 for i, line in enumerate(lines) if "Reevaluating energy at the minimum" in line]
    if not reevaluations:
        raise UnsupportedFormat(f"{label} minimum-endpoint format requires independent review")
    if reevaluations[-1] >= bounds[-1][0]:
        raise ScienceCheckError(f"{label} lacks a final minimum reevaluation before its last energy boundary")
    if not any("GEOMETRY OPTIMIZATION COMPLETED" in line.upper() for line in lines):
        raise UnsupportedFormat(f"{label} native optimizer termination requires independent review")
    # Fail only when the final convergence record in an evaluation is negative;
    # intermediate failed attempts may be followed by a converged retry.
    for index, ev in enumerate(evaluations):
        left, right = ev["line_start"] - 1, ev["line_end"]
        segment_lines = lines[left:right]
        for pattern, label_name in ((r"SCF run\s+(?:NOT\s+)?converged in", "SCF"),
                                    (r"outer SCF loop\s+(?:NOT\s+)?converged", "outer SCF"),
                                    (r"TDDFPT run\s+(?:NOT\s+)?converged in", "TDDFPT")):
            events = [(n, line) for n, line in enumerate(segment_lines, 1)
                      if re.search(pattern, line, re.IGNORECASE)]
            if label_name == "outer SCF" and not events:
                convergence_review_reasons.append(f"{label} evaluation {index + 1} lacks a recognized outer SCF convergence record")
                continue
            if not events:
                convergence_review_reasons.append(f"{label} evaluation {index + 1} lacks a recognized {label_name} convergence record")
                continue
            final_event = events[-1][1]
            if re.search(r"\bNOT\s+converged\b", final_event, re.IGNORECASE):
                raise ScienceCheckError(f"{label} evaluation {index + 1} ends with {label_name} unconverged")
    for ev in evaluations:
        omega = ev["state_rows"][0]["energy_eV"]
        implied = (ev["total_Ha"] - ev["e0_Ha"]) * EV_PER_HA_CODATA_2006
        envelope = rounding_envelope((ev["total_Ha_token"], f"{label} S1 total"),
                                     (ev["e0_Ha_token"], f"{label} E0")) * EV_PER_HA_CODATA_2006
        omega_envelope = half_ulp(ev["state_rows"][0]["energy_token"], f"{label} omega")
        ev["same_evaluation_energy_identity"] = {
            "implied_omega_eV": str(implied), "printed_omega_eV": str(omega),
            "rounding_envelope_eV": str(envelope + omega_envelope),
            "within_printed_rounding": abs(implied - omega) <= envelope + omega_envelope,
            "interpretation": "Differences beyond printed rounding require numerical-error review; they are not by themselves a physical failure."}
    endpoint = evaluations[-1]
    return {"kernel": kernel, "evaluation_count": len(evaluations), "evaluations": evaluations,
            "endpoint": endpoint,
            "convergence_review_reasons": convergence_review_reasons,
            "same_evaluation_identity_review_required": any(
                not ev["same_evaluation_energy_identity"]["within_printed_rounding"] for ev in evaluations)}


def energy_summary(gs_e0_token: str, gs_state1_token: str, s1_total_token: str,
                   s1_e0_token: str, s1_omega_token: str) -> dict[str, str]:
    """Derive Evert, electronic Ead, Efl, and Stokes from native tokens.

    Ead uses the S1 total directly; adding omega to that total would double
    count the excitation energy.
    """
    e0gs = decimal_token(gs_e0_token, "GS minimum E0")
    evert_ev = decimal_token(gs_state1_token, "GS-geometry omega1")
    es1 = decimal_token(s1_total_token, "S1 endpoint total")
    e0es = decimal_token(s1_e0_token, "S1 endpoint E0")
    efl_ev = decimal_token(s1_omega_token, "S1 endpoint omega1")
    with localcontext() as context:
        context.prec = 50
        ead_ev = (es1 - e0gs) * EV_PER_HA_CODATA_2006
        # Same-stage identity also guards a corrupted mapping of E0/omega.
        endpoint_implied = (es1 - e0es) * EV_PER_HA_CODATA_2006
        stokes = evert_ev - efl_ev
    return {"Evert_eV": str(evert_ev), "Ead_electronic_eV": str(ead_ev),
            "Efl_eV": str(efl_ev), "Stokes_eV": str(stokes),
            "S1_endpoint_implied_omega_eV": str(endpoint_implied)}


def compare_reported(reported: dict[str, Any], derived: dict[str, str],
                     rounding_envelopes: dict[str, str], *,
                     profile_precision: dict[str, int] | None = None) -> dict[str, Any]:
    """Compare reported table tokens against native-derived quantities.

    The caller supplies a dimensionally converted native-token envelope. The
    candidate token's own half-ULP is added so honest table rounding passes.
    An over-coarse table is review-required rather than a widened tolerance.
    """
    checks = {}
    for field, formula in derived.items():
        if field not in reported or field not in rounding_envelopes:
            raise ScienceCheckError(f"reported table lacks required field {field}")
        token = reported[field]
        if not isinstance(token, str):
            raise ScienceCheckError(f"reported {field} must preserve its printed decimal token")
        value = decimal_token(token, f"reported {field}")
        expected = decimal_token(formula, f"derived {field}")
        native_envelope = decimal_token(rounding_envelopes[field], f"{field} native rounding envelope")
        report_envelope = half_ulp(token, f"reported {field}")
        declared_places = (profile_precision or {}).get(field)
        places = max(0, -value.as_tuple().exponent)
        if declared_places is not None and places < declared_places:
            raise UnsupportedFormat(f"reported {field} precision is below the frozen automatic-comparison profile")
        envelope = native_envelope + report_envelope
        if abs(value - expected) > envelope:
            raise ScienceCheckError(f"reported {field} differs from native-token result beyond its rounding envelope")
        checks[field] = {"reported_token": token, "derived": str(expected),
                         "native_rounding_envelope": str(native_envelope),
                         "reported_rounding_envelope": str(report_envelope),
                         "total_rounding_envelope": str(envelope), "passed": True}
    return checks


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
