# Task: Conduct open-ended research on cation-dependent inner- and outer-sphere CO2 reduction

## Background

Inner- and outer-sphere pathways for CO₂ reduction at a water/Au interface may vary with the potassium-ion environment. Local coordination, interfacial electric fields, hydration structure, configurational sampling, and definitions of electronic or chemical states are interrelated and must be distinguished carefully. This task provides no preset data, models, or calculation results.

Follow the descriptions below for inputs and available resources; independently acquire materials where required.

## Task

Acquire public research materials independently, choose suitable methods, study competition between the two pathway classes in pure water and K-containing conditions, and assess whether existing evidence can distinguish short-range K⁺–CO₂ coordination from changes that co-vary with it, such as the electric field. Provide a substantive, evidence-based mechanistic explanation or an identifiability conclusion.

## Requirements

- Define the system, inner- and outer-sphere pathways, and chemical/electronic states. Specify the compared energy or free energy, potential reference, and ensemble. Justify the applicability of the chosen theory, computation, or data-analysis methods, and report relevant numerical convergence, sampling, and uncertainty analyses.
- For pathway comparisons and causal explanations, describe controls, co-varying factors, and evidence gaps; match the strength of each conclusion to the evidence. Positive, negative, conditional, or currently unidentifiable conclusions are all acceptable, but a research plan or source summary alone does not substitute for analysis results.
- Cite verifiable primary sources and specific data, figures, or methods. Distinguish calculations reported by the original sources, your own analyses, and new calculations actually performed. Provide the materials and reproducible code needed to support your conclusions.
- Public-source acquisition may use the internet. Without separate authorization, do not access private or paywalled sources, submit remote/HPC jobs, or incur costs for computation or data.

### Input and deliverable details

Only a generic Python, shell, and public-source acquisition environment is provided; there are no preset research inputs. Write the following deliverables to `/app/final/`; names and organization for supporting materials and code are up to you:

- `report.md`: a UTF-8 report covering the research question, methods, evidence analysis, conclusions, uncertainties, and limitations.
- `research.json`: `research_question` and `approach` are text; `findings` is a nonempty list whose items contain `claim`, `status`, and `evidence_ids` as a nonempty list referencing source IDs; `decision` contains `status` and `rationale`; `uncertainties` and `limitations` are lists of text. Describe conclusion statuses in terms appropriate to the research.
- `provenance.json`: `sources` is a nonempty list whose items contain a unique `id`, `citation`, a specific `locator`, and `retrieved_on`; all source-record fields must be nonempty text. `files` maps every relative file path in the output directory except `provenance.json` itself to `{sha256, origin, role}`. Record the file’s content checksum as 64 lowercase hexadecimal characters and give nonempty textual source and purpose descriptions. Paths must be normalized and remain within the output directory; update the manifest whenever a file changes.
- Include at least one supporting evidence file. If using computation or modeling, also deliver the corresponding code and derived data. Scientific claims across structured deliverables must be consistent with the report and source materials.

## Files

Public input files:

| File path | Description |
| --- | --- |
| — | No predefined research data are supplied. |

| Path | Contents |
| --- | --- |
| `/app/final/report.md` | research question, methods, evidence analysis, conclusions, uncertainties, and limitations. |
| `/app/final/research.json` | `research_question` and `approach` are text |
| `/app/final/provenance.json` | `sources` is a nonempty list whose items contain a unique `id`, `citation`, a specific `locator`, and `retrieved_on` |
