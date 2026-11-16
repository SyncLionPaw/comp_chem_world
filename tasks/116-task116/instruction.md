# Task: Interpret Bader charge changes in TiS2 and LiTiS2

## Background

Bader ACF.dat and matching POSCAR files are supplied for primitive TiS2 and LiTiS2 in GGA and HSE06. `CHARGE` is electron population in a Bader basin, not oxidation state; no HSE06 rerun or projected `LORBIT` population is provided.

## Task

Quantify element-wise Bader electron-count changes on lithiation for each functional. Assess whether the total gain on the two S atoms exceeds the Ti gain and whether these Bader values alone establish sulfur redox inactivity.

## Requirements

Average `CHARGE` by element for each of the four systems. For each functional, define lithiation change as LiTiS2 minus TiS2; report `S_mean` per S and `S_total=2*S_mean` for the two-S primitive cell. Compare `Ti` gain with `S_total` separately for GGA and HSE06. Do not mix projected populations with Bader values. Use the gain comparisons to describe charge redistribution. Bader electron counts alone cannot establish sulfur redox inactivity, regardless of which gain is larger.

Write `/app/charges.json`, schema version 2, with systems `TiS2_GGA`, `TiS2_HSE06`, `LiTiS2_GGA`, `LiTiS2_HSE06` and mean element counts; `deltas.GGA/HSE06` with `Ti`, `S_mean`, `S_total`; claims `GGA_S_total_gain_exceeds_Ti`, `HSE06_S_total_gain_exceeds_Ti`, `bader_alone_shows_sulfur_redox_inactive`; and fixed method labels `charge_quantity=bader_basin_electrons`, `sulfur_aggregation=mean_and_two_atom_total`. Generate `/app/report.md` with the supplied renderer.

Electron population comparisons use an absolute tolerance of 0.002 electrons.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Bader populations and matching structures. |

Read `ACF.dat` and `POSCAR` under `/app/environment/assets/<system_id>/` for the four systems. Submit `/app/charges.json` and `/app/report.md`.
