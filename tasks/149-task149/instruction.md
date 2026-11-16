# Accelerating reverse intersystem crossing in MR-TADF emitters

## Background

Multiple-resonance thermally activated delayed fluorescence (MR-TADF) combines narrow emission with triplet harvesting. Faster reverse intersystem crossing (RISC) is useful only if radiative rate, single-exciton photoluminescence quantum yield and emission width remain favorable. No molecule, baseline or numerical target is prescribed.

## Task

Investigate whether RISC can be accelerated without sacrificing those properties. Define the research scope, comparison and stopping point, then give the strongest conclusion supported by the evidence. Negative or unresolved findings are valid outcomes.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, SciPy. Do not install additional packages or fetch dependencies from the network.

- Explain the research question, source-selection strategy, baseline, methods and comparability of the evidence. An improvement claim requires a comparison covering RISC, radiative rate, quantum yield and emission FWHM under compatible conditions.
- Distinguish reported evidence, new analysis and proposed work. Discuss uncertainty, conflicting evidence, limitations and the reason for stopping; preserve the material supporting quantitative claims. Scientific conclusions remain subject to independent review.
- Conduct source research and analysis in the provided task container; do not submit remote jobs. The wall-time budget is 12 hours. Public network access, Python 3.12, NumPy, SciPy, Poppler and retrieval tools in `/app/tools/` are available. Respect source access conditions and licenses.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/output-interface.md` | Submission and evidence conventions for the open study. |

Use `/app/output-interface.md` for the existing record formats. Submit under `/app/final/`:

| Path | Contents |
| --- | --- |
| `report.md` | Question, methods, evidence synthesis, conclusion, uncertainty and limitations. |
| `research.json` | Structured research record. |
| `sources.json` | Source inventory and provenance. |
| `native/` | Retained source documents, retrieved metadata, extracts and analysis code, with an inventory. |
