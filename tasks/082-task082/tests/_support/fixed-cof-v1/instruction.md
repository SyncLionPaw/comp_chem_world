# Task: COF Excited-State Screening with ADMM-PBE0 and sTDA

## Background

The supplied article and supporting information describe COF 05001N2 (CURATED COFs identifier 05001N2), its periodic model, electronic-structure methods, spectra, and published comparisons. The sources are under `/app/inputs/`.

## Task

Verify that the public structure matches SI Table 52 and article Table 4. Reoptimize its fixed periodic cell with ADMM-PBE0/ccGRB-T+tzp. At that ground-state geometry, calculate the lowest 500 singlet excitations and oscillator strengths with full ADMM-PBE0 and sTDA@ADMM-PBE0, For each response kernel, optimize the S1 geometry with an eight-state manifold. Compare vertical excitation, electronic adiabatic excitation, fluorescence, and Stokes-shift energies with the single-system 05001N2 values in article Table 5.

## Requirements

1. Identify the retrieved structure and compare it with SI Table 52 and article Table 4. Report the cell, composition, atom and basis-function counts, retrieval source, coordinate or symmetry processing, source pages, and extraction method. Preserve inputs, full native CP2K logs, final geometries, and convergence evidence for the fixed-cell ground-state optimization, both 500-state calculations, and both eight-state S1 optimizations. Include state-ordering and transition-character evidence along each excited-state optimization, a reproducible spectrum-processing method with source-supported broadening, convergence checks, run time, and cost components.
2. Report both methods’ vertical, electronic adiabatic, fluorescence, and Stokes-shift energies beside the Table 5 single-system values, with definitions and citations. Use `Ead = E0(R_ES) + ω1(R_ES) − E0(R_GS)`; the CP2K excited-state total at the optimized geometry already includes S1 energy, so do not add it twice. Keep electronic and vibrational 0–0 energies distinct. Report a 0–0 value only with a supported zero-point correction for this same model; otherwise mark it unavailable and explain the unresolved article convention.
3. State the accuracy threshold, its independent basis, and the numerical error budget before comparing kernels; do not infer a single-COF threshold from multi-COF mean errors or relax it after seeing results. Quantify sensitivity, uncertainty, and margin to the threshold, including printed-value rounding and unit conversion. Check energy differences, the Stokes identity, state continuity, spectral shape, numerical convergence, and computational cost. Give a screening assessment with limitations; do not fit to published values or claim reproduction without evidence.
4. Base scientific conclusions on complete native execution evidence and independent scientific review. Report only calculations actually performed with authorized compute resources. Keep missing evidence and unresolved uncertainty explicit; do not present an incomplete run as a completed scientific result.

## Files

Place the research record under `/app/final/`:

- `geometries/`: ground-state and both excited-state geometries, corresponding inputs, and full native CP2K logs;
- `spectra/`: both 500-state energy and oscillator-strength sets, plus processing code or parameters;
- `table5.csv`: both methods’ four energy quantities and the published single-system values, with definitions;
- `report.md`: screening assessment, literature comparison, numerical and cost analysis, uncertainty, and unresolved issues;
- `provenance.json`: structure retrieval, inputs, outputs, parameters, and traceability for reported values.

The public output-format reference at [`/app/inputs/case07-output-contract-v1.schema.json`](/app/inputs/case07-output-contract-v1.schema.json) defines submission fields and `table5.csv` columns. It describes the record format, not scientific approval.
