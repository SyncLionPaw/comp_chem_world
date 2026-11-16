#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Intrinsic cleavage–emission competition in six alloys.
"""CompChemBench grader adapter for the local hydrogen-embrittlement Case 06.

The scientific verification is the independent re-computation below: it
rebuilds the six-alloy 101x101x3 phase map, the exact per-anchor-cell boundary
segments, the fluctuation-area classification areas and the nine-vertex
robustness certificates from the sourced inputs, then asserts the candidate's
deliverables against that reconstruction.

Outcome contract (consumed by tests/test.sh):
  PASS                -> exit 0, reward 1
  FAIL                -> exit 1, reward 0
  GRADER_INPUT_ERROR  -> exit 2, no reward file (infrastructure fault)
"""
from __future__ import annotations

# case06_verifier scientific verification
"""Independent source-to-output verifier for the bounded Case06 phase map."""
import csv as _phase_csv
import json as _phase_json
import math as _phase_math
_phase_ALLOYS = ('SS304', 'SS316L', 'CoCrNi', 'CoNiV', 'CoCrFeNi', 'CoCrFeMnNi')
_phase_AREAS = (30.0, 50.0, 70.0)

def _phase_table(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(_phase_csv.DictReader(f))

def _phase_interp(points, x):
    points = sorted(points)
    if x < points[0][0] - 1e-12 or x > points[-1][0] + 1e-12:
        raise ValueError('extrapolation')
    for point in points:
        if _phase_math.isclose(x, point[0], abs_tol=1e-12):
            return point[1:]
    for p0, p1 in zip(points, points[1:]):
        x0, y0 = (p0[0], p0[1:])
        x1, y1 = (p1[0], p1[1:])
        if x0 < x < x1:
            f = (x - x0) / (x1 - x0)
            return tuple((a + f * (b - a) for a, b in zip(y0, y1)))
    raise ValueError('unresolved interpolation')

def _phase_verify(assets, outputs):
    if not __debug__:
        raise RuntimeError('verification refuses python -O because scientific assertions are disabled')
    e_rows = _phase_table(assets / 'elastic_constants_fig2a.csv')
    f_rows = _phase_table(assets / 'gamma_f_fig2b_digitized.csv')
    u_rows = _phase_table(assets / 'gamma_usf_fig2c_parameters.csv')
    assert {r['alloy'] for r in e_rows} == set(_phase_ALLOYS), 'six elastic rows/materials required; Ni must not be imputed'
    ep, fp, up = ({}, {}, {})
    for r in e_rows:
        assert float(r['alpha_GPa']) > 0 and float(r['beta_GPa']) > 0
        ep[r['alloy']] = (float(r['alpha_GPa']), float(r['beta_GPa']))
    for r in f_rows:
        assert r['gamma_F_units'] == 'J/m^2'
        assert float(r['Cb_context_appm']) == 5800
        fp.setdefault(r['alloy'], []).append((float(r['C_surface']), float(r['gamma_F_mean_J_m2']), float(r['gamma_F_low_J_m2']), float(r['gamma_F_high_J_m2'])))
    for r in u_rows:
        assert float(r.get('area_A2', '108')) == 108
        up.setdefault(r['alloy'], []).append((float(r.get('C_usf', r.get('coverage_Cusf'))), float(r['gamma_usf_mean_mJ_m2']), float(r['gamma_usf_std_DFT_mJ_m2'])))
    for alloy in _phase_ALLOYS:
        assert sorted((x[0] for x in fp[alloy])) == [0.0, 0.5, 1.0]
        assert sorted((x[0] for x in up[alloy])) == [0.0, 0.5, 1.0]
    grid = _phase_table(outputs / 'phase_map.csv')
    assert len(grid) == len(_phase_ALLOYS) * 101 * 101 * 3, 'expected 101x101x3 area coverage for each alloy'
    seen = set()
    for r in grid:
        alloy, cs, cu, area = (r['alloy'], float(r['C_surface']), float(r['C_usf']), float(r['A_nucleation_A2']))
        assert alloy in ep and area in _phase_AREAS and (0 <= cs <= 1) and (0 <= cu <= 1)
        assert float(r['Cb_fixed']) == 0.0058 and float(r['temperature_K']) == 300
        # Physical units are explicit in the numeric column names and independently
        # recomputed below; repeated prose/source-label columns are not scientific tests.
        assert _phase_math.isclose(cs * 100, round(cs * 100), abs_tol=1e-09) and _phase_math.isclose(cu * 100, round(cu * 100), abs_tol=1e-09)
        key = (alloy, cs, cu, area)
        assert key not in seen, 'duplicate grid point'
        seen.add(key)
        gf = _phase_interp([(x[0], x[1], x[2], x[3]) for x in fp[alloy]], cs)
        gu, std = _phase_interp([(x[0], x[1], x[2]) for x in up[alloy]], cu)
        alpha, beta = ep[alloy]
        ds = (alpha * gf[0] - beta * gu / 1000, alpha * gf[1] - beta * gu / 1000, alpha * gf[2] - beta * (gu - std * _phase_math.sqrt(108 / area)) / 1000)
        keys = ('gamma_F_mean_J_m2', 'gamma_F_low_J_m2', 'gamma_F_high_J_m2')
        for k, v in zip(keys, gf):
            assert _phase_math.isclose(float(r[k]), v, abs_tol=1e-10)
        assert _phase_math.isclose(float(r['D_low_GPa_J_m2']), ds[1], abs_tol=1e-10)
        assert _phase_math.isclose(float(r['D_center_GPa_J_m2']), ds[0], abs_tol=1e-10)
        assert _phase_math.isclose(float(r['D_high_GPa_J_m2']), ds[2], abs_tol=1e-10)
        ki_expected = (_phase_math.sqrt(alpha * gf[1] / 1000), _phase_math.sqrt(alpha * gf[0] / 1000), _phase_math.sqrt(alpha * gf[2] / 1000), _phase_math.sqrt(beta * max(0, gu - std * _phase_math.sqrt(108 / area)) / 1000000), _phase_math.sqrt(beta * gu / 1000000))
        ki_keys = ('KIc_low_MPa_sqrt_m', 'KIc_mean_MPa_sqrt_m', 'KIc_high_MPa_sqrt_m', 'KIe_low_MPa_sqrt_m', 'KIe_mean_MPa_sqrt_m')
        for k, v in zip(ki_keys, ki_expected):
            assert _phase_math.isclose(float(r[k]), v, abs_tol=1e-10), 'critical-K value/units formula mismatch'
        assert _phase_math.isclose(float(r['gamma_usf_sigma_scaled_mJ_m2']), std * _phase_math.sqrt(108 / area), abs_tol=1e-10), 'wrong DFT fluctuation area scaling'
        label = 'cleavage_first_robust' if ds[2] < 0 else 'emission_first_robust' if ds[1] > 0 else 'competition_uncertain'
        assert r['classification'] == label
    assert len({(float(r['C_surface']), float(r['C_usf'])) for r in grid if r['alloy'] == _phase_ALLOYS[0] and float(r['A_nucleation_A2']) == 50}) == 101 * 101
    bounds = _phase_json.loads((outputs / 'analytic_boundaries.json').read_text(encoding='utf-8'))
    expected_segments = {}

    def bound_value(alloy, area, name, x, y):
        fg = _phase_interp([(q[0], q[1], q[2], q[3]) for q in fp[alloy]], x)
        uv, us = _phase_interp([(q[0], q[1], q[2]) for q in up[alloy]], y)
        alpha, beta = ep[alloy]
        gfi = fg[1] if name == 'D_low' else fg[0] if name == 'D_center' else fg[2]
        ut = uv if name != 'D_high' else uv - us * _phase_math.sqrt(108 / area)
        return alpha * gfi - beta * ut / 1000

    def edge_root(p, q, alloy, area, name):
        vp = bound_value(alloy, area, name, *p)
        vq = bound_value(alloy, area, name, *q)
        if abs(vp) < 1e-12:
            return p
        if abs(vq) < 1e-12:
            return q
        if vp * vq > 0:
            return None
        t = vp / (vp - vq)
        return (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))
    for alloy in _phase_ALLOYS:
        for area in _phase_AREAS:
            for x0, x1 in ((0.0, 0.5), (0.5, 1.0)):
                for y0, y1 in ((0.0, 0.5), (0.5, 1.0)):
                    corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
                    for name in ('D_low', 'D_center', 'D_high'):
                        pts = []
                        for p0, p1 in zip(corners, corners[1:] + corners[:1]):
                            root = edge_root(p0, p1, alloy, area, name)
                            if root and (not any((_phase_math.dist(root, z) < 1e-09 for z in pts))):
                                pts.append(root)
                        if len(pts) >= 2:
                            k = (alloy, area, name, x0, x1, y0, y1)
                            expected_segments[k] = sorted(pts)
    submitted = {}
    for seg in bounds:
        alloy, area, name = (seg['alloy'], float(seg['A_nucleation_A2']), seg['boundary'])
        x0, x1 = seg['C_surface_cell']
        y0, y1 = seg['C_usf_cell']
        k = (alloy, area, name, x0, x1, y0, y1)
        assert k not in submitted, 'duplicate contour segment'
        submitted[k] = sorted([tuple(p) for p in seg['endpoints_C_surface_C_usf']])
        assert area in _phase_AREAS and x0 in (0, 0.5) and (x1 in (0.5, 1)) and (y0 in (0, 0.5)) and (y1 in (0.5, 1))
        for x, y in seg['endpoints_C_surface_C_usf']:
            assert x0 - 1e-10 <= x <= x1 + 1e-10 and y0 - 1e-10 <= y <= y1 + 1e-10
            gf = _phase_interp([(q[0], q[1], q[2], q[3]) for q in fp[alloy]], x)
            gu, std = _phase_interp([(q[0], q[1], q[2]) for q in up[alloy]], y)
            alpha, beta = ep[alloy]
            val = alpha * (gf[1] if name == 'D_low' else gf[0] if name == 'D_center' else gf[2])
            us = gu if name != 'D_high' else gu - std * _phase_math.sqrt(108 / area)
            assert abs(val - beta * us / 1000) < 2e-08, 'contour endpoint is not a true edge intersection'
    assert set(submitted) == set(expected_segments), 'missing or extra per-cell contour segment'
    for k, expected in expected_segments.items():
        actual = submitted[k]
        assert len(actual) == len(expected) and all((_phase_math.dist(a, b) < 1e-09 for a, b in zip(actual, expected))), 'contour edge intersections are incomplete or incorrect'
    region = _phase_table(outputs / 'region_areas.csv')
    assert len(region) == len(_phase_ALLOYS) * 3
    region_keys = {(r['alloy'], float(r['A_nucleation_A2'])) for r in region}
    assert len(region_keys) == len(region) and region_keys == {(a, area) for a in _phase_ALLOYS for area in _phase_AREAS}, 'region area rows must uniquely cover every alloy-area pair'

    def polygon_area(poly):
        return abs(sum((a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1])))) / 2 if len(poly) >= 3 else 0.0

    def clipped(poly, fn, nonpos):
        out = []
        for p, q in zip(poly, poly[1:] + poly[:1]):
            fpv, fqv = (fn(*p), fn(*q))
            ip = fpv <= 1e-12 if nonpos else fpv >= -1e-12
            iq = fqv <= 1e-12 if nonpos else fqv >= -1e-12
            if ip:
                out.append(p)
            if ip != iq:
                t = fpv / (fpv - fqv)
                out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
        return out
    for r in region:
        assert _phase_math.isclose(float(r['area_sum']), 1, abs_tol=1e-09)
        alloy, area = (r['alloy'], float(r['A_nucleation_A2']))
        alpha, beta = ep[alloy]
        totals = {'cleavage_first_robust': 0.0, 'emission_first_robust': 0.0, 'competition_uncertain': 0.0}
        for x0, x1 in ((0.0, 0.5), (0.5, 1.0)):
            for y0, y1 in ((0.0, 0.5), (0.5, 1.0)):
                base = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

                def low(x, y):
                    f = _phase_interp([(q[0], q[1], q[2], q[3]) for q in fp[alloy]], x)
                    u, s = _phase_interp([(q[0], q[1], q[2]) for q in up[alloy]], y)
                    return alpha * f[1] - beta * u / 1000

                def high(x, y):
                    f = _phase_interp([(q[0], q[1], q[2], q[3]) for q in fp[alloy]], x)
                    u, s = _phase_interp([(q[0], q[1], q[2]) for q in up[alloy]], y)
                    return alpha * f[2] - beta * (u - s * _phase_math.sqrt(108 / area)) / 1000
                totals['cleavage_first_robust'] += polygon_area(clipped(base, high, True))
                totals['emission_first_robust'] += polygon_area(clipped(base, low, False))
                totals['competition_uncertain'] += polygon_area(clipped(clipped(base, low, True), high, False))
        for key, val in totals.items():
            assert _phase_math.isclose(float(r[key]), val, abs_tol=1e-09), 'fabricated or incorrect classification area'
    certs = _phase_json.loads((outputs / 'extrema_certificates.json').read_text(encoding='utf-8'))
    assert len(certs) == len(_phase_ALLOYS) * len(_phase_AREAS)
    by = {(x['alloy'], float(x['A_nucleation_A2'])): x for x in certs}
    assert len(by) == len(certs), 'duplicate extrema certificate'
    for alloy in _phase_ALLOYS:
        for area in _phase_AREAS:
            vals = []
            for cs in (0.0, 0.5, 1.0):
                f = _phase_interp([(q[0], q[1], q[2], q[3]) for q in fp[alloy]], cs)
                for cu in (0.0, 0.5, 1.0):
                    u, s = _phase_interp([(q[0], q[1], q[2]) for q in up[alloy]], cu)
                    vals.append({'C_surface': cs, 'C_usf': cu, 'D_low_GPa_J_m2': ep[alloy][0] * f[1] - ep[alloy][1] * u / 1000, 'D_high_GPa_J_m2': ep[alloy][0] * f[2] - ep[alloy][1] * (u - s * _phase_math.sqrt(108 / area)) / 1000})
            expected = {'min_D_low': min(vals, key=lambda z: z['D_low_GPa_J_m2']), 'max_D_low': max(vals, key=lambda z: z['D_low_GPa_J_m2']), 'min_D_high': min(vals, key=lambda z: z['D_high_GPa_J_m2']), 'max_D_high': max(vals, key=lambda z: z['D_high_GPa_J_m2'])}
            c = by[alloy, area]
            assert c['vertices_checked'] == 9
            for kind, obj in expected.items():
                got = c[kind]
                assert _phase_math.isclose(got['D_low_GPa_J_m2'] if 'low' in kind else got['D_high_GPa_J_m2'], obj['D_low_GPa_J_m2'] if 'low' in kind else obj['D_high_GPa_J_m2'], abs_tol=1e-10)
                assert got['C_surface'] == obj['C_surface'] and got['C_usf'] == obj['C_usf']
            cert = 'cleavage_first_robust_entire_domain' if expected['max_D_high']['D_high_GPa_J_m2'] < 0 else 'emission_first_robust_entire_domain' if expected['min_D_low']['D_low_GPa_J_m2'] > 0 else 'local_competition_or_uncertainty_present'
            assert c['whole_domain_certificate'] == cert
    print(f'PASS: {len(grid)} independently recomputed 2-D map rows; {len(bounds)} exact clipped boundary segments; {len(region)} area summaries')




import argparse
import hashlib
import json
import traceback
from pathlib import Path

DELIVERABLES = (
    "phase_map.csv",
    "analytic_boundaries.json",
    "region_areas.csv",
    "extrema_certificates.json",
)

# Failures that mean "the candidate's deliverables are wrong, missing or
# malformed" -- the task is scored 0 rather than reported as a grader fault.
CANDIDATE_FAULTS = (
    AssertionError,
    FileNotFoundError,
    IsADirectoryError,
    NotADirectoryError,
    KeyError,
    IndexError,
    TypeError,
    ValueError,  # includes json.JSONDecodeError
    UnicodeDecodeError,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_inputs(app_dir: Path, tests_dir: Path, refs: dict) -> list[str]:
    """All public inputs and protected source references are frozen."""
    problems = []
    for field, base in (("asset_hashes", app_dir), ("grader_reference_hashes", tests_dir)):
        group = refs.get(field)
        if not isinstance(group, dict) or (field == "asset_hashes" and not group):
            problems.append(f"invalid or empty {field}")
            continue
        expected_paths = ({f"assets/{p.relative_to(app_dir/'assets').as_posix()}" for p in (app_dir/'assets').rglob('*') if p.is_file()}
                          if field == "asset_hashes" else
                          {f"tests/{p.relative_to(tests_dir).as_posix()}" for p in (tests_dir/'references').rglob('*') if p.is_file()})
        if set(group) != expected_paths:
            problems.append(f"incomplete {field} manifest")
        for rel, expected in sorted(group.items()):
            from pathlib import PurePosixPath
            q = PurePosixPath(rel)
            if q.is_absolute() or '..' in q.parts or not isinstance(expected, str) or len(expected) != 71 or not expected.startswith('sha256:'):
                problems.append(f"invalid hash entry {rel}")
                continue
            if field == "grader_reference_hashes" and q.parts and q.parts[0] == "tests":
                q = PurePosixPath(*q.parts[1:])
            path = base.joinpath(*q.parts)
            if not path.is_file() or "sha256:" + sha256(path) != expected:
                problems.append(f"hash mismatch or missing file {rel}")
    return problems


def classify(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, CANDIDATE_FAULTS):
        message = str(exc).strip()
        frames = traceback.extract_tb(exc.__traceback__)
        frame = next((item for item in reversed(frames)
                      if Path(item.filename).name in {"case06_verifier.py", "verify.py"}), None)
        if frame is None and frames:
            frame = frames[-1]
        location = ""
        if frame is not None:
            location = f" at {Path(frame.filename).name}:{frame.lineno}"
            if frame.line:
                location += f": {frame.line.strip()}"
        if message:
            return "FAIL", f"{type(exc).__name__}: {message}"
        if location:
            return "FAIL", f"{type(exc).__name__}{location}"
        return "FAIL", f"{type(exc).__name__}: candidate assertion failed without a message"
    return "GRADER_INPUT_ERROR", f"{type(exc).__name__}: {exc}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, required=True)
    parser.add_argument("--tests-dir", type=Path, required=True)
    parser.add_argument("--final-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)


    try:
        refs = json.loads((args.tests_dir / "refs.json").read_text(encoding="utf-8"))
        if not isinstance(refs, dict) or refs.get("case_id") != "case-06":
            raise ValueError("refs.json schema/case id mismatch")
    except Exception as exc:
        report = {"case_id": "case-06", "verifier": "tests/verify.py",
                  "status": "GRADER_INPUT_ERROR", "reason": f"invalid refs.json: {type(exc).__name__}",
                  "reward": None, "deliverables": {name: (args.final_dir/name).is_file() for name in DELIVERABLES}}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2
    report: dict = {
        "case_id": refs.get("case_id", "case-06"),
        "verifier": "tests/verify.py",
        "final_dir": str(args.final_dir),
    }

    problems = check_inputs(args.app_dir, args.tests_dir, refs)
    if problems:
        report.update(status="GRADER_INPUT_ERROR", reason="sourced inputs altered or absent",
                      problems=problems, reward=None)
    else:
        missing = [name for name in DELIVERABLES if not (args.final_dir / name).is_file()]
        try:
            if missing:
                raise FileNotFoundError(
                    "missing deliverables under " + str(args.final_dir) + ": " + ", ".join(missing)
                )
            _phase_verify(args.app_dir / "assets", args.final_dir)
        except BaseException as exc:  # noqa: BLE001  (mapped explicitly below)
            status, detail = classify(exc)
            report.update(status=status, reason=detail, reward=(0 if status == "FAIL" else None))
        else:
            report.update(status="PASS", reason="independent recomputation agrees",
                          reward=1, checks=len(refs.get("criteria", [])))

    report["deliverables"] = {name: (args.final_dir / name).is_file() for name in DELIVERABLES}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return {"PASS": 0, "FAIL": 1}.get(report["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
