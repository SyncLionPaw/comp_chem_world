# Task: Compare TiS2 interlayer spacing across deposited structures

## Background

The working directory contains seven PBE+D3-relaxed CONTCAR structures for TiS2, LiTiS2 and NaTiS2 in O1/P-3m1, O3/R-3m and R3m stackings. `TiS2_R-3m` is the O3 structure. No new DFT is needed.

## Task

Measure each cell’s lattice-vector lengths and defined interlayer spacing; assess O1 expansion upon Li/Na insertion, whether Na expands more than Li, whether MgTiS2 is represented, and whether the deposited R3m TiS2 cell is a primitive monolayer.

## Requirements

Retain the CONTCAR scale factor and report lengths in Å. Define interlayer spacing as `c/n_Ti` only when `|a-b|≤0.01 Å`, `a<4.5 Å`, and `n_Ti` is 1 or 3; otherwise report `null`. Compare O1 TiS2 with O1 LiTiS2 and NaTiS2: expansion claims require an increase >0.05 Å; Na’s increase must exceed Li’s by a further 0.05 Å. Use only the seven supplied structures.

Write `/app/lattice.json` with schema version 2, a `structures` entry for each of the seven IDs and fields `a_A`, `b_A`, `c_A`, integer `n_Ti`, `interlayer_A`; `methods.interlayer_rule`=`c_over_nTi_if_a_b_hexagonal_and_nTi_1_or_3`; and claims `O1_lithiation_expands_interlayer`, `O1_sodiation_expands_interlayer_more_than_lithiation`, `deposited_GGA_set_contains_MgTiS2`, `R3m_TiS2_is_primitive_monolayer_cell`. Generate `/app/report.md` from that JSON with `/app/environment/assets/render_report.py`.

Length comparisons use an absolute tolerance of 0.001 Å.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Relaxed structures for the seven compositions and phases. |

Read `/app/environment/assets/<structure_id>/CONTCAR` for `TiS2_P-3m1`, `TiS2_R-3m`, `TiS2_R3m`, `LiTiS2_P-3m1`, `LiTiS2_R-3m`, `NaTiS2_P-3m1`, and `NaTiS2_R-3m`. Submit `/app/lattice.json` and `/app/report.md`.
