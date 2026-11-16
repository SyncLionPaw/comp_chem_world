#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Conditional fate of bicyclic peroxy radicals.
"""Eight independent dimensional, native-rate and kinetic audit checks for Case 04."""
import argparse
import ast
import csv
import hashlib
import json
import math
import re
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

CASE = "case-04-bpr-fate-effective-loss-rate"
PINNED_ASSETS = {'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-200-mesmer_out.xml': 'sha256:6e25c758ad0ac7c3a0473f974ea31dd33746344b281c1f7e7b26db148eefe537', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-225-mesmer_out.xml': 'sha256:914a4da187f2b77952702778b84818d29344eab1ded434c3c674a46e2965f4b4', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-250-mesmer_out.xml': 'sha256:b193715b66aa4887e4ee3d96fe9ac3b5c607a3ea1b844c28e4d58adb082407dc', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-255-mesmer_out.xml': 'sha256:aaada51cb08a8972193f7fbee12ac62b10d13c18cd563abbf995e434e8ebd853', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-260-mesmer_out.xml': 'sha256:2e060ea36920da0c1c1ac346be94dc0991f7fe91536db930c74373b2b41c5d4b', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-265-mesmer_out.xml': 'sha256:8f27d782a57da4ff98f4d720970fabd69a00c5be6eff86d0884e70e0756d4310', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-270-mesmer_out.xml': 'sha256:9905cdaac95762092597f9294a3349babe8367f239ee137b2a119b620ae46727', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-275-mesmer_out.xml': 'sha256:7824830b91254335da4d51c6f90ab8f8cdae9545267c6398790089ac22b9fb47', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-280-mesmer_out.xml': 'sha256:b639c098005f248b84fe9a631cfdeab03fd08e63db10d62e95e65a91e48ee4e5', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-285-mesmer_out.xml': 'sha256:0fd73724fb42f6d63cc36342141943fc24c01ec332a9dea179f6f52833ce5b22', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-290-mesmer_out.xml': 'sha256:29e1a781d5d90ec68be7f9c40ef29ded4acfc01833b6f0b5bd9a1550a3077d94', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-295-mesmer_out.xml': 'sha256:1f0febc06b2a6b1e5b2ffcd5fe4f5b8444632f66125e06ad5d96645aee779caa', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-300-mesmer_out.xml': 'sha256:e919fd67260d98c5bbbf2edff3a114ce54ba336e3bdd59556856abea5f4f6516', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-305-mesmer_out.xml': 'sha256:0d10af4420299fc1d16b4de01e2856d3462c68e540eec8bc733cdf5aa674486b', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-310-mesmer_out.xml': 'sha256:4761128d619cb8dfa66bd053eecd265d7d2f5000d6baaf691ccc76c1d57e29b0', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-325-mesmer_out.xml': 'sha256:1c9461303649e977ab862bb15967247b05e6a3599079a36c4ce3b3cbe7e19e25', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-350-mesmer_out.xml': 'sha256:ac14cc3d3d9862900447ec203e19f07a9651193b89ae4a2871ee0e83b93a5d51', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-375-mesmer_out.xml': 'sha256:c6c1a7a440a7083faa99a2e866c2b61fcf8a4ba91c9116eba81333e5ddc8a29a', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-400-mesmer_out.xml': 'sha256:f6c739a68af204aeee61628116ec917eb4429959946f1c07f4bb48a179bc79f3', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-425-mesmer_out.xml': 'sha256:7b7ce9ec7325fbe11f3147cef62fcadd9ddea4302e9fa14e55f4a4bdf1e905a8', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-450-mesmer_out.xml': 'sha256:c42f760bf2abd22625b3f91aab3bf31b2e95734149f2b23f5ed134384b63dd9c', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-475-mesmer_out.xml': 'sha256:96f53569d357286677e7f0bf8ca9dc2716bc1a3be2bf6c4f81548690740e9704', 'assets/Toluene-iBPR-rearrangement-Tdep-MESMER/Toluene-ipso-HR-500-mesmer_out.xml': 'sha256:240997ebe177f06cd099b9172cdd09bece1a16ec7b13d1f3091c433d7f1137ad', 'assets/41467_2023_40675_MOESM1_ESM.docx': 'sha256:52c8854e125cac6ea714c61a4e711fea66565cef62d0f176511e819e59fd568a', 'assets/41467_2023_40675_MOESM3_ESM.xlsx': 'sha256:69969f05b7fb9b75335737bfc4e65cd49218d75da632197d929f6196784b67f1'}
PINNED_REFS_SHA = 'sha256:bcf503299eea6b9215b0fbf2b370e5555e43d644a8069f7d38ef314dde210931'
PINNED_REFERENCE_SHA = 'sha256:050ade4d0888adb2369e34830cc955a79379a6ba5918724dfa4277209b8c5255'
KB, NA = 1.380649e-23, 6.02214076e23
ME = "{http://www.chem.leeds.ac.uk/mesmer}"
CRITERIA = [
    ("fate_quantities_present", "L1"), ("unit_conventions_explicit", "L2"),
    ("channel_sum_reproduced", "L3"), ("effective_rate_within_author_range", "L3"),
    ("comparison_against_prior_ceiling_quantified", "L3"), ("NO_competition_and_branching_consistent", "L3"),
    ("temperature_sensitivity_assumptions_disclosed", "L3"), ("pre_equilibrium_and_reference_species_limits_stated", "L3")]


def sha(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def number(value):
    if isinstance(value, bool):
        raise ValueError("boolean used as a number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("non-finite number")
    return value


def close(value, expected, tol=0.01):
    expected = number(expected)
    return abs(number(value)-expected) <= tol*abs(expected) + 1e-14*min(1, abs(expected))


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON field: "+key)
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=unique)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def bpr_reference(value):
    label = str(value).strip().lower()
    # The contract is the physical reference species. Accept clear expansions
    # such as “BPR (bicyclic peroxy radical)” while rejecting B-alkyl bases.
    denied = re.search(r"\b(?:not|non|excluded|rather than)\b", label)
    return not denied and "alkyl" not in label and bool(
        re.search(r"\bbpr\b", label) or re.search(r"\bbicyclic\s+peroxy\s+radical\b", label)
    )


def sink_name(value):
    if isinstance(value, dict):
        declared = value.get("sink")
        if not isinstance(declared, str):
            for key in ("id", "identifier", "sink_id"):
                candidate = value.get(key)
                if isinstance(candidate, str):
                    declared = candidate
                    break
        identity = sink_name(declared) if isinstance(declared, str) else None
        if identity is None:
            return None
        for key in ("included", "is_included"):
            if key in value and value[key] is not True:
                return None
        for key in ("name", "type", "sink_type", "kind", "identity"):
            other = value.get(key)
            if isinstance(other, str):
                other_identity = sink_name(other)
                if other_identity is not None and other_identity != identity:
                    return None
        for key in ("description", "reaction", "label"):
            detail = value.get(key)
            if isinstance(detail, str):
                detail_identity = sink_name(detail)
                if detail_identity is not None and detail_identity != identity:
                    return None
        return identity
    if not isinstance(value, str):
        return None
    label = str(value).strip().lower()
    if re.search(r"\b(?:not|non|excluded|rather than|without|except)\b", label):
        return None
    if label == "mr":
        return "MR"
    if label == "no":
        return "NO"
    if ("rearrangement" in label and not re.search(r"\bno\b", label)
                          and ("bpr" in label or "c1" in label or "c2" in label or "k_mer" in label)):
        return "MR"
    no_species = r"(?:\bno\b)"
    radical = r"(?:\bbpr\b|\bro2\b)"
    # Require NO itself and a peroxy-radical participant. A negative phrase or
    # NO2 alone cannot satisfy this identity; either reactant order is valid.
    if re.search(no_species, label) and re.search(radical, label):
        return "NO"
    return None


def excluded_sinks(value):
    # The field may declare exclusion or list the excluded physical processes.
    return value is True or (isinstance(value, list) and bool(value) and
                            all(isinstance(x, str) and x.strip() for x in value))


def competition_scope_is_valid(competition):
    sinks = competition.get("sinks")
    if not isinstance(sinks, list) or len(sinks) != 2:
        return False
    identities = [sink_name(sink) for sink in sinks]
    if set(identities) != {"MR", "NO"}:
        return False
    for key in ("number_of_sinks", "sink_count"):
        if key in competition and number(competition[key]) != 2:
            return False
    excluded = competition.get("other_sinks_excluded")
    if not excluded_sinks(excluded):
        return False
    if competition.get("other_sinks_included") is True or competition.get("additional_sinks_included") is True:
        return False
    listed_exclusions = competition.get("excluded_sinks")
    if excluded is False and listed_exclusions:
        return False
    if isinstance(excluded, list) and listed_exclusions is not None and listed_exclusions != excluded:
        return False
    return True


def qssa_mr_basis(approximation):
    """Select the declared finite-return QSSA basis; legacy unlabeled formulas are per B-alkyl."""
    explicit = approximation.get("QSSA_MR_basis")
    declared = None
    if explicit is not None:
        require(isinstance(explicit, str), "QSSA_MR_basis must be text")
        token = re.sub(r"[^a-z0-9]+", "_", explicit.lower()).strip("_")
        if token in {"b_alkyl", "balkyl", "per_b_alkyl", "per_balkyl"}:
            declared = "B-alkyl"
        elif token in {"total_pool", "equilibrated_pool", "total_equilibrated_pool", "pool"}:
            declared = "total_pool"
        else:
            raise ValueError("QSSA_MR_basis must identify B-alkyl or total_pool")
    targets = approximation.get("expression_targets")
    if targets is not None:
        require(isinstance(targets, dict), "expression_targets must be an object")
    target_present = isinstance(targets, dict) and "QSSA_MR_expression" in targets
    target = targets.get("QSSA_MR_expression") if target_present else None
    target_basis = None
    if target_present:
        require(isinstance(target, str) and bool(target.strip()),
                "expression_targets.QSSA_MR_expression must identify its expression")
        label = target.lower().replace("-", "_")
        normalized_label = re.sub(r"[_\s]+", " ", label)
        require(not re.search(r"\b(?:per\s+bpr|bpr\s+referenced|bpr\s+basis)\b", normalized_label),
                "QSSA expression target declares unsupported BPR basis")
        if "pool" in label and ("total" in label or "equilibrated" in label or "per_pool" in label):
            target_basis = "total_pool"
        elif "b_alkyl" in label or "balkyl" in label:
            target_basis = "B-alkyl"
        else:
            require(declared is not None,
                    "unrecognized QSSA expression target requires explicit QSSA_MR_basis")
    require(declared is None or target_basis is None or declared == target_basis,
            "QSSA expression basis declarations conflict")
    return declared or target_basis or "B-alkyl"


def safe_expression(expression, values):
    """Evaluate arithmetic only, accepting algebraically equivalent reported formulas."""
    require(isinstance(expression, str) and len(expression) <= 1000, "formula too long or not a string")
    tree = ast.parse(expression, mode="eval")
    require(len(list(ast.walk(tree))) <= 80, "formula too complex")

    def visit(node):
        if isinstance(node, ast.Expression): return visit(node.body)
        if isinstance(node, ast.Name): return values[node.id]
        if isinstance(node, ast.Constant): return number(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        if isinstance(node, ast.BinOp):
            l, r = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add): return l+r
            if isinstance(node.op, ast.Sub): return l-r
            if isinstance(node.op, ast.Mult): return l*r
            if isinstance(node.op, ast.Div): return l/r
        raise ValueError("formula permits only numeric arithmetic and declared symbols")
    return number(visit(tree))


def expression_rhs(expression):
    """Allow one documentary `identifier = arithmetic` wrapper, never eval text."""
    require(isinstance(expression, str), "formula must be a string")
    # Public legacy relation strings sometimes spell the quantity with units.
    expression = re.sub(r"(?i)\bmolecules\s*/\s*cm(?:\^?3|³)\b", "molecules_per_cm3", expression)
    expression = re.sub(r"(?i)\bmol\s*/\s*l\b", "mol_per_L", expression)
    if "=" not in expression:
        return expression
    require(expression.count("=") == 1, "formula assignment must contain one equals sign")
    lhs, rhs = expression.split("=", 1)
    identifier = r"\s*[A-Za-z_][A-Za-z0-9_]*\s*"
    lhs_simple = re.fullmatch(identifier, lhs) is not None
    rhs_simple = re.fullmatch(identifier, rhs) is not None
    require(lhs_simple or rhs_simple, "formula assignment must have a simple identifier on one side")
    return (rhs if lhs_simple else lhs).strip()


def is_worked_numeric(expression):
    """A one-off worked check with numbers on both sides is not the general formula."""
    if "=" not in expression:
        return False
    lhs, rhs = expression.split("=", 1)
    identifier = r"\s*[A-Za-z_][A-Za-z0-9_]*\s*"
    if re.fullmatch(identifier, lhs) or re.fullmatch(identifier, rhs):
        return False
    number_pattern = r"(?<![\w.])\d+(?:\.\d*)?(?:[eE][-+]?\d+)?(?![\w])"
    return bool(re.search(number_pattern, lhs) and re.search(number_pattern, rhs))


def check_expression_identity(expression, values, variable, samples, expected, label):
    for value in samples:
        sample = dict(values)
        sample[variable] = value
        require(close(safe_expression(expression_rhs(expression), sample), expected(value), 1e-9), label)


def check_ideal_gas_number_density(expression, units, conditions, expected_density):
    """Evaluate an ideal-gas density identity using the declared condition and constants."""
    symbols = {
        "Pa_per_atm": number(units["Pa_per_atm"]),
        "k_B_J_per_K": number(units["k_B_J_per_K"]),
        "temperature_K": number(conditions["temperature_K"]),
        "cm3_per_m3": number(units["cm3_per_m3"]),
        "pressure_Pa": number(conditions["pressure_Pa"]),
        "P_Pa": number(conditions["pressure_Pa"]),
        "p_Pa": number(conditions["pressure_Pa"]),
    }
    value = safe_expression(expression_rhs(expression), symbols)
    require(close(value, expected_density, 1e-3),
            "ideal-gas number-density expression does not reproduce the stated conditions")


def native_inputs(app):
    rates = {}
    for rel in PINNED_ASSETS:
        if not rel.endswith(".xml"): continue
        root = ET.parse(app/rel).getroot()
        pts = root.findall(".//"+ME+"PTpair")
        blocks = root.findall(".//"+ME+"analysis/"+ME+"rateList")
        require(len(pts) == 1 and len(blocks) == 1, "native rate block is not unique")
        pt = pts[0]
        channel_map = {}
        for e in blocks[0].findall(ME+"firstOrderRate"):
            if e.get("fromRef") == "RO2" and e.get("toRef") in {"ringopen-prod1", "ringopen-prod2"}:
                require(e.get("toRef") not in channel_map, "duplicate native channel")
                channel_map[e.get("toRef")] = number(e.text)
        require(set(channel_map) == {"ringopen-prod1", "ringopen-prod2"}, "native channels missing")
        temperature = number(pt.get("T"))
        require(temperature not in rates and number(pt.get("P")) == 760, "native T/P mismatch")
        rates[temperature] = {"source": rel, "channels": channel_map, "bath": pt.get("bathGas"), "sum": sum(channel_map.values())}
    require(len(rates) == 23 and 300 in rates, "native temperature inventory changed")
    return rates


def normalized_parameters(a):
    params = a["parameters"]
    keq, kno = params["K_eq"], params["k_RO2_NO"]
    factor_eq = parameter_unit_factor(keq["unit"], "K_eq")
    factor_no = parameter_unit_factor(kno["unit"], "k_RO2_NO")
    return number(keq["value"])*factor_eq, number(kno["value"])*factor_no


def parameter_unit_factor(unit, key):
    """Normalize only documented molar/molecular kinetic units and their typography."""
    require(isinstance(unit, str), f"{key} unit must be a string")
    value = unit.translate(str.maketrans({"³": "3", "⁻": "-", "¹": "1", "²": "2"}))
    value = re.sub(r"\s+", "", value.lower().replace("^", ""))
    if key == "K_eq":
        molecular = {"cm3/molecule", "cm3molecule-1"}
        molar = {"l/mol", "lmol-1"}
    else:
        molecular = {"cm3/molecule/s", "cm3molecule-1s-1", "cm3molecule-1/s"}
        molar = {"l/mol/s", "lmol-1s-1", "lmol-1/s"}
    if value in molecular:
        return 1.0
    if value in molar:
        return 1000/NA
    raise ValueError(f"unsupported or dimensionally incorrect {key} unit: {unit}")


def normalized_parameter_record(record, key):
    """Convert a typed temperature-model parameter using the public unit aliases."""
    require(isinstance(record, dict) and "value" in record and "unit" in record,
            f"temperature_model.{key} must include value and unit")
    factor = parameter_unit_factor(record["unit"], key)
    return number(record["value"])*factor


def fixed_si_parameter(model_value, key, params):
    """Accept the documented string label or a value/unit/label object."""
    if model_value == "fixed_SI":
        return
    require(isinstance(model_value, dict), f"temperature_model.{key} must be fixed_SI")
    require(model_value.get("label") == "fixed_SI" or model_value.get("basis") == "fixed_SI",
            f"temperature_model.{key} must be labelled fixed_SI")
    if "label" in model_value:
        require(model_value["label"] == "fixed_SI", f"temperature_model.{key} label conflicts")
    if "basis" in model_value:
        require(model_value["basis"] == "fixed_SI", f"temperature_model.{key} basis conflicts")
    dependence = model_value.get("temperature_dependence_applied")
    require(dependence in {"none", "none applied", "fixed_SI"},
            f"temperature_model.{key} claims temperature dependence")
    if key == "K_eq" and "independently_verified" in model_value:
        require(model_value["independently_verified"] is False,
                "temperature_model.K_eq cannot claim independent verification")
    typed_value = normalized_parameter_record(model_value, key)
    base_value = normalized_parameters({"parameters": params})[0 if key == "K_eq" else 1]
    require(close(typed_value, base_value, 1e-12), f"temperature_model.{key} value conflicts with supplied SI")


def expected_quantities(c, rates, keq, kno):
    t, pressure, x, ppbv = [number(c[k]) for k in ("temperature_K", "pressure_Pa", "x_O2", "NO_ppbv")]
    require(t in rates and pressure > 0 and 0 < x <= 1 and ppbv >= 0, "invalid declared conditions")
    # Compute with SI number density in m^-3, then explicitly convert to cm^-3.
    air = pressure/t/KB * 1e-6
    o2, no = air*x, air*ppbv/1e9
    equilibrium_population = o2*keq
    kmer, loss_no = rates[t]["sum"], kno*no
    return {"air_molecules_cm3": air, "O2_molecules_cm3": o2, "NO_molecules_cm3": no,
            "k_mer_per_s": kmer, "K_eq_cm3_per_molecule": keq, "k_NO_cm3_per_molecule_s": kno,
            "q_BPR_over_Balkyl": equilibrium_population, "k_NO_pseudo_per_s": loss_no,
            "k_eff_MR_per_Balkyl_s": kmer*equilibrium_population,
            "k_eff_NO_per_Balkyl_s": loss_no*equilibrium_population,
            "MR_fraction_two_sinks": 1/(1+loss_no/kmer),
            "k_MR_per_equilibrated_pool_s": kmer/(1+1/equilibrium_population)}


def grade(final, app, reference, rates):
    input_errors = {}
    def candidate(name, reader, default):
        try: return reader(final/name)
        except (OSError, UnicodeError, ValueError, KeyError, TypeError, csv.Error) as error:
            input_errors[name] = str(error)
            return default
    def object_json(path):
        value = load_json(path)
        require(isinstance(value, dict), "JSON document must be an object")
        return value
    def read_sweep(path):
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            require(reader.fieldnames is not None and len(reader.fieldnames) == len(set(reader.fieldnames)), "missing or duplicate CSV headers")
            rows = list(reader)
            require(all(None not in r and all(v is not None for v in r.values()) for r in rows), "inconsistent CSV field count")
            return rows
    a = candidate("fate_analysis.json", object_json, {})
    units = candidate("unit_conventions.json", object_json, {})
    sweep = candidate("fate_sensitivity.csv", read_sweep, [])
    conclusion = candidate("conclusion.md", lambda p: p.read_text().strip(), "")
    checks = []

    def record(name, fn):
        try:
            fn()
            passed, reason = True, "Independent native/equation/convention audit passed"
        except (KeyError, ValueError, TypeError, IndexError, AttributeError, ZeroDivisionError, SyntaxError, RecursionError) as error:
            passed, reason = False, f"{type(error).__name__}: {error}"
        checks.append({"name": name, "level": dict(CRITERIA)[name], "passed": passed, "reason": reason})

    def present():
        require(not input_errors, "candidate document missing or invalid: " + "; ".join(f"{k}: {v}" for k,v in input_errors.items()))
        require(bool(conclusion.strip()) and bool(sweep), "four complete outputs required")
        for key in ("conditions", "parameters", "quantities", "comparisons", "competition", "temperature_model", "approximation", "SI_provenance"):
            require(isinstance(a[key], dict) and bool(a[key]), "missing section: "+key)
        require(bool(a["native_rate_records"]), "native provenance missing")
        conditions = a["conditions"]
        for key in ("temperature_K", "pressure_Pa", "x_O2", "NO_ppbv"):
            number(conditions[key])
        if "pressure_Torr" in conditions:
            require(close(conditions["pressure_Torr"], number(conditions["pressure_Pa"])*760/101325, 1e-9),
                    "optional pressure_Torr conflicts with pressure_Pa")
        required_quantities = ("air_molecules_cm3", "O2_molecules_cm3", "NO_molecules_cm3",
            "k_mer_per_s", "K_eq_cm3_per_molecule", "k_NO_cm3_per_molecule_s",
            "q_BPR_over_Balkyl", "k_NO_pseudo_per_s", "k_eff_MR_per_Balkyl_s",
            "k_eff_NO_per_Balkyl_s", "MR_fraction_two_sinks", "k_MR_per_equilibrated_pool_s")
        for key in required_quantities:
            number(a["quantities"][key])
        sup = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
        prose = re.sub(r"(?:×|x|X)\s*10([⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+)",
                       lambda m: "e" + m.group(1).translate(sup), conclusion)
        prose = re.sub(r"(?<![\w.])10([⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+)",
                       lambda m: "1e" + m.group(1).translate(sup), prose)
        prose = re.sub(r"(?:×|x|X)\s*10\s*\^\s*([-+]?\d+)", r"e\1", prose)
        prose = re.sub(r"(?<![\w.])10\s*\^\s*([-+]?\d+)", r"1e\1", prose)
        prose = prose.translate(sup)
        narrative_numbers = [number(v) for v in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", prose)]
        for key in ("k_eff_MR_per_Balkyl_s", "k_eff_NO_per_Balkyl_s", "MR_fraction_two_sinks"):
            value = number(a["quantities"][key])
            require(any(close(v, value, .02) or (key == "MR_fraction_two_sinks" and close(v, 100*value, .02)) for v in narrative_numbers), "conclusion does not report numeric competition results: "+key)

    def dimensions():
        require("unit_conventions.json" not in input_errors, input_errors.get("unit_conventions.json", "unit file invalid"))
        constants = {"k_B_J_per_K": KB, "N_A_per_mol": NA, "Pa_per_atm": 101325,
                     "cm3_per_m3": 1e6, "cm3_per_L": 1000, "mole_fraction_per_ppbv": 1e-9,
                     "K_eq_L_per_mol": 1.3e-15*NA/1000, "k_NO_L_per_mol_s": 9.15e-12*NA/1000}
        require(all(close(units[k], v, 1e-3) for k, v in constants.items()), "conversion constants or cm3/L/Avogadro direction wrong")
        require(all(close(units[k], constants[k], 1e-12) for k in ("Pa_per_atm", "cm3_per_m3", "cm3_per_L", "mole_fraction_per_ppbv")), "exact unit-definition factors wrong")
        keq, kno = normalized_parameters(a)
        require(close(keq, 1.3e-15, 1e-3) and close(kno, 9.15e-12, 1e-3), "SI parameters have wrong dimensional basis")
        expected = expected_quantities(a["conditions"], rates, keq, kno)
        require(all(close(a["quantities"][k], expected[k], 1e-3) for k in ("air_molecules_cm3", "O2_molecules_cm3", "NO_molecules_cm3", "q_BPR_over_Balkyl")), "number density or equilibrium population inconsistent")
        concentration_factor = NA/1000
        parameter_unit_factor = 1000/NA
        factor = number(units["molar_to_molecular_factor"])
        if close(factor, parameter_unit_factor, 1e-3):
            # Some candidates use the named factor for L/mol -> cm3/molecule
            # rate/equilibrium constants. Accept that convention only when
            # the separate concentration factor and its direction are explicit.
            require(close(units["molar_to_molecular_factor_for_concentrations"], concentration_factor, 1e-3),
                    "molar concentration conversion factor wrong")
        elif close(factor, NA, 1e-3):
            require(close(units["molar_to_molecular_factor_for_concentrations"], concentration_factor, 1e-3),
                    "molar concentration conversion factor wrong")
        else:
            require(close(factor, concentration_factor, 1e-3), "molar concentration conversion factor wrong")
        samples = (0.1, 1e-12, 2)
        avogadro = number(units["N_A_per_mol"])
        symbols = {"mol_per_L": 1.0, "N_A": avogadro, "N_A_per_mol": avogadro,
                   "cm3_per_L": number(units["cm3_per_L"]), "molecules_per_cm3": 1.0,
                   "molecules_cm3": 1.0}
        checked_concentration_expression = False
        # Check every supplied molar-conversion identity. The same JSON may also
        # state an ideal-gas number density (pressure/mole fraction), which is a
        # different identity and is not required to be the mol/L -> cm3 one.
        for alias in ("concentration_expression", "concentration_relation",
                      "concentration_identity_molar", "molar_concentration_identity"):
            expression = units.get(alias)
            if expression is None:
                continue
            require(isinstance(expression, str), f"{alias} must be a string")
            if alias == "molar_concentration_identity" and not is_worked_numeric(expression):
                expression = re.sub(r"^\s*1\s*mol_per_L\s*=\s*",
                                    "molecules_per_cm3 = mol_per_L * ", expression)
                expression = re.sub(r"\s+molecules_per_cm3\s*$", "", expression)
            normalized = re.sub(r"(?i)\bmolecules\s*/\s*cm(?:\^?3|³)\b",
                                "molecules_per_cm3", expression)
            normalized = re.sub(r"(?i)\bmolecule\s*cm\s*\^?\s*-?3\b",
                                "molecules_per_cm3", normalized)
            normalized = re.sub(r"(?i)\bmol\s*/\s*l\b", "mol_per_L", normalized)
            normalized = re.sub(r"\bn_(?:air_)?mol_per_L\b", "mol_per_L", normalized)
            normalized = re.sub(r"\bn_(?:air_)?molar_mol_per_L\b", "mol_per_L", normalized)
            normalized = re.sub(r"\bN_(?:air_)?molecules_per_cm3\b", "molecules_per_cm3", normalized)
            normalized = re.sub(r"\bN_(?:air_)?molecules_cm3\b", "molecules_per_cm3", normalized)
            normalized = re.sub(r"\bC_(?:air_)?mol_per_L\b", "mol_per_L", normalized)
            normalized = re.sub(r"\bn_(?:air_)?molecules_per_cm3\b", "molecules_per_cm3", normalized)
            normalized = re.sub(r"\bn_(?:air_)?molecules_cm3\b", "molecules_per_cm3", normalized)
            normalized = re.sub(r"\bc_(?:air_)?mol_per_L\b", "mol_per_L", normalized)
            lower = normalized.lower()
            number_density = bool(re.search(
                r"\b(?:n_cm3|air_molecules_cm3|molecules_per_cm3|molecules_cm3)\b", lower)
                or "molecules/cm3" in lower)
            molar_conversion = "mol_per_l" in lower and number_density
            ideal_gas = any(token in lower for token in
                            ("mole_fraction", "pressure_pa", "p_pa", "pa_per_atm", "ideal gas", "ideal-gas"))
            parameter_conversion = any(token in lower for token in
                                       ("k_eq", "k_no", "rate", "cm3_per_molecule",
                                        "molar_to_molecular_factor"))
            inverse = False
            if "=" in normalized:
                lhs, rhs = normalized.split("=", 1)
                identifier = r"\s*[A-Za-z_][A-Za-z0-9_]*\s*"
                inverse = (re.fullmatch(identifier, lhs) is not None
                           and "mol_per_l" in lhs.lower()
                           and "molecules" in rhs.lower())
            if molar_conversion and is_worked_numeric(normalized):
                lhs, rhs = normalized.split("=", 1)
                unit_product = r"([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)\s+(mol_per_L|molecules_per_cm3|molecules_cm3)\b"
                lhs = re.sub(unit_product, r"\1 * \2", lhs).strip()
                rhs = re.sub(unit_product, r"\1 * \2", rhs).strip()
                require(close(safe_expression(lhs, symbols), safe_expression(rhs, symbols), 1e-9),
                        f"{alias} worked concentration identity has wrong scale")
                checked_concentration_expression = True
            elif molar_conversion and not inverse:
                check_expression_identity(normalized, symbols, "mol_per_L", samples,
                    lambda c: c*NA/1000, f"{alias} has wrong direction or scale")
                checked_concentration_expression = True
            elif molar_conversion:
                # Check an algebraic inverse; a forward identity is still required separately.
                check_expression_identity(normalized, symbols, "molecules_per_cm3", samples,
                    lambda c: c*1000/NA, f"{alias} has wrong inverse direction or scale")
                checked_concentration_expression = True
                continue
            elif ideal_gas and "pa_per_atm" in lower:
                # Evaluate the declared ideal-gas identity against the stated pressure and temperature.
                check_ideal_gas_number_density(normalized, units, a["conditions"],
                                               expected["air_molecules_cm3"])
                continue
            elif ideal_gas:
                # Preserve existing recognized pressure/mole-fraction identity forms.
                continue
            elif parameter_conversion:
                # A different, explicitly identified identity.
                continue
            else:
                require(False, f"{alias} is not a verifiable molar concentration identity")
        legacy_expression = units.get("molar_to_molecular_expression")
        if legacy_expression is not None:
            require(isinstance(legacy_expression, str), "legacy conversion expression must be a string")
            # The legacy field has appeared with both meanings. Validate its
            # declared identity independently of the canonical field.
            legacy_lower = legacy_expression.lower()
            if "mol_per_l" in legacy_lower:
                check_expression_identity(legacy_expression, symbols, "mol_per_L", samples,
                    lambda c: c*NA/1000, "molar concentration conversion identity reversed")
                checked_concentration_expression = True
            else:
                parameter_symbols = {"value_L_per_mol": 1.0, "cm3_per_L": number(units["cm3_per_L"]),
                                     "N_A": avogadro, "N_A_per_mol": avogadro}
                check_expression_identity(legacy_expression, parameter_symbols, "value_L_per_mol", samples,
                    lambda v: v*1000/NA, "molar parameter conversion identity reversed")
                checked_concentration_expression = True
        require(checked_concentration_expression, "verifiable concentration conversion identity missing")

    def channels():
        records = a["native_rate_records"]
        temperatures = [number(r["temperature_K"]) for r in records]
        require(len(temperatures) == len(set(temperatures)) and {300, number(a["conditions"]["temperature_K"])} <= set(temperatures), "duplicate/missing 300 K or chosen-temperature witness")
        for row in records:
            native = rates[number(row["temperature_K"])]
            require(row["source_file"] == native["source"] and number(row["source_pressure_Torr"]) == 760 and row["bath_gas"] == native["bath"], "native file, pressure or bath provenance wrong")
            if "analysis_locator" in row:
                require(row["analysis_locator"] == "analysis/rateList/firstOrderRate", "optional rate locator does not identify the analysis elements")
            supplied = {r["toRef"]: r for r in row["channels"]}
            require(len(row["channels"]) == 2 and set(supplied) == set(native["channels"]), "missing or duplicate C1/C2")
            for product, value in native["channels"].items():
                require(supplied[product]["fromRef"] == "RO2" and close(supplied[product]["rate_per_s"], value), "wrong species assignment/channel rate")
            require(close(row["k_mer_per_s"], native["sum"]), "channel sum wrong")

    def effective():
        keq, kno = normalized_parameters(a)
        require(close(keq, 1.3e-15, 1e-3) and close(kno, 9.15e-12, 1e-3), "effective coefficient must use supplied SI parameters")
        expected = expected_quantities(a["conditions"], rates, keq, kno)
        q = a["quantities"]
        c = a["conditions"]
        baseline = all(close(c[k], v, 1e-8) for k, v in {"temperature_K": 300, "pressure_Pa": 101325, "x_O2": .2095, "NO_ppbv": 1}.items())
        require(all(close(q[k], v, .02 if baseline and k in {"k_eff_MR_per_Balkyl_s", "k_eff_NO_per_Balkyl_s"} else .01) for k, v in expected.items()), "effective, native or pool quantity fails independent recomputation")
        if baseline:
            require(close(q["k_eff_MR_per_Balkyl_s"], 4900, .02) and close(q["k_eff_NO_per_Balkyl_s"], 1500, .02), "baseline does not reproduce SI rounding")
        si = a["SI_provenance"]
        source_file, source_asset = si.get("source_file"), si.get("source_asset")
        require(source_file is not None or source_asset is not None, "SI source missing")
        require(source_file is None or source_file == "assets/41467_2023_40675_MOESM1_ESM.docx", "SI source_file is wrong")
        require(source_asset is None or source_asset == "assets/41467_2023_40675_MOESM1_ESM.docx", "SI source_asset is wrong")
        require(source_file is None or source_asset is None or source_file == source_asset,
                "SI source_file/source_asset declarations conflict")
        if "part" in si:
            part = str(si["part"]).strip().lower()
            section_locator = "2.2" in part and "loss rate of b-alkyl" in part
            require(part == "word/document.xml" or section_locator, "optional SI document locator is wrong")
        if "equation_paragraph_zero_based" in si:
            require(si["equation_paragraph_zero_based"] == reference["SI_equation"]["paragraph_index_zero_based"], "optional SI equation paragraph index is wrong")
        if "parameters_paragraph_zero_based" in si:
            require(si["parameters_paragraph_zero_based"] == reference["SI_statement"]["paragraph_index_zero_based"], "optional SI parameter paragraph index is wrong")

    def comparison():
        c = a["comparisons"]
        require(bpr_reference(c["prior_reference_species"]) and number(c["prior_comparison_temperature_K"]) == 300, "old ceiling must be compared on the 300 K BPR basis")
        require(close(c["prior_ceiling_per_BPR_s"], .03, 1e-9) and close(c["MR_over_prior_BPR_ceiling"], rates[300]["sum"]/.03), "mixed reference species or acceleration ratio wrong")
        require(close(c["k_oxy_per_Balkyl_s"], .22, 1e-9) and close(c["MR_effective_over_oxy_Balkyl"], number(a["quantities"]["k_eff_MR_per_Balkyl_s"])/.22), "B-alkyl comparison wrong")
        require(close(c["SI_effective_MR_per_s"], 4900) and close(c["SI_effective_NO_per_s"], 1500), "SI limiting values misrepresented")

    def competition():
        keq, kno = normalized_parameters(a)
        q = expected_quantities(a["conditions"], rates, keq, kno)
        c = a["competition"]
        if q["k_NO_pseudo_per_s"]:
            require(close(c["MR_over_NO"], q["k_mer_per_s"]/q["k_NO_pseudo_per_s"]), "two-sink ratio wrong")
        else:
            require(c["MR_over_NO"] is None, "zero-NO ratio must be null, not a finite value")
        require(close(c["MR_fraction_two_sinks"], q["MR_fraction_two_sinks"]) and close(c["NO_crossover_ppbv"], q["k_mer_per_s"]/(kno*q["air_molecules_cm3"]*1e-9)), "branching fraction/crossover wrong")
        if "common_K_eq_O2_factor_cancels" in c:
            require(c["common_K_eq_O2_factor_cancels"] is True, "optional common-factor statement contradicts the calculated scenarios")
        require(competition_scope_is_valid(c),
                "NO competition or two-sink scope not disclosed")

    def sensitivity():
        require("fate_sensitivity.csv" not in input_errors, input_errors.get("fate_sensitivity.csv", "sensitivity table invalid"))
        model = a["temperature_model"]
        params = a["parameters"]
        fixed_si_parameter(model["K_eq"], "K_eq", params)
        fixed_si_parameter(model["k_RO2_NO"], "k_RO2_NO", params)
        labels = model.get("parameter_labels")
        if labels is not None:
            require(isinstance(labels, dict) and labels.get("K_eq") == labels.get("k_RO2_NO") == "fixed_SI",
                    "temperature_model parameter_labels conflict with fixed_SI")
        require(model["thermodynamic_prediction"] is False and model["bath_gas_composition_recomputed"] is False and number(model["source_pressure_Torr"]) == 760, "unsupported temperature/pressure/composition claim")
        variants = {k: {number(row[k]) for row in sweep} for k in ("temperature_K", "x_O2", "NO_ppbv")}
        require(all(len(v) >= 2 for v in variants.values()), "sweep must vary T, O2 and NO")
        groups, unique = {}, {}
        baseline_key = tuple(number(a["conditions"][k]) for k in ("temperature_K", "pressure_Pa", "x_O2", "NO_ppbv"))
        baseline_fraction = number(a["quantities"]["MR_fraction_two_sinks"])
        for row in sweep:
            key = tuple(number(row[k]) for k in ("temperature_K", "pressure_Pa", "x_O2", "NO_ppbv"))
            require(row["scenario_kind"] == "fixed_K_eq_and_k_NO" and number(row["source_pressure_Torr"]) == 760, "sensitivity assumption label missing")
            expected = expected_quantities(row, rates, 1.3e-15, 9.15e-12)
            require(all(close(row[k], v) for k, v in expected.items()), "sensitivity scenario fails dimensional/native recomputation")
            if key in unique:
                reported = {k: number(row[k]) for k in expected}
                require(all(close(reported[k], unique[key]["reported"][k], 1e-9) for k in expected),
                        "duplicate sensitivity scenario has inconsistent quantities")
                continue
            unique[key] = {"expected": expected, "reported": {k: number(row[k]) for k in expected}}
            if key == baseline_key:
                require(close(row["MR_fraction_two_sinks"], baseline_fraction), "baseline and repeated sensitivity row disagree")
            groups.setdefault((key[0], key[1], key[3]), []).append((key[2], number(row["MR_fraction_two_sinks"])))
        groups.setdefault((baseline_key[0], baseline_key[1], baseline_key[3]), []).append((baseline_key[2], baseline_fraction))
        comparable = [rows for rows in groups.values() if len({x for x, _ in rows}) >= 2]
        require(bool(comparable) and all(max(f for _, f in rows)-min(f for _, f in rows) <= 1e-8 for rows in comparable), "paired O2 sweep must show common-factor cancellation")

    def limits():
        ap = a["approximation"]
        qssa_basis = qssa_mr_basis(ap)
        condition = ap["return_must_dominate_sink_sum"]
        condition_ok = condition is True
        # Probe different returns, equilibria, O2, NO and sinks: accept algebraic equivalents.
        for k_return, kmer, kno, no, o2, keq in [(0.01,.749169,.2,1,2,3), (1,.1,.3,0,4,.5), (100,7,.05,2,3,4), (.1,2,1,4,5,.2)]:
            env = {"k_return": k_return, "k_add": keq*k_return, "K_eq": keq, "O2": o2, "k_mer": kmer, "k_NO": kno, "NO": no}
            q = keq*o2
            sink_ratio = (kmer+kno*no)/k_return
            if qssa_basis == "total_pool":
                expected_qssa = kmer*q/(1+q+sink_ratio)
            else:
                expected_qssa = env["k_add"]*o2*kmer/(k_return+kmer+kno*no)
            require(close(safe_expression(ap["QSSA_MR_expression"], env), expected_qssa, 1e-9),
                    "finite-return QSSA formula or declared species basis is wrong")
            require(close(safe_expression(ap["pool_MR_expression"], env), (keq*o2)/(1+keq*o2)*kmer, 1e-9), "total-pool normalization wrong")
            if isinstance(condition, str):
                sides = condition.replace("≫", ">>").split(">>")
                require(len(sides) == 2 and sides[0].strip() == "k_return" and
                        close(safe_expression(sides[1].strip(), env), kmer+kno*no, 1e-9),
                        "return dominance condition omits or changes a sink")
                condition_ok = True
        require(condition_ok and ap["k_return_known"] is False and ap["K_eq_independently_verified"] is False, "pre-equilibrium validity or supplied K_eq overstated")
        require(a["parameters"]["K_eq"]["basis"] == a["parameters"]["k_RO2_NO"]["basis"] == "supplied_SI" and a["parameters"]["K_eq"]["independently_verified"] is False, "supplied parameters mislabelled as independently validated")
        explanation = ap.get("explanation")
        require(isinstance(explanation, str) and bool(explanation.strip()),
                "approximation explanation missing")
        # Legacy effective_reference_species and boolean labels are ambiguous
        # when one result object reports multiple quantities. They do not set
        # or override the formula basis, which is probed above independently.

    for (name, _), fn in zip(CRITERIA, (present, dimensions, channels, effective, comparison, competition, sensitivity, limits)):
        record(name, fn)
    return checks


def regular_file(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
        current = root
        if root.is_symlink(): return False
        for part in parts:
            current = current / part
            if current.is_symlink(): return False
        return path.is_file() and root.resolve() in path.resolve().parents
    except (OSError, ValueError): return False

def main():
    p = argparse.ArgumentParser()
    for arg in ("app-dir", "tests-dir", "final-dir", "report"): p.add_argument("--"+arg, type=Path, required=True)
    args = p.parse_args()
    report = {"case_id": CASE, "status": "ENV_INVALID", "reward": None, "checks": [], "failures": []}
    try:
        require(sha(args.tests_dir/"refs.json") == PINNED_REFS_SHA, "grader refs changed")
        require(sha(args.tests_dir/"references/case04_fate_manifest.json") == PINNED_REFERENCE_SHA, "frozen reference changed")
        for rel, expected in PINNED_ASSETS.items():
            path = args.app_dir/rel
            require(regular_file(path,args.app_dir/"assets") and sha(path) == expected, "public input changed: "+rel)
        reference = json.loads((args.tests_dir/"references/case04_fate_manifest.json").read_text())
        rates = native_inputs(args.app_dir)
        require(close(rates[300]["sum"], reference["baseline"]["k_mer_per_s"], 1e-10), "native/reference rate discrepancy")
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
        report["reason"] = "Grading environment: "+str(error)
    else:
        try:
            checks = grade(args.final_dir, args.app_dir, reference, rates)
        except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError, csv.Error, ArithmeticError) as error:
            checks = [{"name": n, "level": level, "passed": False, "reason": "Candidate output invalid: "+str(error)} for n, level in CRITERIA]
        report["checks"] = checks
        report["failures"] = [c["name"] for c in checks if not c["passed"]]
        report.update(status="FAIL" if report["failures"] else "PASS", reward=0 if report["failures"] else 1)
    report["verifier_sha256"] = sha(Path(__file__))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)+"\n")
    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    return {"PASS": 0, "FAIL": 1, "ENV_INVALID": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
