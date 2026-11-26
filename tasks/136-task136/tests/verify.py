#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: reconcile published TNEP values and conventions.
"""Scorer for case-04: published results and convention reconciliation.

Exit codes: 0 = PASS, 1 = FAIL, 2 = environment error.
Anchors below were transcribed and cross-checked from the official PDFs shipped
in tests/refs/ (grader-only; frozen 2026-10-05).
"""
import json
import ast
from fractions import Fraction
import os
import re
import sys
from pathlib import Path

import math

# --- inlined from the former tests/validation.py ------------------------------
import hashlib
import json
import math
from pathlib import Path


def object_json(path, on_error):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError(f"duplicate JSON key: {key}")
            out[key] = value
        return out
    try:
        obj = json.loads(path.read_text(), object_pairs_hook=pairs,
                         parse_constant=lambda s: (_ for _ in ()).throw(ValueError(f"non-finite JSON: {s}")))
        if not isinstance(obj, dict):
            raise ValueError("JSON root must be an object")
        return obj
    except Exception as exc:
        on_error(f"{path.name} unreadable or malformed: {exc}")


def mapping(value, what, on_error):
    if not isinstance(value, dict):
        on_error(f"{what} must be an object")
    return value


def text(value, what, on_error):
    if not isinstance(value, str) or not value.strip():
        on_error(f"{what} must be a nonempty string")
    return value


def number(value, what, on_error):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        on_error(f"{what} must be a finite number")
    return float(value)


def inside(final, rel, on_error):
    text(rel, "artifact path", on_error)
    path = final / rel
    if path.is_symlink():
        on_error(f"symbolic-link artifact is not allowed: {rel}")
    resolved = path.resolve()
    if not resolved.is_relative_to(final.resolve()) or resolved == final.resolve():
        on_error(f"artifact path escapes submission dir: {rel}")
    return resolved


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_file(path, expected, on_error):
    try:
        if not path.is_file() or digest(path) != expected:
            on_error(f"frozen evaluation asset missing or SHA-256 mismatch: {path.name}")
    except OSError as exc:
        on_error(f"frozen evaluation asset unreadable: {path.name}: {exc}")


def engine_logs(final, engine, on_error):
    mapping(engine, "engine", on_error)
    for key in ("name", "version", "build_command"):
        text(engine.get(key), f"engine.{key}", on_error)
    hashes = mapping(engine.get("log_sha256"), "engine.log_sha256", on_error)
    for name in ("build.log", "run.log"):
        path = inside(final, name, on_error)
        try:
            if not path.is_file() or not path.read_text().strip():
                on_error(f"missing or empty {name}")
            if hashes.get(name) != digest(path):
                on_error(f"engine.log_sha256 does not match {name}")
        except (OSError, UnicodeError) as exc:
            on_error(f"cannot read {name}: {exc}")

val = sys.modules[__name__]  # the helpers above, addressed as before

REFERENCE_CONTRACT_SHA256 = '688d90524dcfafcfaacaa4ad101cc86f2ac6317851e4c302b239bc3339aa81b5'


class SubmissionError(Exception):
    pass


class InfrastructureError(Exception):
    pass


def fail(msg):
    raise SubmissionError(msg)


def infra(msg):
    raise InfrastructureError(msg)


def load_contract():
    path = Path(__file__).resolve().parent / "refs.json"
    val.frozen_file(path, REFERENCE_CONTRACT_SHA256, infra)
    contract = val.object_json(path, infra)
    if contract.get("contract_version") != 1:
        infra("unsupported scoring contract version")
    rows = contract.get("anchors")
    topics = contract.get("convention_topics")
    documents = contract.get("documents_sha256")
    if not isinstance(rows, list) or not isinstance(topics, dict) or not isinstance(documents, dict):
        infra("scoring contract is missing anchors, convention topics, or document hashes")
    anchors, specs = {}, {}
    for row in rows:
        if not isinstance(row, dict):
            infra("scoring contract anchor must be an object")
        table, cell = row.get("table"), row.get("cell")
        value, tolerance = row.get("value"), row.get("relative_tolerance")
        unit = row.get("expected_unit")
        if not all(isinstance(x, str) and x for x in (table, cell, unit)):
            infra("scoring contract anchor has invalid table, cell, or unit")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            infra("scoring contract anchor has invalid value")
        if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or tolerance < 0:
            infra("scoring contract anchor has invalid relative tolerance")
        entity = row.get("count_entity")
        if entity is not None and (not isinstance(entity, str) or not entity):
            infra("scoring contract anchor has invalid count entity")
        if not isinstance(row.get("percent_allowed"), bool):
            infra("scoring contract anchor has invalid percent flag")
        key = (table, cell)
        if key in anchors:
            infra(f"duplicate scoring contract anchor: {key}")
        anchors[key] = (float(value), float(tolerance))
        specs[key] = row
    for topic, keywords in topics.items():
        if not isinstance(topic, str) or not topic or not isinstance(keywords, list) or \
           any(not isinstance(keyword, str) or not keyword for keyword in keywords):
            infra("scoring contract convention topic is malformed")
    for name, expected in documents.items():
        if not isinstance(name, str) or not name or not isinstance(expected, str) or \
           not re.fullmatch(r"[0-9a-f]{64}", expected):
            infra("scoring contract document hash is malformed")
    return anchors, specs, topics, documents

def norm(s):
    return (str(s).casefold().replace("²", "2").replace("³", "3").replace("⁻", "-")
            .replace("¹", "1")
            .replace("₀", "0").replace("₂", "2").replace("⁴", "4")
            .replace("ᵣ", "r").replace("−", "-").replace("ϵ", "epsilon")
            .replace("χ", "chi").replace("μ", "mu")
            .replace("α", "alpha").replace("ρ", "rho").replace("ε", "epsilon"))


def polynomial_add(left, right, sign=1):
    result = dict(left)
    for powers, coefficient in right.items():
        result[powers] = result.get(powers, Fraction(0)) + sign * coefficient
        if result[powers] == 0:
            del result[powers]
        elif (result[powers].numerator.bit_length() > 4096 or
              result[powers].denominator.bit_length() > 4096):
            fail("equation coefficient exceeds the supported size")
    return result


def polynomial_multiply(left, right):
    result = {}
    for lp, lc in left.items():
        for rp, rc in right.items():
            powers = tuple(a + b for a, b in zip(lp, rp))
            if max(powers, default=0) > 12:
                fail("equation exceeds the bounded polynomial degree")
            result[powers] = result.get(powers, Fraction(0)) + lc * rc
            if result[powers] == 0:
                del result[powers]
            elif (result[powers].numerator.bit_length() > 4096 or
                  result[powers].denominator.bit_length() > 4096):
                fail("equation coefficient exceeds the supported size")
    if len(result) > 256:
        fail("equation exceeds the bounded polynomial size")
    return result


def polynomial_power(value, exponent):
    if exponent < 0 or exponent > 6:
        fail("equation exponent is outside the supported bound")
    result = {(0, 0, 0, 0): Fraction(1)}
    for _ in range(exponent):
        result = polynomial_multiply(result, value)
    return result


def equation_polynomial(expression):
    if not isinstance(expression, str) or len(expression) > 512 or expression.count("=") != 1:
        fail("equation must be a bounded equality with one equals sign")
    left_text, right_text = expression.split("=", 1)
    aliases = {
        "chi": "chi", "chi_e": "chi", "rho": "rho", "alpha": "alpha",
        "epsilon0": "epsilon0", "epsilon_0": "epsilon0", "eps0": "epsilon0",
        "eps_0": "epsilon0", "epsilon_r": "epsilon_r", "epsilonr": "epsilon_r",
        "eps_r": "epsilon_r", "epsr": "epsilon_r",
    }
    variables = {name: tuple(1 if i == j else 0 for i in range(4))
                 for j, name in enumerate(("chi", "rho", "alpha", "epsilon0"))}

    def parse(text):
        text = text.replace("^", "**")
        try:
            tree = ast.parse(text.strip(), mode="eval")
        except (SyntaxError, ValueError, MemoryError, RecursionError):
            fail("equation is not in the supported arithmetic syntax")
        nodes = list(ast.walk(tree))
        if len(nodes) > 64:
            fail("equation exceeds the bounded syntax size")

        def visit(node):
            if isinstance(node, ast.Expression):
                return visit(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                if abs(node.value) > 1_000_000:
                    fail("equation constant exceeds the supported bound")
                return ({(0, 0, 0, 0): Fraction(str(node.value))},
                        {(0, 0, 0, 0): Fraction(1)})
            if isinstance(node, ast.Name):
                name = aliases.get(node.id.casefold())
                if name == "epsilon_r":
                    chi = {(1, 0, 0, 0): Fraction(1)}
                    one = {(0, 0, 0, 0): Fraction(1)}
                    return polynomial_add(chi, one), one
                if name not in variables:
                    fail("equation contains an unsupported symbol")
                return {variables[name]: Fraction(1)}, {(0, 0, 0, 0): Fraction(1)}
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                num, den = visit(node.operand)
                return (num if isinstance(node.op, ast.UAdd) else
                        {k: -v for k, v in num.items()}), den
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
                an, ad = visit(node.left)
                bn, bd = visit(node.right)
                if isinstance(node.op, ast.Add):
                    return polynomial_add(polynomial_multiply(an, bd), polynomial_multiply(bn, ad)), polynomial_multiply(ad, bd)
                if isinstance(node.op, ast.Sub):
                    return polynomial_add(polynomial_multiply(an, bd), polynomial_multiply(bn, ad), -1), polynomial_multiply(ad, bd)
                if isinstance(node.op, ast.Mult):
                    return polynomial_multiply(an, bn), polynomial_multiply(ad, bd)
                if isinstance(node.op, ast.Div):
                    if not bn:
                        fail("equation divides by zero")
                    return polynomial_multiply(an, bd), polynomial_multiply(ad, bn)
                exponent_node = node.right
                if isinstance(exponent_node, ast.UnaryOp) and isinstance(exponent_node.op, (ast.UAdd, ast.USub)):
                    constant = exponent_node.operand
                    if not isinstance(constant, ast.Constant) or not isinstance(constant.value, int) or isinstance(constant.value, bool):
                        fail("equation powers must be bounded integers")
                    exponent = constant.value * (-1 if isinstance(exponent_node.op, ast.USub) else 1)
                elif isinstance(exponent_node, ast.Constant) and isinstance(exponent_node.value, int) and not isinstance(exponent_node.value, bool):
                    exponent = exponent_node.value
                else:
                    fail("equation powers must be bounded integers")
                if abs(exponent) > 6:
                    fail("equation exponent is outside the supported bound")
                if exponent < 0:
                    if not an:
                        fail("equation divides by zero")
                    return polynomial_power(ad, -exponent), polynomial_power(an, -exponent)
                return polynomial_power(an, exponent), polynomial_power(ad, exponent)
            fail("equation contains unsupported syntax")

        return visit(tree)

    left_num, left_den = parse(left_text)
    right_num, right_den = parse(right_text)
    return polynomial_add(polynomial_multiply(left_num, right_den),
                          polynomial_multiply(right_num, left_den), -1)


def cm_equation_matches(equation):
    normalized = norm(equation)
    submitted = equation_polynomial(normalized)
    target = equation_polynomial("3*epsilon0*chi = rho*alpha*(chi+3)")
    if not submitted or not target or set(submitted) != set(target):
        return False
    first = next(iter(target))
    scale = submitted[first] / target[first]
    return scale != 0 and all(submitted[p] == scale * target[p] for p in target)


def bounded_prefix_factor(units):
    text = norm(units).replace("×", "*").replace("·", "*").replace("å", "angstrom")
    scale_pattern = (r"\s*(?:10\s*\^\s*(?:\{\s*([+-]?\d+)\s*\}|"
                     r"\(\s*([+-]?\d+)\s*\)|([+-]?\d+))|1e([+-]?\d+))\s*[*·]?\s*")
    scale = re.match(scale_pattern, text)
    if not scale:
        return 1.0, text
    exponent = int(next(group for group in scale.groups() if group is not None))
    if abs(exponent) > 12:
        return None, text[scale.end():]
    return 10.0 ** exponent, text[scale.end():]


def unit_factor_and_family(units, expected_unit, *, percent_allowed=False):
    factor, text = bounded_prefix_factor(units)
    if factor is None:
        return None
    if expected_unit == "1":
        dimensionless = re.fullmatch(
            r"\s*(?:1|dimensionless|unitless|无量纲)\s*"
            r"(?:\(\s*([^()]+?)\s*\))?\s*",
            text,
            flags=re.IGNORECASE,
        )
        if dimensionless:
            return factor, expected_unit
    compact = re.sub(r"\s+", "", text).replace("·", "*").replace("×", "*")
    compact = compact.replace("{", "").replace("}", "")
    compact = compact.replace("a_0", "bohr").replace("a0", "bohr")
    compact = compact.replace("bohr3", "bohr^3")
    compact = compact.replace("atom^-1", "/atom").replace("atom-1", "/atom")
    compact = compact.replace("*/", "/")
    compact = compact.replace("cm-1", "cm^-1").replace("1/cm", "cm^-1")
    compact = compact.replace("e*bohr", "ebohr").replace("ebohr", "e*bohr")
    compact = compact.replace("bohr^3", "bohr3").replace("cm^(-1)", "cm-1").replace("cm^-1", "cm-1")
    compact = compact.replace("bohr**3", "bohr3").replace("cm**(-1)", "cm-1")
    compact = compact.replace(".", "")
    expected = expected_unit.replace("^", "")
    if compact in {"au", "atomicunit", "atomicunits", "au/atom", "atomicunit/atom", "atomicunits/atom"}:
        if expected_unit in {"e*bohr", "bohr^3", "e*bohr/atom", "bohr^3/atom"}:
            if expected_unit.endswith("/atom") != compact.endswith("/atom"):
                return None
            return factor, expected_unit
    if compact in {"%", "percent"} and percent_allowed:
        return factor * 0.01, "1"
    if compact == expected:
        return factor, expected_unit
    if expected_unit == "e*bohr" and compact == "ebohr":
        return factor, expected_unit
    if expected_unit == "bohr^3" and compact in {"bohr3"}:
        return factor, expected_unit
    if expected_unit == "bohr^3/atom" and compact == "bohr3/atom":
        return factor, expected_unit
    if expected_unit == "e*bohr/atom" and compact == "e*bohr/atom":
        return factor, expected_unit
    if expected_unit == "cm^-1" and compact == "cm-1":
        return factor, expected_unit
    if expected_unit == "angstrom" and compact in {"angstrom", "å"}:
        return factor, expected_unit
    if expected_unit == "1" and compact in {"1", "dimensionless", "unitless", "无量纲"}:
        return factor, expected_unit
    return None


def count_unit_matches(units, expected_entity):
    """Accept dimensionless counts or the exact entity named by this cell."""
    allowed = {
        "neuron": {"count", "counts", "neuron", "neurons"},
        "generation": {"count", "counts", "generation", "generations"},
        "individual": {"count", "counts", "individual", "individuals"},
        "structure": {"count", "counts", "structure", "structures", "configuration", "configurations"},
        "count": {"count", "counts"},
    }
    dimensionless = {"1", "dimensionless", "unitless", "无量纲", "count", "counts"}
    accepted = allowed.get(expected_entity, set()) | dimensionless
    match = re.fullmatch(r"\s*([^()]+?)\s*(?:\(\s*([^()]+?)\s*\))?\s*", norm(units))
    if not match:
        return False
    primary = re.sub(r"[\s_-]+", "", match.group(1)).strip()
    annotation = (re.sub(r"[\s_-]+", "", match.group(2)).strip()
                  if match.group(2) is not None else None)
    if primary in dimensionless:
        return annotation is None or bool(annotation)
    return primary in accepted and (annotation is None or annotation in accepted)


def count_unit_factor_and_family(units, expected_entity):
    factor, unit_text = bounded_prefix_factor(units)
    if factor is None or not count_unit_matches(unit_text, expected_entity):
        return None
    return factor, expected_entity


def si_unit_canonical(units):
    text = str(units).strip().replace("·", "*").replace("⋅", "*")
    text = text.replace("²", "^2").replace("−", "-").replace("⁻", "-").replace("¹", "1")
    text = re.sub(r"\s*([*/^()])\s*", r"\1", text)
    return re.sub(r"\s+", "*", text)


def main():
    anchors, anchor_specs, convention_topics, input_hashes = load_contract()
    inputs = Path(os.environ.get("NEP_DOCUMENT_ROOT", Path(__file__).resolve().parent / "refs"))
    for name, expected in input_hashes.items():
        val.frozen_file(inputs / name, expected, infra)

    final = Path(os.environ.get("APP", "/app/final"))
    path = final / "reconciliation.json"
    if not path.is_file():
        fail("missing reconciliation.json")
    sub = val.object_json(path, fail)
    for key in ("values", "normalized", "conventions", "unsupported"):
        if not isinstance(sub.get(key), list):
            if key == "normalized" and isinstance(sub.get(key), dict):
                continue
            fail(f"missing or invalid key: {key}")

    # Closed, structured scientific assertions make the rubric auditable and
    # catch explicit contradictions; prose keyword coverage alone cannot do so.
    normed = sub["normalized"]
    if not isinstance(normed, dict):
        fail("normalized must be an object")
    topic_fields = set(convention_topics)
    if set(normed) != topic_fields:
        fail("normalized must contain exactly the five fixed topics")
    liquid = val.mapping(normed["liquid water dipole normalization"], "normalized.liquid water dipole normalization", fail)
    liquid_entity_raw = norm(liquid.get("entity", "")).replace("-", " ").replace("_", " ").strip()
    liquid_entity = re.split(r"[(\[;,]", liquid_entity_raw, maxsplit=1)[0].strip()
    liquid_allowed = {"water molecule", "water molecules", "h2o molecule", "h2o molecules",
                      "molecule", "molecules"}
    if liquid_entity not in liquid_allowed and not any(
            liquid_entity_raw == allowed or liquid_entity_raw.startswith(allowed + " ")
            for allowed in liquid_allowed):
        fail("liquid-water normalization structured answer is inconsistent")
    if "count" in liquid:
        count = val.number(liquid["count"], "liquid-water normalization count", fail)
        if count < 0 or not count.is_integer():
            fail("liquid-water normalization count note must be a non-negative integer")
    qm = val.mapping(normed["qm7b normalization"], "normalized.qm7b normalization", fail)
    qm_entity = norm(qm.get("denominator_entity", "")).replace("-", " ").replace("_", " ").strip()
    if qm_entity not in {"atom", "atoms", "per atom", "per atoms"}:
        fail("QM7B normalization structured answer is inconsistent")
    units = val.mapping(normed["unit conventions"], "normalized.unit conventions", fail)
    mu_unit = val.text(units.get("mu"), "normalized.unit conventions.mu", fail)
    alpha_unit = val.text(units.get("alpha"), "normalized.unit conventions.alpha", fail)
    chi_unit = val.text(units.get("chi"), "normalized.unit conventions.chi", fail)
    mu_au = unit_factor_and_family(mu_unit, "e*bohr")
    alpha_au = unit_factor_and_family(alpha_unit, "bohr^3")
    chi = unit_factor_and_family(chi_unit, "1")
    mu_si = si_unit_canonical(mu_unit) == "C*m/mol"
    alpha_si = si_unit_canonical(alpha_unit) in {
        "F*m^2/mol", "C*m^2/(V*mol)", "C*m^2/V/mol", "C*m^2*V^-1/mol",
    }
    if chi is None or chi[0] != 1.0 or not (
        (mu_au is not None and mu_au[0] == 1.0 and alpha_au is not None and alpha_au[0] == 1.0)
        or (mu_si and alpha_si)
    ):
        fail("unit conventions structured answer is inconsistent")
    cm = val.mapping(normed["clausius-mossotti"], "normalized.clausius-mossotti", fail)
    equation = cm.get("equation", "")
    applicability = {norm(x).replace("_", " ").replace("-", " ").strip()
                     for x in cm.get("applicability", [])} if isinstance(cm.get("applicability"), list) else set()
    # Interpret only the condition's leading clause; parenthesized text may
    # explain terminology but must not introduce the applicability itself.
    condition_heads = [x.split("(", 1)[0].strip() for x in applicability]
    has_nonpolar = any(re.search(r"\bnon\s*polar\b", x) for x in condition_heads)
    has_scalar_model = any(re.search(r"\b(?:isotropic|scalars?)\b", x) for x in condition_heads)
    def contradicts_condition(text):
        polar_excluded = bool(re.search(
            r"\b(?:not\s+polar|does\s+not\s+apply\s+to\s+polar|excludes?\s+polar)\b", text))
        anisotropic_excluded = bool(re.search(
            r"\b(?:not\s+anisotropic|does\s+not\s+apply\s+to\s+anisotropic|excludes?\s+anisotropic)\b", text))
        negative_required_property = bool(re.search(
            r"\b(?:not|no|without)\s+(?:(?:any|the)\s+)?(?:non\s*polar|isotropic|scalars?)\b", text))
        polar_conflict = bool(re.search(r"\bpolar\b", text)) and not (
            re.search(r"\bnon\s*polar\b", text) or polar_excluded)
        anisotropic_conflict = bool(re.search(r"\banisotropic\b", text)) and not anisotropic_excluded
        return negative_required_property or polar_conflict or anisotropic_conflict

    contradiction = any(contradicts_condition(x) for x in applicability)
    try:
        equation_ok = cm_equation_matches(equation)
    except SubmissionError:
        raise
    except Exception:
        equation_ok = False
    if not equation_ok or not has_nonpolar or not has_scalar_model or contradiction:
        fail("Clausius-Mossotti equation or applicability structured answer is inconsistent")
    reconstruct = val.mapping(normed["chi/rho reconstructability"], "normalized.chi/rho reconstructability", fail)
    if reconstruct.get("unique") is not False or not isinstance(reconstruct.get("reason"), str) or not reconstruct["reason"].strip():
        fail("chi/rho reconstructability structured answer is inconsistent")

    # index agent values by (table, cell), tolerant to case/whitespace
    got = {}
    for v in sub["values"]:
        try:
            key = (norm(v["table"]).strip(), norm(v["cell"]).strip())
            if key in got:
                fail(f"duplicate value entry: {key}")
            value = val.number(v.get("value"), f"value {key}", fail)
            units = val.text(v.get("units"), f"units {key}", fail)
            val.text(v.get("provenance"), f"provenance {key}", fail)
            got[key] = (value, units)
        except Exception:
            fail(f"malformed value entry: {v}")

    missing, wrong = [], []
    for key, (anchor, tol) in anchors.items():
        k1 = (norm(key[0]), norm(key[1]))
        candidates = [k1,
                      (k1[0].replace("table ", "table"), k1[1]),
                      (k1[0], k1[1].replace(" ", "-")),
                      (k1[0], k1[1].replace(" ", "_"))]
        value = None
        for c in candidates:
            if c in got:
                value, units = got[c]
                spec = anchor_specs[key]
                expected_unit = spec["expected_unit"]
                expected_count_entity = spec["count_entity"]
                percent_allowed = spec["percent_allowed"]
                unit_text = units
                if "liquid water" in key[1]:
                    unit_text = re.sub(r"\s+per[\s_-]+water[\s_-]+molecule\s*$", "", unit_text,
                                       flags=re.IGNORECASE)
                if expected_count_entity is not None:
                    parsed_unit = count_unit_factor_and_family(unit_text, expected_count_entity)
                else:
                    parsed_unit = unit_factor_and_family(unit_text, expected_unit,
                                                         percent_allowed=percent_allowed)
                if parsed_unit is None:
                    fail(f"{key[0]} / {key[1]}: wrong units {units}; expected {expected_unit}")
                scale, _family = parsed_unit
                value *= scale
                if not (value == value and abs(value) != float("inf")):
                    fail(f"{key[0]} / {key[1]}: scaled value is not finite")
                break
        if value is None:
            missing.append(f"{key[0]} / {key[1]}")
        elif anchor != 0 and abs(value - anchor) / abs(anchor) > tol:
            wrong.append(f"{key[0]} / {key[1]}: submitted {value}, anchor {anchor}")
    if missing:
        fail(f"missing required values: {missing[:6]}{' ...' if len(missing) > 6 else ''}")
    if wrong:
        fail(f"values disagree with anchors: {wrong[:6]}{' ...' if len(wrong) > 6 else ''}")

    # Prose is displayed as research evidence but is not semantically scored;
    # the closed normalized rubric below rejects direct contradictions.
    conv = {}
    for row in sub["conventions"]:
        val.mapping(row, "convention", fail)
        topic = norm(val.text(row.get("topic"), "convention.topic", fail)).strip()
        statement = val.text(row.get("statement"), "convention.statement", fail)
        val.text(row.get("basis"), "convention.basis", fail)
        if topic in conv:
            fail(f"duplicate convention topic: {topic}")
        conv[topic] = statement
    if set(conv) != topic_fields:
        fail("conventions must contain exactly the five fixed topics")
    unsupported_ok = False
    for row in sub["unsupported"]:
        val.mapping(row, "unsupported entry", fail)
        claim = val.text(row.get("claim"), "unsupported.claim", fail)
        why = val.text(row.get("why"), "unsupported.why", fail)
        category = row.get("category")
        if category not in {"hardware_performance_extrapolation", "per_configuration_error_distribution"}:
            fail("unsupported category is not in the closed evidence-boundary rubric")
        if row.get("supported") is not False:
            fail("unsupported structured decision must mark the claim unsupported")
        if claim.strip() and why.strip(): unsupported_ok = True
    if not unsupported_ok:
        fail("unsupported needs a nonempty claim and evidence-based reason")
    print(json.dumps({"case_id": "case-04", "status": "PASS", "reward": 1,
                      "values_checked": len(anchors),
                      "conventions_checked": len(convention_topics)}, indent=1))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SubmissionError as exc:
        print(json.dumps({"case_id": "case-04", "status": "FAIL", "reward": 0, "reason": str(exc)}))
        sys.exit(1)
    except InfrastructureError as exc:
        print(json.dumps({"case_id": "case-04", "status": "ENVIRONMENT_ERROR", "reason": str(exc)}))
        sys.exit(2)
    except Exception as exc:
        print(json.dumps({"case_id": "case-04", "status": "ENVIRONMENT_ERROR", "reason": f"unexpected verifier error: {type(exc).__name__}: {exc}"}))
        sys.exit(2)
