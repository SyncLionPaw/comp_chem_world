#!/usr/bin/env python3
"""Reference solution for case-04 (oracle replay material).

Writes a budget-estimated QE 7.2 native EPC input chain plus plan.json into argv[1]
(default ./final-out). This is a static template, not a measured or executed
QE workflow. Structure taken from the
provided monolayer POSCAR (a=2.9131 A), cell height kept at 25.15 A.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

A_ANG = 2.9130614778
C_ANG = 25.1518869092
CELL = [[A_ANG, 0.0, 0.0], [-A_ANG / 2, A_ANG * 3 ** 0.5 / 2, 0.0], [0.0, 0.0, C_ANG]]

HEADERS = {
    "scf.in": f"""&CONTROL
  calculation = 'scf',
  prefix = 'W2N3',
  outdir = './tmp',
  pseudo_dir = './pseudo',
  tprnfor = .true.,
/
&SYSTEM
  ibrav = 0,
  nat = 5,
  ntyp = 2,
  ecutwfc = 80.0,
  occupations = 'smearing',
  degauss = 0.01,
  la2F = .true.,
/
&ELECTRONS
  conv_thr = 1.0d-8,
  mixing_beta = 0.3,
  electron_maxstep = 200,
/
ATOMIC_SPECIES
 W  183.84  W_ONCV_PBE-1.0.upf
 N   14.007  N_ONCV_PBE-1.0.upf
CELL_PARAMETERS angstrom
 {CELL[0][0]:18.12f} {CELL[0][1]:18.12f} {CELL[0][2]:18.12f}
 {CELL[1][0]:18.12f} {CELL[1][1]:18.12f} {CELL[1][2]:18.12f}
 {CELL[2][0]:18.12f} {CELL[2][1]:18.12f} {CELL[2][2]:18.12f}
ATOMIC_POSITIONS (crystal)
 W  0.6666666667  0.3333333333  0.4416442081
 W  0.6666666667  0.3333333333  0.5583557919
 N  0.3333333333  0.6666666667  0.3973543531
 N  0.3333333333  0.6666666667  0.6026456469
 N  0.3333333333  0.6666666667  0.5000000000
K_POINTS automatic
 64 64 1 0 0 0
""",
    "coarse_scf.in": f"""&CONTROL
  calculation = 'scf',
  prefix = 'W2N3',
  outdir = './tmp',
  pseudo_dir = './pseudo',
/
&SYSTEM
  ibrav = 0,
  nat = 5,
  ntyp = 2,
  ecutwfc = 80.0,
  occupations = 'smearing',
  degauss = 0.01,
/
&ELECTRONS
  conv_thr = 1.0d-8,
/
ATOMIC_SPECIES
 W  183.84  W_ONCV_PBE-1.0.upf
 N   14.007  N_ONCV_PBE-1.0.upf
CELL_PARAMETERS angstrom
 {CELL[0][0]:18.12f} {CELL[0][1]:18.12f} {CELL[0][2]:18.12f}
 {CELL[1][0]:18.12f} {CELL[1][1]:18.12f} {CELL[1][2]:18.12f}
 {CELL[2][0]:18.12f} {CELL[2][1]:18.12f} {CELL[2][2]:18.12f}
ATOMIC_POSITIONS (crystal)
 W  0.6666666667  0.3333333333  0.4416442081
 W  0.6666666667  0.3333333333  0.5583557919
 N  0.3333333333  0.6666666667  0.3973543531
 N  0.3333333333  0.6666666667  0.6026456469
 N  0.3333333333  0.6666666667  0.5000000000
K_POINTS automatic
 16 16 1 0 0 0
""",
    "ph.in": """&INPUTPH
  prefix = 'W2N3',
  outdir = './tmp',
  fildyn = 'W2N3.dyn',
  tr2_ph = 1.0d-10,
  electron_phonon = 'interpolated',
  fildvscf = 'W2N3.dvscf',
  epsil = .false.,
  ldisp = .true.,
  nq1 = 4,
  nq2 = 4,
  nq3 = 1,
/
""",
    "q2r.in": """&INPUT
  fildyn = 'W2N3.dyn',
  flfrc = 'W2N3.fc',
  zasr = 'simple',
  la2F = .true.,
/
""",
    "matdyn.in": """&INPUT
  flfrc = 'W2N3.fc',
  asr = 'simple',
  la2f = .true.,
  dos = .true.,
  nk1 = 96,
  nk2 = 96,
  nk3 = 1,
  fldos = 'W2N3.phdos.dat',
  ndos = 400,
/
""",
    "run.sh": """#!/usr/bin/env bash
set -euo pipefail
# QE 7.2 example03 sequence; q weights/files are matched from actual PH outputs.
pw.x < scf.in > scf.out
pw.x < coarse_scf.in > coarse_scf.out
ph.x < ph.in > ph.out
q2r.x < q2r.in > q2r.out
matdyn.x < matdyn.in > matdyn.out
python3 make-lambda-input.py --scf scf.in --elph-root elph_dir --mesh 4 4 1
lambda.x < lambda.in > lambda-mu016.log
cp alpha2F.dat alpha2F-mu016.dat
cp lambda.dat lambda-mu016.dat
lambda.x < lambda-mu010.in > lambda-mu010.log
cp alpha2F.dat alpha2F-mu010.dat
cp lambda.dat lambda-mu010.dat
""",
}

plan = {
    "route": "qe_native",
    "qe_target": "QE 7.2",
    "execution_order": ["dense_scf_fit", "coarse_scf", "ph", "q2r", "matdyn_a2f", "lambda_postprocess"],
    "lambda_q_mapping": {"mesh": [4, 4, 1], "points": "automatic unshifted QE phonon mesh with crystal-symmetry reduction", "weights": "spglib full-grid orbit multiplicities; QE Cartesian tpiba headers are converted to crystal coordinates, located on the full grid, then mapped to the orbit independent of representative choice", "files": "QE 7.2 writes elph.inp_lambda.N under elph_dir; helper bijectively matches actual headers to mesh orbits; aborts if count, coordinates, or weight sum disagree"},
    "structure": {"source": "W2N3-monolayer.poscar", "n_atoms": 5, "cell_height_z_A": 25.15},
    "cutoffs": {"ecutwfc_ry": 80.0, "ecutrho_ry": 320.0},
    "smearing": {"occupations": "smearing", "degauss_ry": 0.01},
    "grids": {"dense_scf_k": [64, 64, 1], "coarse_scf_k": [16, 16, 1], "q": [4, 4, 1]},
    "estimated_core_hours": {"dense_scf": 24.0, "coarse_scf": 2.0, "ph": 36.0, "post": 6.0, "total": 68.0},
    "estimate_basis": "Planning estimates only; costs are not benchmarked and no QE production run was performed. Validate with a small representative q-point before committing resources.",
    "justifications": {
        "dense_scf_k": "The 64x64x1 unshifted dense grid is a budgeted planning choice below the paper's 192x192 grid for the QE 7.2 la2F fit. Its convergence error and direction are not established by available calculations; compare with a finer grid before treating lambda or Tc as converged.",
        "coarse_scf_k": "The 16x16x1 coarse SCF grid is a planning choice for the phonon step, paired with the separate dense la2F fit. The 4x4x1 q mesh is coarser than the paper's 8x8 mesh, so the error direction and size are unresolved; Fourier interpolation to a dense matdyn grid cannot recover DFPT physics missing from the coarse q mesh.",
        "q": "The 4x4x1 DFPT q mesh is an unbenchmarked budget choice under the declared phonon-hour cap. It may miss acoustic softening or other q-dependent structure; a denser q convergence comparison is required, and interpolation does not compensate for absent q samples.",
        "degauss": "The 0.01 Ry Gaussian smearing matches the stated paper parameter, but Tc stability across 0.005-0.02 Ry has not been assessed for this template. Check smearing sensitivity together with k-grid convergence before claiming a converged Tc.",
    },
    "notes": "QE 7.2 example03 native interpolation protocol. The helper creates lambda.x input only after actual PH q files exist. This static plan is not a QE execution or proof that 300/40 core-hour estimates are achievable.",
}


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "final-out").resolve()
    out.mkdir(parents=True, exist_ok=True)
    HEADERS["make-lambda-input.py"] = Path(__file__).with_name("make-lambda-input.py").read_text(encoding="utf-8")
    for name, text in HEADERS.items():
        (out / name).write_text(text, encoding="utf-8")
    (out / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
                                   encoding="utf-8")
    print(f"wrote input chain + plan.json to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
