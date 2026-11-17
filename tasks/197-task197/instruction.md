# MFI stored-label local and directional consistency audit

## Background

Use stored same-geometry DFT and NNP labels for MFI to analyze energy gauges and force errors in local chemical environments and displacement directions.

The inputs pair energy and force labels at the same geometries and document their provenance and theory-level limitations.

## Task

Audit the100 original author MFI_2D_1600K same-geometry DFT-labelled/NNP-labelled pairs in `/app/inputs/matched_snapshots.npz`. Each snapshot has810 atoms (H350O365Si95); stored isotopic masses are authoritative. The array frame_id is the original source identity, not a trajectory time. Data are publicly supplied, including both label sets. This is a retrospective numerical and chemical audit, not training, prospective uncertainty calibration or new simulation.

## Requirements

Read `/app/inputs/source_provenance.json`. All numbers, positions, cells, PBC, masses and energy/force labels are preserved without fitting. Stored VASP metadata lacks `metagga` and `ivdw` and records `lmetagga=false`; it cannot certify SCAN+D3(BJ), PAW identity or convergence. Use the term **stored DFT-labelled reference**. Attribute Erlebach et al., paper doi:10.1038/s41467-024-48609-2 and data doi:10.5281/zenodo.10361794, CC-BY-NC-SA-4.0.

Cutoffs are finite numbers in [1.8,2.2] and [1.05,1.25]Å; reference_frame is an integer0…99; review_budget is an integer5…30; priority_metric is global_component_rmse, local_max_vector or direction_max. Explain your geometry, gauge and retrospective inspection choices in `analysis.md`. Choices freeze before the controlled replay.

For **all100 frames**, subtract stored NNP minus stored DFT forces and retain every atom's vector-error norm. Report component RMSE over3N, largest atom-vector error and its lowest-index maximizer. Report raw total-energy differences and common-reference relative residuals per atom in meV. Use exact arithmetic on stored binary64 energies before the final rounding; a large method-dependent energy zero must not enlarge the comparison budget. Report the mean raw difference, fixed-reference relative RMSE, and mean-centered RMSE. A centered energy score cannot identify a unique physical cause for the offset.

Evaluate the full Cartesian family SiO={1.8,2.0,2.2}Å × OH={1.05,1.15,1.25}Å, plus your chosen pair if distinct. All distances use minimum-image periodic vectors; only strict distance<cutoff edges count. For each definition/frame:

1. Count each O's Si and H neighbors. Active O has at least one Si neighbor and either at least one H neighbor or a Si coordination other than2. This geometric set includes undercoordinated/protonated network oxygen; it does not identify a reaction event.
2. The active atom set is these O atoms and every Si/H neighbor attached to them under those cutoffs. Report sorted O/atom IDs, local component RMSE and maximum atom-vector error, retaining all active atoms.
3. For every active-O→neighbor edge, let u be the periodic O→neighbor unit vector. Compute `(ΔF_neighbor−ΔF_O)·u/sqrt(2)`: projection onto a normalized3N relative-displacement direction. Report edge count, largest absolute projection, RMS projection and worst [O,neighbor], breaking ties lexicographically. This is a force-error diagnostic, not proof of dynamics or stability.

For your chosen geometry, rank all100 frames separately by each of the three priority metrics in descending order, ties by source frame ID. For each ranking report the first K source IDs and the maximum omitted local-vector and directional errors. Include all three alternatives and identify the chosen one. Since all DFT labels are visible, this quantifies retrospective inspection coverage only; it is not a prospective acquisition-policy test.

`analysis.py --inputs INPUT_DIR --output EMPTY_OUTPUT_DIR` must regenerate audit.json using only that directory. Recompute for original and bounded synthetic NNP-label/reorder inputs. A synthetic replay is a data-dependence control, not new scientific data. No historical execution receipt, licensed DFT engine, model inference or MD run is required.

The arithmetic gate is256 binary64 eps × max(1,abs(reference)) per finite output scalar; identity, integer denominators and scope fields are exact. This checks faithful calculations of observed errors, not whether the model errors are scientifically small. Both good and poor agreement are valid complete outcomes. Do not infer unseen-geometry truth, SCAN convergence, a six-model committee, water-mediated events, event rates, or population generalization.

Network access is disabled.

- Submit the required results and evidence under `/app/` according to the listed output convention. Use `/app/analysis.py` as the analysis entry point; `/app/code` may contain optional helpers.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Paired energy and force labels and method descriptions. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/public/output-contract.yaml` | Required outputs and submission format. |
