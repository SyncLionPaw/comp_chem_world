# 论文与任务映射

来源：既有 28 个 bench，以及 `hx/file-uploads` 分支交付的 bench 29–38。
本文按源 README 汇总论文、DOI 和任务描述；未重新核验论文元数据，也不表示任务逐一复现论文实验。
原始 README 已逐份保存在本目录的各 bench Markdown 文件中；详情、材料来源与许可说明请以对应原文为准。
本索引涵盖 245 个研究任务（编号 001–185、189–248；186–188 暂空）；`tasks/000-hello` 是项目冒烟测试，不映射到论文。

## 总览

| Bench | 论文或参考 | DOI | 对应任务 | 原始说明 |
| --- | --- | --- | --- | --- |
| 01 · activation-energy-mechanistic-modeling | Machine learning meets mechanistic modelling for accurate prediction of experimental activation energies | [10.1039/d0sc04896h](https://doi.org/10.1039/d0sc04896h) | 001–006（6） | [README](01-activation-energy-mechanistic-modeling.md) |
| 02 · alloy-hydrogen-embrittlement | Mechanism and Prediction of Hydrogen Embrittlement in fcc Stainless Steels and High Entropy Alloys | [10.1103/physrevlett.127.175501](https://doi.org/10.1103/physrevlett.127.175501) | 007–013（7） | [README](02-alloy-hydrogen-embrittlement.md) |
| 03 · autosolvateweb-explicit-solvation | Chatbot-assisted quantum chemistry for explicitly solvated molecules | [10.1039/d4sc08677e](https://doi.org/10.1039/d4sc08677e) | 014–020（7） | [README](03-autosolvateweb-explicit-solvation.md) |
| 04 · bicyclic-peroxy-radical-rearrangement | Molecular rearrangement of bicyclic peroxy radicals is a key route to aerosol from aromatics | [10.1038/s41467-023-40675-2](https://doi.org/10.1038/s41467-023-40675-2) | 021–028（8） | [README](04-bicyclic-peroxy-radical-rearrangement.md) |
| 05 · biomolecular-condensate-network-fluids | Biomolecular condensates form spatially inhomogeneous network fluids | [10.1038/s41467-024-47602-z](https://doi.org/10.1038/s41467-024-47602-z) | 029–035（7） | [README](05-biomolecular-condensate-network-fluids.md) |
| 06 · cation-driven-co2-reduction | Cation-induced changes in the inner- and outer-sphere mechanisms of electrocatalytic CO2 reduction | [10.1038/s41467-023-43300-4](https://doi.org/10.1038/s41467-023-43300-4) | 036–041（6） | [README](06-cation-driven-co2-reduction.md) |
| 07 · deep-eutectic-solvent-ml-potentials | Efficient Molecular Dynamics Simulations of Deep Eutectic Solvents with First-Principles Accuracy Using Machine Learning Interatomic Potentials | [10.1021/acs.jctc.3c00944](https://doi.org/10.1021/acs.jctc.3c00944) | 042–048（7） | [README](07-deep-eutectic-solvent-ml-potentials.md) |
| 08 · deepves-variational-enhanced-sampling | Neural networks-based variationally enhanced sampling | [10.1073/pnas.1907975116](https://doi.org/10.1073/pnas.1907975116) | 049–054（6） | [README](08-deepves-variational-enhanced-sampling.md) |
| 09 · first-principles-carrier-scattering | Efficient calculation of carrier scattering rates from first principles | [10.1038/s41467-021-22440-5](https://doi.org/10.1038/s41467-021-22440-5) | 055–061（7） | [README](09-first-principles-carrier-scattering.md) |
| 10 · host-guest-water-enhanced-sampling | The role of water in host-guest interaction | [10.1038/s41467-020-20310-0](https://doi.org/10.1038/s41467-020-20310-0) | 062–069（8） | [README](10-host-guest-water-enhanced-sampling.md) |
| 11 · hsp60-mutation-dynamics | Pathogenic mutation impairs functional dynamics of Hsp60 in mono- and oligomeric states | [10.1038/s41467-025-57958-5](https://doi.org/10.1038/s41467-025-57958-5) | 070–075（6） | [README](11-hsp60-mutation-dynamics.md) |
| 12 · hybrid-dft-extended-excited-states | Excited-State Properties for Extended Systems: Efficient Hybrid Density Functional Methods | [10.1021/acs.jctc.2c00144](https://doi.org/10.1021/acs.jctc.2c00144) | 076–082（7） | [README](12-hybrid-dft-extended-excited-states.md) |
| 13 · infrared-spectra-structure-elucidation | Leveraging infrared spectroscopy for automated structure elucidation | [10.1038/s42004-024-01341-w](https://doi.org/10.1038/s42004-024-01341-w) | 083–087（5） | [README](13-infrared-spectra-structure-elucidation.md) |
| 14 · interfacial-hydration-force | The Dramatic Effect of Water Structure on Hydration Forces and the Electrical Double Layer | [10.1021/acs.jpcc.3c00262](https://doi.org/10.1021/acs.jpcc.3c00262) | 088–095（8） | [README](14-interfacial-hydration-force.md) |
| 15 · layered-materials-pressure-lattice-dynamics | Interlayer engineering of lattice dynamics and elastic constants of 2D layered nanomaterials under pressure | [10.1038/s41467-025-60211-8](https://doi.org/10.1038/s41467-025-60211-8) | 096–102（7） | [README](15-layered-materials-pressure-lattice-dynamics.md) |
| 16 · lithium-titanate-ion-migration | Kinetic pathways of ionic transport in fast-charging lithium titanate | [10.1126/science.aax3520](https://doi.org/10.1126/science.aax3520) | 103–107（5） | [README](16-lithium-titanate-ion-migration.md) |
| 17 · atomistic-simulation-benchmark | 无统一论文；MACE-OFF23 仅对应 Task 110 | [10.1021/jacs.4c07099](https://doi.org/10.1021/jacs.4c07099)（仅 Task 110） | 108–113（6） | [README](17-atomistic-simulation-benchmark.md) |
| 18 · magnesium-dual-cation-cointercalation | Improving rechargeable magnesium batteries through dual cation co-intercalation strategy | [10.1038/s41467-023-44495-2](https://doi.org/10.1038/s41467-023-44495-2) | 114–119（6） | [README](18-magnesium-dual-cation-cointercalation.md) |
| 19 · chemgraph | ChemGraph as an agentic framework for computational chemistry workflows | [10.1038/s42004-025-01776-9](https://doi.org/10.1038/s42004-025-01776-9) | 120–132（13） | [README](19-chemgraph.md) |
| 20 · nep-infrared-raman-spectra | Tensorial Properties via the Neuroevolution Potential Framework: Fast Simulation of Infrared and Raman Spectra | [10.1021/acs.jctc.3c01343](https://doi.org/10.1021/acs.jctc.3c01343) | 133–137（5） | [README](20-nep-infrared-raman-spectra.md) |
| 21 · newtonnet-hessian-transition-states | Analytical ab initio hessian from a deep learning potential for transition state optimization | [10.1038/s41467-024-52481-5](https://doi.org/10.1038/s41467-024-52481-5) | 138–143（6） | [README](21-newtonnet-hessian-transition-states.md) |
| 22 · organic-emitter-rate-constants | Quantitative prediction of rate constants and its application to organic emitters | [10.1038/s41467-024-49069-4](https://doi.org/10.1038/s41467-024-49069-4) | 144–149（6） | [README](22-organic-emitter-rate-constants.md) |
| 23 · protein-drug-quantum-refinement | Accelerating reliable multiscale quantum refinement of protein–drug systems enabled by machine learning | [10.1038/s41467-024-48453-4](https://doi.org/10.1038/s41467-024-48453-4) | 150–154（5） | [README](23-protein-drug-quantum-refinement.md) |
| 24 · silicon-oxygen-active-learning | Modelling atomic and nanoscale structure in the silicon–oxygen system through active machine learning | [10.1038/s41467-024-45840-9](https://doi.org/10.1038/s41467-024-45840-9) | 155–161（7） | [README](24-silicon-oxygen-active-learning.md) |
| 25 · spainn-nonadiabatic-dynamics | SPaiNN: equivariant message passing for excited-state nonadiabatic molecular dynamics | [10.1039/d4sc04164j](https://doi.org/10.1039/d4sc04164j) | 162–166（5） | [README](25-spainn-nonadiabatic-dynamics.md) |
| 26 · w2n3-phonon-superconductivity | Prediction of Phonon-Mediated Superconductivity with High Critical Temperature in the Two-Dimensional Topological Semimetal W2N3 | [10.1021/acs.nanolett.0c05125](https://doi.org/10.1021/acs.nanolett.0c05125) | 167–172（6） | [README](26-w2n3-phonon-superconductivity.md) |
| 27 · wise-lithium-nanochains | Formation of Polymer-like Nanochains with Short Lithium–Lithium Distances in a Water-in-Salt Electrolyte | [10.1021/jacs.3c12488](https://doi.org/10.1021/jacs.3c12488) | 173–178（6） | [README](27-wise-lithium-nanochains.md) |
| 28 · ai2-kit-ai-accelerated-ab-initio-workflows | Ai2-Kit: Streamlining AI-Accelerated Ab Initio Workflows for Complex Chemical Systems | [10.48550/arXiv.2607.00613](https://doi.org/10.48550/arXiv.2607.00613) | 179–185（7） | [README](28-ai2-kit-ai-accelerated-ab-initio-workflows.md) |
| 29 · metals-mlp | Machine-Learned Potentials for Elemental Metals and Alloys | [10.1038/s41467-024-54554-x](https://doi.org/10.1038/s41467-024-54554-x) | 189–195（7） | [README](29-metals-mlp.md) |
| 30 · reactive-nn-zeolite | Reactive Neural-Network Potentials for Water-Loaded Zeolites | [10.1038/s41467-024-48609-2](https://doi.org/10.1038/s41467-024-48609-2) | 196–200（5） | [README](30-reactive-nn-zeolite.md) |
| 31 · openff-sage-2.0 | OpenFF Sage Small-Molecule Force Field | [10.1021/acs.jctc.3c00039](https://doi.org/10.1021/acs.jctc.3c00039) | 201–206（6） | [README](31-openff-sage-2.0.md) |
| 32 · qeq-electrostatics | Charge Equilibration and Electrostatics in Nanoporous Materials | [10.1021/acs.jctc.8b00669](https://doi.org/10.1021/acs.jctc.8b00669) | 207–213（7） | [README](32-qeq-electrostatics.md) |
| 33 · wpd-loop | WPD-Loop Sequence, Structure and Catalytic Activity | [10.1039/D2SC04135A](https://doi.org/10.1039/D2SC04135A) | 214–219（6） | [README](33-wpd-loop.md) |
| 34 · constant-ph-md | Scalable Constant-pH Molecular Dynamics | [10.1021/acs.jctc.2c00516](https://doi.org/10.1021/acs.jctc.2c00516) | 220–225（6） | [README](34-constant-ph-md.md) |
| 35 · binding-pose-metad | Open Binding Pose Metadynamics | [10.1021/acs.jcim.2c01142](https://doi.org/10.1021/acs.jcim.2c01142) | 226–230（5） | [README](35-binding-pose-metad.md) |
| 36 · batio3-data-driven | Data-Driven BaTiO3 Thermodynamics and Dielectric Response | [10.1038/s41524-022-00845-0](https://doi.org/10.1038/s41524-022-00845-0) | 231–236（6） | [README](36-batio3-data-driven.md) |
| 37 · ml-reaction-space | Machine Learning in Chemical Reaction Space | [10.1038/s41467-020-19267-x](https://doi.org/10.1038/s41467-020-19267-x) | 237–242（6） | [README](37-ml-reaction-space.md) |
| 38 · co2-double-layer | Double-Layer Charging and CO2 Reduction on Gold | [10.1038/s41467-019-13777-z](https://doi.org/10.1038/s41467-019-13777-z) | 243–248（6） | [README](38-co2-double-layer.md) |

## 逐任务索引

### 01 · activation-energy-mechanistic-modeling

参考论文：Machine learning meets mechanistic modelling for accurate prediction of experimental activation energies（[DOI: 10.1039/d0sc04896h](https://doi.org/10.1039/d0sc04896h)）。

原始映射：[源 README](01-activation-energy-mechanistic-modeling.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 001](../../tasks/001-task001/) | Audit SNAr geometries, stationary points, thermochemistry, and native execution evidence. |
| [Task 002](../../tasks/002-task002/) | Compare mechanistic descriptors and baselines for predicting experimental activation energies. |
| [Task 003](../../tasks/003-task003/) | Assess representation choices and learning curves on a small reaction dataset. |
| [Task 004](../../tasks/004-task004/) | Evaluate uncertainty calibration, applicability domains, and risk-based prediction filtering. |
| [Task 005](../../tasks/005-task005/) | Assess blinded native ORCA evidence for competing pathways and evidence-quality failures. |
| [Task 006](../../tasks/006-task006/) | Conduct open-ended research on experimental SNAr activation free energies. |

### 02 · alloy-hydrogen-embrittlement

参考论文：Mechanism and Prediction of Hydrogen Embrittlement in fcc Stainless Steels and High Entropy Alloys（[DOI: 10.1103/physrevlett.127.175501](https://doi.org/10.1103/physrevlett.127.175501)）。

原始映射：[源 README](02-alloy-hydrogen-embrittlement.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 007](../../tasks/007-task007/) | Compute hydrogen site preferences in CoCrFeNi and assess numerical and magnetic sensitivity. |
| [Task 008](../../tasks/008-task008/) | Assess hydrogen-coverage stability and conditional surface softening. |
| [Task 009](../../tasks/009-task009/) | Quantify stacking-fault-energy responses and uncertainty from finite-area sampling. |
| [Task 010](../../tasks/010-task010/) | Analyse low-energy hydrogen occupation and finite-spectrum sampling. |
| [Task 011](../../tasks/011-task011/) | Evaluate crack-tip hydrogen occupation and energetic versus entropic free-energy contributions. |
| [Task 012](../../tasks/012-task012/) | Compare intrinsic cleavage and dislocation-emission competition across six alloys. |
| [Task 013](../../tasks/013-task013/) | Analyse crack-tip first-crossing predictions and their comparability with experiments. |

### 03 · autosolvateweb-explicit-solvation

参考论文：Chatbot-assisted quantum chemistry for explicitly solvated molecules（[DOI: 10.1039/d4sc08677e](https://doi.org/10.1039/d4sc08677e)）。

原始映射：[源 README](03-autosolvateweb-explicit-solvation.md)。

Task 015、020 使用已锁定的双架构 Conda 缓存构建环境，构建步骤禁止联网。先执行 `uv run init` 恢复资源；缺失或损坏的缓存会直接报错。定向重测步骤见[环境准备与重测](03-autosolvateweb-explicit-solvation.md#environment-preparation-and-reruns)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 014](../../tasks/014-task014/) | Fit RESP charges for a naphthalene radical cation from supplied geometry and ESP grids. |
| [Task 015](../../tasks/015-task015/) | Construct a consistent periodic solvent model using the supplied six-site acetonitrile parameters. |
| [Task 016](../../tasks/016-task016/) | Diagnose equilibration and statistical reliability in native molecular-dynamics trajectories. |
| [Task 017](../../tasks/017-task017/) | Extract solvent clusters while preserving molecules and periodic-boundary geometry. |
| [Task 018](../../tasks/018-task018/) | Analyse continuum and local-solvent effects for Reichardt's dye. |
| [Task 019](../../tasks/019-task019/) | Validate chemical requests and charge-model choices within the workflow's supported scope. |
| [Task 020](../../tasks/020-task020/) | Diagnose and recover a failed propagation without changing the underlying physical model. |

### 04 · bicyclic-peroxy-radical-rearrangement

参考论文：Molecular rearrangement of bicyclic peroxy radicals is a key route to aerosol from aromatics（[DOI: 10.1038/s41467-023-40675-2](https://doi.org/10.1038/s41467-023-40675-2)）。

原始映射：[源 README](04-bicyclic-peroxy-radical-rearrangement.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 021](../../tasks/021-task021/) | Reconstruct bicyclic-peroxy-radical energy profiles from native quantum-chemistry outputs. |
| [Task 022](../../tasks/022-task022/) | Validate transition states, electronic states, and conformer screening. |
| [Task 023](../../tasks/023-task023/) | Analyse temperature-dependent ring-opening rates and channel branching. |
| [Task 024](../../tasks/024-task024/) | Evaluate conditional radical fates from oxygen-addition, NO-reaction, and loss-rate evidence. |
| [Task 025](../../tasks/025-task025/) | Check consistency of aromatic radical rates across sources and temperatures. |
| [Task 026](../../tasks/026-task026/) | Audit organic-nitrate energies, species identities, and missing evidence. |
| [Task 027](../../tasks/027-task027/) | Independently investigate and validate two ring-opening saddle points for toluene ipso-BPR. |
| [Task 028](../../tasks/028-task028/) | Conduct open-ended research on aromatic radical rearrangement and aerosol formation. |

### 05 · biomolecular-condensate-network-fluids

参考论文：Biomolecular condensates form spatially inhomogeneous network fluids（[DOI: 10.1038/s41467-024-47602-z](https://doi.org/10.1038/s41467-024-47602-z)）。

原始映射：[源 README](05-biomolecular-condensate-network-fluids.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 029](../../tasks/029-task029/) | Estimate correlation lengths from SANS curves while assessing background and sampling sensitivity. |
| [Task 030](../../tasks/030-task030/) | Compare WT and A2-modified FRAP recovery models, time scales, and immobile fractions. |
| [Task 031](../../tasks/031-task031/) | Analyse acidic-segment interaction hierarchies and the limits of RDF-derived pair potentials. |
| [Task 032](../../tasks/032-task032/) | Construct molecular contact networks from trajectories and assess degree distributions. |
| [Task 033](../../tasks/033-task033/) | Identify dynamical regimes and inference limits from mean-squared displacements. |
| [Task 034](../../tasks/034-task034/) | Investigate how an A2 intervention changes condensate structure. |
| [Task 035](../../tasks/035-task035/) | Conduct an independent study of heterogeneous network-fluid behaviour in N130/rpL5 condensates. |

### 06 · cation-driven-co2-reduction

参考论文：Cation-induced changes in the inner- and outer-sphere mechanisms of electrocatalytic CO2 reduction（[DOI: 10.1038/s41467-023-43300-4](https://doi.org/10.1038/s41467-023-43300-4)）。

原始映射：[源 README](06-cation-driven-co2-reduction.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 036](../../tasks/036-task036/) | Analyse CO2 structural fluctuations in water and potassium-containing interfacial trajectories. |
| [Task 037](../../tasks/037-task037/) | Audit velocity-derived vibrational spectra and their mechanistic interpretation. |
| [Task 038](../../tasks/038-task038/) | Assess potential alignment, barrier comparisons, and conditional pathway ordering. |
| [Task 039](../../tasks/039-task039/) | Reanalyse native outer-sphere energy-gap evidence and its statistical limitations. |
| [Task 040](../../tasks/040-task040/) | Analyse local Au–C force responses and numerical consistency in fixed water/potassium environments. |
| [Task 041](../../tasks/041-task041/) | Conduct open-ended research on cation-dependent inner- and outer-sphere CO2 reduction. |

### 07 · deep-eutectic-solvent-ml-potentials

参考论文：Efficient Molecular Dynamics Simulations of Deep Eutectic Solvents with First-Principles Accuracy Using Machine Learning Interatomic Potentials（[DOI: 10.1021/acs.jctc.3c00944](https://doi.org/10.1021/acs.jctc.3c00944)）。

原始映射：[源 README](07-deep-eutectic-solvent-ml-potentials.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 042](../../tasks/042-task042/) | Audit model errors on a small public DFT training and holdout dataset. |
| [Task 043](../../tasks/043-task043/) | Analyse temperature-dependent behaviour in archived short NPT trajectories. |
| [Task 044](../../tasks/044-task044/) | Audit historical CP2K, prediction, and execution records without launching new calculations. |
| [Task 045](../../tasks/045-task045/) | Investigate molecular-centre-of-mass diffusion and its identifiability within a finite budget. |
| [Task 046](../../tasks/046-task046/) | Investigate conductivity estimates with consistent temperature, units, and sampling evidence. |
| [Task 047](../../tasks/047-task047/) | Compare transport observables and finite-size-corrected diffusion across six temperatures. |
| [Task 048](../../tasks/048-task048/) | Independently assess the reliability and transferability of a reline potential. |

### 08 · deepves-variational-enhanced-sampling

参考论文：Neural networks-based variationally enhanced sampling（[DOI: 10.1073/pnas.1907975116](https://doi.org/10.1073/pnas.1907975116)）。

原始映射：[源 README](08-deepves-variational-enhanced-sampling.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 049](../../tasks/049-task049/) | Optimise a static variational bias on the Wolfe–Quapp potential. |
| [Task 050](../../tasks/050-task050/) | Analyse archived online VES trajectories and bias-coefficient histories. |
| [Task 051](../../tasks/051-task051/) | Reconstruct a frozen alanine-dipeptide NN-VES checkpoint. |
| [Task 052](../../tasks/052-task052/) | Analyse model-space expectations and Metropolis transitions in archived chains. |
| [Task 053](../../tasks/053-task053/) | Compute static mechanical quantities for silicon snapshots under frozen neural biases. |
| [Task 054](../../tasks/054-task054/) | Diagnose evidence relationships and information limits in anonymised DeepVES records. |

### 09 · first-principles-carrier-scattering

参考论文：Efficient calculation of carrier scattering rates from first principles（[DOI: 10.1038/s41467-021-22440-5](https://doi.org/10.1038/s41467-021-22440-5)）。

原始映射：[源 README](09-first-principles-carrier-scattering.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 055](../../tasks/055-task055/) | Compare angularly weighted scattering rates and resolve forward-scattering integration. |
| [Task 056](../../tasks/056-task056/) | Analyse directional mobilities and the limits of harmonic mechanism-combination estimates. |
| [Task 057](../../tasks/057-task057/) | Compare constant and temperature-scaled relaxation-time approximations. |
| [Task 058](../../tasks/058-task058/) | Check Seebeck, conductivity, carrier-sign, and mobility consistency. |
| [Task 059](../../tasks/059-task059/) | Generate and validate GaAs first-principles inputs for carrier-scattering calculations. |
| [Task 060](../../tasks/060-task060/) | Assess silicon transport convergence across meshes, energy windows, mechanisms, and concentrations. |
| [Task 061](../../tasks/061-task061/) | Conduct open-ended research on reliable first-principles semiconductor transport. |

### 10 · host-guest-water-enhanced-sampling

参考论文：The role of water in host-guest interaction（[DOI: 10.1038/s41467-020-20310-0](https://doi.org/10.1038/s41467-020-20310-0)）。

原始映射：[源 README](10-host-guest-water-enhanced-sampling.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 062](../../tasks/062-task062/) | Select non-local descriptors of water rearrangement. |
| [Task 063](../../tasks/063-task063/) | Assess whether collective-variable validation is sufficient. |
| [Task 064](../../tasks/064-task064/) | Evaluate free-energy sensitivity, uncertainty, and stopping criteria. |
| [Task 065](../../tasks/065-task065/) | Analyse wet/dry G4 states and proposed water-bridge mechanisms. |
| [Task 066](../../tasks/066-task066/) | Estimate hydration probabilities of an unoccupied host cavity. |
| [Task 067](../../tasks/067-task067/) | Assess water-model effects on host–guest binding free energies. |
| [Task 068](../../tasks/068-task068/) | Integrate limited-budget evidence into an independent water-mechanism and binding decision. |
| [Task 069](../../tasks/069-task069/) | Perform short molecular-dynamics checks and justify whether further computation is warranted. |

### 11 · hsp60-mutation-dynamics

参考论文：Pathogenic mutation impairs functional dynamics of Hsp60 in mono- and oligomeric states（[DOI: 10.1038/s41467-025-57958-5](https://doi.org/10.1038/s41467-025-57958-5)）。

原始映射：[源 README](11-hsp60-mutation-dynamics.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 070](../../tasks/070-task070/) | Analyse WT/V72I monomer flexibility and allosteric communication. |
| [Task 071](../../tasks/071-task071/) | Assess structure-dependent protonation of the Asp50/Asp397 catalytic dyad. |
| [Task 072](../../tasks/072-task072/) | Analyse residue-correlation and distance matrices with consistent residue numbering. |
| [Task 073](../../tasks/073-task073/) | Compare catalytic geometry across assembly and ligand/protonation conditions. |
| [Task 074](../../tasks/074-task074/) | Relate catalytic-dyad geometry to apical conformations in double-ring and football assemblies. |
| [Task 075](../../tasks/075-task075/) | Investigate proton-exchange barriers in small catalytic-dyad models with and without bridging water. |

### 12 · hybrid-dft-extended-excited-states

参考论文：Excited-State Properties for Extended Systems: Efficient Hybrid Density Functional Methods（[DOI: 10.1021/acs.jctc.2c00144](https://doi.org/10.1021/acs.jctc.2c00144)）。

原始映射：[源 README](12-hybrid-dft-extended-excited-states.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 076](../../tasks/076-task076/) | Assess auxiliary-basis convergence of ADMM excited-state geometries. |
| [Task 077](../../tasks/077-task077/) | Compare four response kernels against EOM-CCSD references. |
| [Task 078](../../tasks/078-task078/) | Recompute errors in adiabatic excitation and fluorescence energies. |
| [Task 079](../../tasks/079-task079/) | Audit vertical-excitation statistics, reference mappings, and basis-set limitations. |
| [Task 080](../../tasks/080-task080/) | Assess COF efficiency claims and consistency across computational tables. |
| [Task 081](../../tasks/081-task081/) | Analyse historical native excited-state geometry-optimisation results. |
| [Task 082](../../tasks/082-task082/) | Conduct open-ended research on efficient and reliable excited-state methods. |

### 13 · infrared-spectra-structure-elucidation

参考论文：Leveraging infrared spectroscopy for automated structure elucidation（[DOI: 10.1038/s42004-024-01341-w](https://doi.org/10.1038/s42004-024-01341-w)）。

原始映射：[源 README](13-infrared-spectra-structure-elucidation.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 083](../../tasks/083-task083/) | Identify eight defined functional-group classes from simulated infrared spectra. |
| [Task 084](../../tasks/084-task084/) | Rank constitutional isomers sharing a molecular formula. |
| [Task 085](../../tasks/085-task085/) | Assess prediction stability under controlled spectral perturbations. |
| [Task 086](../../tasks/086-task086/) | Audit published functional-group metrics, denominators, and confusion patterns. |
| [Task 087](../../tasks/087-task087/) | Conduct open-ended computational research on infrared-based structure identification. |

### 14 · interfacial-hydration-force

参考论文：The Dramatic Effect of Water Structure on Hydration Forces and the Electrical Double Layer（[DOI: 10.1021/acs.jpcc.3c00262](https://doi.org/10.1021/acs.jpcc.3c00262)）。

原始映射：[源 README](14-interfacial-hydration-force.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 088](../../tasks/088-task088/) | Compute bulk dielectric response and uncertainty from a new SPC/E production trajectory. |
| [Task 089](../../tasks/089-task089/) | Infer a two-mode dielectric kernel from five supplied response targets. |
| [Task 090](../../tasks/090-task090/) | Calculate hydration pressure using the specified variational boundaries and roughness convention. |
| [Task 091](../../tasks/091-task091/) | Solve the coupled Poisson–Fermi electrical-double-layer model. |
| [Task 092](../../tasks/092-task092/) | Analyse differential capacitance and Parsons–Zobel concentration relationships. |
| [Task 093](../../tasks/093-task093/) | Repair a defective hydration-force solver that suppresses oscillations. |
| [Task 094](../../tasks/094-task094/) | Reconstruct longitudinal dielectric response from a supplied SPC/E trajectory sample. |
| [Task 095](../../tasks/095-task095/) | Evaluate scientific evidence for oscillatory versus monotonic mica hydration forces. |

### 15 · layered-materials-pressure-lattice-dynamics

参考论文：Interlayer engineering of lattice dynamics and elastic constants of 2D layered nanomaterials under pressure（[DOI: 10.1038/s41467-025-60211-8](https://doi.org/10.1038/s41467-025-60211-8)）。

原始映射：[源 README](15-layered-materials-pressure-lattice-dynamics.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 096](../../tasks/096-task096/) | Fit ambient-pressure shear and layer-breathing interlayer force constants. |
| [Task 097](../../tasks/097-task097/) | Analyse pressure coefficients and shear/breathing mode crossings. |
| [Task 098](../../tasks/098-task098/) | Infer spectral features and elastic response from molecular-dynamics data. |
| [Task 099](../../tasks/099-task099/) | Infer force constants using a diatomic-chain model. |
| [Task 100](../../tasks/100-task100/) | Identify few-layer MoS2 modes using native molecular-dynamics evidence. |
| [Task 101](../../tasks/101-task101/) | Analyse Gamma-point phonons and Raman-mode tracking across four pressure points. |
| [Task 102](../../tasks/102-task102/) | Conduct open-ended research on pressure-dependent lattice dynamics. |

### 16 · lithium-titanate-ion-migration

参考论文：Kinetic pathways of ionic transport in fast-charging lithium titanate（[DOI: 10.1126/science.aax3520](https://doi.org/10.1126/science.aax3520)）。

原始映射：[源 README](16-lithium-titanate-ion-migration.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 103](../../tasks/103-task103/) | Extract lithium-migration energy profiles and barriers from native VASP NEB outputs. |
| [Task 104](../../tasks/104-task104/) | Analyse site-resolved core-hole spectra and local structures across lithiation states. |
| [Task 105](../../tasks/105-task105/) | Compare fixed-composition structural-relaxation candidates using native evidence. |
| [Task 106](../../tasks/106-task106/) | Analyse a five-image Li5+x migration path with consistent endpoint and cell evidence. |
| [Task 107](../../tasks/107-task107/) | Assess geometric contacts and pathway connectivity without inferring unavailable energies. |

### 17 · atomistic-simulation-benchmark

该组为六个独立任务，没有统一对应论文。MACE-OFF23 的论文只关联 Task 110；Task 113 使用 CHGNet，不应误列为同篇论文任务。

原始映射：[源 README](17-atomistic-simulation-benchmark.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 108](../../tasks/108-task108/) | Implement silicon flexible-boundary crack mechanics and determine the lattice-trapping range. |
| [Task 109](../../tasks/109-task109/) | Infer absolute phase fractions from multiphase powder diffraction and supporting measurements. |
| [Task 110](../../tasks/110-task110/) | Generate MACE-OFF23 conformer ensembles and consistent Boltzmann populations.（MACE-OFF23 模型参考：[DOI: 10.1021/jacs.4c07099](https://doi.org/10.1021/jacs.4c07099)） |
| [Task 111](../../tasks/111-task111/) | Implement conformer generation subject to distance, angle, and signed-torsion restraints. |
| [Task 112](../../tasks/112-task112/) | Calculate 3C-SiC lattice thermal conductivity from anharmonic force constants. |
| [Task 113](../../tasks/113-task113/) | Calculate LiFePO4 intercalation voltage from consistently relaxed cathode and lithium references. |

### 18 · magnesium-dual-cation-cointercalation

参考论文：Improving rechargeable magnesium batteries through dual cation co-intercalation strategy（[DOI: 10.1038/s41467-023-44495-2](https://doi.org/10.1038/s41467-023-44495-2)）。

原始映射：[源 README](18-magnesium-dual-cation-cointercalation.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 114](../../tasks/114-task114/) | Compare relaxed TiS2, LiTiS2, and NaTiS2 structures and stacking geometry. |
| [Task 115](../../tasks/115-task115/) | Reconstruct Li, Mg, and Na migration barriers from climbing-image NEB outputs. |
| [Task 116](../../tasks/116-task116/) | Interpret Bader electron populations and compare GGA/HSE06 charge redistribution. |
| [Task 117](../../tasks/117-task117/) | Analyse differential Li/Mg charge densities using consistent cells and references. |
| [Task 118](../../tasks/118-task118/) | Compare fixed-composition stacking stability from deposited GGA relaxation outputs. |
| [Task 119](../../tasks/119-task119/) | Investigate Li/Mg and Na/Mg co-intercalation mechanisms with independently generated DFT evidence. |

### 19 · chemgraph

参考论文：ChemGraph as an agentic framework for computational chemistry workflows（[DOI: 10.1038/s42004-025-01776-9](https://doi.org/10.1038/s42004-025-01776-9)）。

原始映射：[源 README](19-chemgraph.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 120](../../tasks/120-task120/) | Convert molecular names into canonical SMILES. |
| [Task 121](../../tasks/121-task121/) | Generate reproducible three-dimensional structures from molecular names. |
| [Task 122](../../tasks/122-task122/) | Optimise name-specified molecular structures with GFN2-xTB. |
| [Task 123](../../tasks/123-task123/) | Calculate molecular vibrational frequencies from a Hessian. |
| [Task 124](../../tasks/124-task124/) | Compute molecular thermochemistry with consistent symmetry and spin conventions. |
| [Task 125](../../tasks/125-task125/) | Write an optimised structure to a molecule-specific coordinate file. |
| [Task 126](../../tasks/126-task126/) | Generate reproducible three-dimensional structures from SMILES. |
| [Task 127](../../tasks/127-task127/) | Optimise SMILES-specified molecular structures with GFN2-xTB. |
| [Task 128](../../tasks/128-task128/) | Calculate vibrational frequencies for SMILES-specified molecules. |
| [Task 129](../../tasks/129-task129/) | Compute thermochemistry for SMILES-specified molecules. |
| [Task 130](../../tasks/130-task130/) | Export SMILES-derived optimised coordinates with the required naming convention. |
| [Task 131](../../tasks/131-task131/) | Compute reaction enthalpies from consistent species-level calculations. |
| [Task 132](../../tasks/132-task132/) | Compute reaction Gibbs free energies with consistent thermal and spin contributions. |

### 20 · nep-infrared-raman-spectra

参考论文：Tensorial Properties via the Neuroevolution Potential Framework: Fast Simulation of Infrared and Raman Spectra（[DOI: 10.1021/acs.jctc.3c01343](https://doi.org/10.1021/acs.jctc.3c01343)）。

原始映射：[源 README](20-nep-infrared-raman-spectra.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 133](../../tasks/133-task133/) | Validate TNEP dipole predictions on a blind evaluation set. |
| [Task 134](../../tasks/134-task134/) | Validate polarizability predictions and QM7B generalisation. |
| [Task 135](../../tasks/135-task135/) | Test rotational equivariance of tensor-property models. |
| [Task 136](../../tasks/136-task136/) | Audit published TNEP numerical results, units, and spectral conventions. |
| [Task 137](../../tasks/137-task137/) | Conduct independent research linking tensor-property models to vibrational spectra. |

### 21 · newtonnet-hessian-transition-states

参考论文：Analytical ab initio hessian from a deep learning potential for transition state optimization（[DOI: 10.1038/s41467-024-52481-5](https://doi.org/10.1038/s41467-024-52481-5)）。

原始映射：[源 README](21-newtonnet-hessian-transition-states.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 138](../../tasks/138-task138/) | Check energy derivatives, Hessians, and unit consistency on a fixed NewtonNet potential. |
| [Task 139](../../tasks/139-task139/) | Analyse curvature bias in paired predicted and DFT Hessian eigenvalues. |
| [Task 140](../../tasks/140-task140/) | Compare NewtonNet and DFT Hessians at four fixed reaction geometries. |
| [Task 141](../../tasks/141-task141/) | Compare full-Hessian and quasi-Newton saddle searches. |
| [Task 142](../../tasks/142-task142/) | Assess saddle-search robustness to controlled perturbations of initial guesses. |
| [Task 143](../../tasks/143-task143/) | Trace downhill paths in both directions and verify reactant/product endpoint identities. |

### 22 · organic-emitter-rate-constants

参考论文：Quantitative prediction of rate constants and its application to organic emitters（[DOI: 10.1038/s41467-024-49069-4](https://doi.org/10.1038/s41467-024-49069-4)）。

原始映射：[源 README](22-organic-emitter-rate-constants.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 144](../../tasks/144-task144/) | Implement unit-safe radiative and thermally activated spin-transition rate kernels. |
| [Task 145](../../tasks/145-task145/) | Integrate exciton-population kinetics and channel-resolved quantum yields. |
| [Task 146](../../tasks/146-task146/) | Determine which rate constants are identifiable from photoluminescence traces. |
| [Task 147](../../tasks/147-task147/) | Compare excited-state methods and state character for benzophenone under fixed settings. |
| [Task 148](../../tasks/148-task148/) | Calculate mode-projected excited-state derivatives with valid state tracking. |
| [Task 149](../../tasks/149-task149/) | Conduct open-ended research on faster RISC in narrowband MR-TADF emitters. |

### 23 · protein-drug-quantum-refinement

参考论文：Accelerating reliable multiscale quantum refinement of protein–drug systems enabled by machine learning（[DOI: 10.1038/s41467-024-48453-4](https://doi.org/10.1038/s41467-024-48453-4)）。

原始映射：[源 README](23-protein-drug-quantum-refinement.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 150](../../tasks/150-task150/) | Audit mapped ligand geometries and stereochemical consistency in the 1XBB system. |
| [Task 151](../../tasks/151-task151/) | Compare quantum-region partitions for 5HLS–62G with a fixed protein environment. |
| [Task 152](../../tasks/152-task152/) | Investigate the isolated NEO molecular model using ORCA and r2SCAN-3c. |
| [Task 153](../../tasks/153-task153/) | Analyse occupancy refinement and its relation to an independent X-ray baseline. |
| [Task 154](../../tasks/154-task154/) | Conduct open-ended research on protein–ligand refinement in the 5HLS–62G system. |

### 24 · silicon-oxygen-active-learning

参考论文：Modelling atomic and nanoscale structure in the silicon–oxygen system through active machine learning（[DOI: 10.1038/s41467-024-45840-9](https://doi.org/10.1038/s41467-024-45840-9)）。

原始映射：[源 README](24-silicon-oxygen-active-learning.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 155](../../tasks/155-task155/) | Compare high-pressure SiO2 equations of state and phase stability from ACE and DFT data. |
| [Task 156](../../tasks/156-task156/) | Analyse finite-temperature SiO2 phase diagrams and free-energy sensitivity. |
| [Task 157](../../tasks/157-task157/) | Assess alpha-quartz surface energies, orientation ordering, and slab-thickness effects. |
| [Task 158](../../tasks/158-task158/) | Compare SiO crystallisation kinetics with structural-scattering changes. |
| [Task 159](../../tasks/159-task159/) | Compare finite-cell quartz/coesite Gibbs free energies at a fixed state and quantify uncertainty. |
| [Task 160](../../tasks/160-task160/) | Evaluate ACE active-learning label efficiency across diverse Si–O environments. |
| [Task 161](../../tasks/161-task161/) | Independently assess a Si–O model across energies, forces, surfaces, and finite-temperature behaviour. |

### 25 · spainn-nonadiabatic-dynamics

参考论文：SPaiNN: equivariant message passing for excited-state nonadiabatic molecular dynamics（[DOI: 10.1039/d4sc04164j](https://doi.org/10.1039/d4sc04164j)）。

原始映射：[源 README](25-spainn-nonadiabatic-dynamics.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 162](../../tasks/162-task162/) | Audit the XAlkeneDB reference database, electronic-state conventions, and training inputs. |
| [Task 163](../../tasks/163-task163/) | Analyse alkene conical-intersection geometries and surface-hopping evidence. |
| [Task 164](../../tasks/164-task164/) | Assess bounded fine-tuning of a nonadiabatic-coupling head and its symmetry properties. |
| [Task 165](../../tasks/165-task165/) | Evaluate an exploratory PaiNN/SHARC dynamics model and justify whether to continue. |
| [Task 166](../../tasks/166-task166/) | Cross-check three-root state-averaged CASSCF properties for two fixed ethylene geometries. |

### 26 · w2n3-phonon-superconductivity

参考论文：Prediction of Phonon-Mediated Superconductivity with High Critical Temperature in the Two-Dimensional Topological Semimetal W2N3（[DOI: 10.1021/acs.nanolett.0c05125](https://doi.org/10.1021/acs.nanolett.0c05125)）。

原始映射：[源 README](26-w2n3-phonon-superconductivity.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 167](../../tasks/167-task167/) | Construct and validate a monolayer W2N3 structure. |
| [Task 168](../../tasks/168-task168/) | Integrate Eliashberg spectra with consistent frequency and coupling conventions. |
| [Task 169](../../tasks/169-task169/) | Analyse strain and doping trends in supplied reconstructed spectra. |
| [Task 170](../../tasks/170-task170/) | Prepare a consistent Quantum ESPRESSO electron–phonon input chain. |
| [Task 171](../../tasks/171-task171/) | Diagnose reconstructed QE/EPW campaigns and distinguish convergence from physical conclusions. |
| [Task 172](../../tasks/172-task172/) | Assess neutral and strained W2N3 phonon stability and superconductivity evidence. |

### 27 · wise-lithium-nanochains

参考论文：Formation of Polymer-like Nanochains with Short Lithium–Lithium Distances in a Water-in-Salt Electrolyte（[DOI: 10.1021/jacs.3c12488](https://doi.org/10.1021/jacs.3c12488)）。

原始映射：[源 README](27-wise-lithium-nanochains.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 173](../../tasks/173-task173/) | Check simulation-box composition and compare SANS length scales with finite-box dimensions. |
| [Task 174](../../tasks/174-task174/) | Characterise Li–Li radial distributions and compare them with literature curves. |
| [Task 175](../../tasks/175-task175/) | Compare lithium contacts and oxygen-bridge topology across two structural frames. |
| [Task 176](../../tasks/176-task176/) | Compare coordination and Li–O–Li angle distributions across distance windows. |
| [Task 177](../../tasks/177-task177/) | Compare calculated and experimental total X-ray scattering curves. |
| [Task 178](../../tasks/178-task178/) | Integrate structural and dynamical observations to assess nanochain-related claims. |

### 28 · ai2-kit-ai-accelerated-ab-initio-workflows

参考论文：Ai2-Kit: Streamlining AI-Accelerated Ab Initio Workflows for Complex Chemical Systems（[DOI: 10.48550/arXiv.2607.00613](https://doi.org/10.48550/arXiv.2607.00613)）。

原始映射：[源 README](28-ai2-kit-ai-accelerated-ab-initio-workflows.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 179](../../tasks/179-task179/) | Generate an isolated water molecule with a chemically valid geometry. |
| [Task 180](../../tasks/180-task180/) | Run three fresh periodic-water CP2K labelling calculations. |
| [Task 181](../../tasks/181-task181/) | Run new water MLMD trajectories with a fixed DeepMD committee. |
| [Task 182](../../tasks/182-task182/) | Analyse oxygen structure in supplied historical water trajectories. |
| [Task 183](../../tasks/183-task183/) | Quantify static hydrogen-bond networks and tetrahedral order. |
| [Task 184](../../tasks/184-task184/) | Diagnose the displacement information available in wrapped water trajectories. |
| [Task 185](../../tasks/185-task185/) | Independently construct and evaluate a water potential using Ai2-Kit. |

### 29 · metals-mlp

参考论文：Machine-Learned Potentials for Elemental Metals and Alloys（[DOI: 10.1038/s41467-024-54554-x](https://doi.org/10.1038/s41467-024-54554-x)）。

原始映射：[源 README](29-metals-mlp.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 189](../../tasks/189-task189/) | Evaluate multicomponent transferability through energy and force prediction errors. |
| [Task 190](../../tasks/190-task190/) | Calculate single-vacancy formation energies in FCC Cu and BCC W and assess size and relaxation convergence. |
| [Task 191](../../tasks/191-task191/) | Compute finite-displacement phonons and diagnose dynamical stability. |
| [Task 192](../../tasks/192-task192/) | Analyse timestep convergence and NVE energy conservation in goldene records. |
| [Task 193](../../tasks/193-task193/) | Identify initial Ni–Ni3Al phase regions and assess static Mo partitioning. |
| [Task 194](../../tasks/194-task194/) | Identify defects and clusters in displacement-cascade configurations. |
| [Task 195](../../tasks/195-task195/) | Compare the finite prediction accuracy and applicability of twelve retained models. |

### 30 · reactive-nn-zeolite

参考论文：Reactive Neural-Network Potentials for Water-Loaded Zeolites（[DOI: 10.1038/s41467-024-48609-2](https://doi.org/10.1038/s41467-024-48609-2)）。

原始映射：[源 README](30-reactive-nn-zeolite.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 196](../../tasks/196-task196/) | Analyse cross-composition energy and force errors and diagnose reference-energy offsets. |
| [Task 197](../../tasks/197-task197/) | Optimise proton-transfer endpoints and test convergence of neural-network-potential reaction paths. |
| [Task 198](../../tasks/198-task198/) | Reconstruct ordinary-metadynamics bias and collective-variable derivatives from CHA histories. |
| [Task 199](../../tasks/199-task199/) | Optimise atomic coordinates and unit cells of eight silica frameworks while checking periodic topology. |
| [Task 200](../../tasks/200-task200/) | Audit local and directional errors in matched MFI DFT and neural-network-potential records. |

### 31 · openff-sage-2.0

参考论文：OpenFF Sage Small-Molecule Force Field（[DOI: 10.1021/acs.jctc.3c00039](https://doi.org/10.1021/acs.jctc.3c00039)）。

原始映射：[源 README](31-openff-sage-2.0.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 201](../../tasks/201-task201/) | Parameterise molecules with Sage and check molecular energy and force consistency. |
| [Task 202](../../tasks/202-task202/) | Perform multi-start conformer minimisation and compare the resulting structures and energies. |
| [Task 203](../../tasks/203-task203/) | Compute constrained relaxed molecular-mechanics torsion scans against quantum reference profiles. |
| [Task 204](../../tasks/204-task204/) | Sample small-system liquid NPT trajectories and estimate liquid densities. |
| [Task 205](../../tasks/205-task205/) | Analyse finite gas-phase MBAR reweighting and identifiability limits. |
| [Task 206](../../tasks/206-task206/) | Refit Sage torsion parameters and evaluate performance on protected validation data. |

### 32 · qeq-electrostatics

参考论文：Charge Equilibration and Electrostatics in Nanoporous Materials（[DOI: 10.1021/acs.jctc.8b00669](https://doi.org/10.1021/acs.jctc.8b00669)）。

原始映射：[源 README](32-qeq-electrostatics.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 207](../../tasks/207-task207/) | Analyse copper-ion spin states and energy differences relevant to charge-equilibration parameters. |
| [Task 208](../../tasks/208-task208/) | Test finite-summation convergence and equivalent-cell representation invariance of periodic charges. |
| [Task 209](../../tasks/209-task209/) | Attribute halogen charge anomalies to local chemical environments. |
| [Task 210](../../tasks/210-task210/) | Compare charge-assignment methods while controlling for unequal coverage. |
| [Task 211](../../tasks/211-task211/) | Assess periodic electrostatic-potential fidelity in accessible pore volume. |
| [Task 212](../../tasks/212-task212/) | Assess charge-model sensitivity of dilute CO₂ adsorption through paired Widom insertion. |
| [Task 213](../../tasks/213-task213/) | Analyse finite-cohort electrostatic adsorption-heat contributions and paired gas comparisons. |

### 33 · wpd-loop

参考论文：WPD-Loop Sequence, Structure and Catalytic Activity（[DOI: 10.1039/D2SC04135A](https://doi.org/10.1039/D2SC04135A)）。

原始映射：[源 README](33-wpd-loop.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 214](../../tasks/214-task214/) | Prepare a phosphocysteine-intermediate system and audit its topology and protonation states. |
| [Task 215](../../tasks/215-task215/) | Analyse active-site coordination, the Asp181 rotamer and WPD-loop conformation. |
| [Task 216](../../tasks/216-task216/) | Measure EVB stationary-point geometries and assign phosphocysteine-hydrolysis reaction stages. |
| [Task 217](../../tasks/217-task217/) | Validate reaction-region topology and EVB force-field parameter integrity. |
| [Task 218](../../tasks/218-task218/) | Analyse static restraint-Hamiltonian responses and deposited restart dependencies. |
| [Task 219](../../tasks/219-task219/) | Integrate kinetic, structural and sequence evidence to assess catalytic effects and inactivity mechanisms. |

### 34 · constant-ph-md

参考论文：Scalable Constant-pH Molecular Dynamics（[DOI: 10.1021/acs.jctc.2c00516](https://doi.org/10.1021/acs.jctc.2c00516)）。

原始映射：[源 README](34-constant-ph-md.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 220](../../tasks/220-task220/) | Run tripeptide constant-pH titrations and estimate pKa values with uncertainty. |
| [Task 221](../../tasks/221-task221/) | Run fixed-pH tripeptide simulations and analyse lambda distributions and protonation populations. |
| [Task 222](../../tasks/222-task222/) | Run protein multisite constant-pH titrations and assess site-specific pKa agreement with experiment. |
| [Task 223](../../tasks/223-task223/) | Validate coarse-grained Martini constant-pH molecular dynamics. |
| [Task 224](../../tasks/224-task224/) | Compare the performance and scaling of conventional and constant-pH molecular dynamics. |
| [Task 225](../../tasks/225-task225/) | Fit Henderson–Hasselbalch titration curves from supplied lambda trajectories. |

### 35 · binding-pose-metad

参考论文：Open Binding Pose Metadynamics（[DOI: 10.1021/acs.jcim.2c01142](https://doi.org/10.1021/acs.jcim.2c01142)）。

原始映射：[源 README](35-binding-pose-metad.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 226](../../tasks/226-task226/) | Compute trajectory contact persistence, ligand displacement and composite pose-stability scores. |
| [Task 227](../../tasks/227-task227/) | Specify a metadynamics protocol and assess Gaussian hill-height choices using source evidence. |
| [Task 228](../../tasks/228-task228/) | Calculate multi-replica ensemble statistics and finite-trajectory convergence diagnostics. |
| [Task 229](../../tasks/229-task229/) | Rerank poses across targets and perform paired statistical comparisons. |
| [Task 230](../../tasks/230-task230/) | Compare MM-GBSA and OpenBPMD ranking performance and examine bounded failure explanations. |

### 36 · batio3-data-driven

参考论文：Data-Driven BaTiO3 Thermodynamics and Dielectric Response（[DOI: 10.1038/s41524-022-00845-0](https://doi.org/10.1038/s41524-022-00845-0)）。

原始映射：[源 README](36-batio3-data-driven.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 231](../../tasks/231-task231/) | Reconstruct polarisation branches and summarise finite polarisation records. |
| [Task 232](../../tasks/232-task232/) | Compare paired QE/GAP energy profiles and evaluate residual corrections with blocked holdouts. |
| [Task 233](../../tasks/233-task233/) | Analyse Ti off-centering in short NVT trajectories and assess order–disorder identifiability. |
| [Task 234](../../tasks/234-task234/) | Calculate spatial dipole-correlation tensors and finite-record ordering contrasts. |
| [Task 235](../../tasks/235-task235/) | Recompute paired-energy free-energy perturbation and assess importance-sampling support. |
| [Task 236](../../tasks/236-task236/) | Derive dielectric response from dipole autocorrelation and compare oscillator fits. |

### 37 · ml-reaction-space

参考论文：Machine Learning in Chemical Reaction Space（[DOI: 10.1038/s41467-020-19267-x](https://doi.org/10.1038/s41467-020-19267-x)）。

原始映射：[源 README](37-ml-reaction-space.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 237](../../tasks/237-task237/) | Audit electronic-reference energies, spin constraints and method comparability in the Rad-6 library. |
| [Task 238](../../tasks/238-task238/) | Analyse reaction-network topology, hub chemistry and mechanistic identifiability. |
| [Task 239](../../tasks/239-task239/) | Compare extensive and intensive SOAP-KRR learning curves. |
| [Task 240](../../tasks/240-task240/) | Assess FPS sampling choices and propagation of molecular-energy errors into reaction energies. |
| [Task 241](../../tasks/241-task241/) | Compare direct and indirect reaction-energy predictions and Hess-cycle consistency. |
| [Task 242](../../tasks/242-task242/) | Analyse Bell–Evans–Polanyi barrier scaling with paired grouped validation and transfer diagnostics. |

### 38 · co2-double-layer

参考论文：Double-Layer Charging and CO2 Reduction on Gold（[DOI: 10.1038/s41467-019-13777-z](https://doi.org/10.1038/s41467-019-13777-z)）。

原始映射：[源 README](38-co2-double-layer.md)。

| 任务目录 | 源 README 中的任务说明 |
| --- | --- |
| [Task 243](../../tasks/243-task243/) | Recover source electrochemical evidence and construct tests of mechanistic identifiability. |
| [Task 244](../../tasks/244-task244/) | Analyse charge-dependent Au adsorbate energies and reference-state corrections. |
| [Task 245](../../tasks/245-task245/) | Solve fixed-activity microkinetic steady states and calculate rate-control and Tafel diagnostics. |
| [Task 246](../../tasks/246-task246/) | Analyse vibrational isotope shifts and construct identifiability counterexamples. |
| [Task 247](../../tasks/247-task247/) | Solve spatial transport under prescribed electrode flux and assess numerical refinement. |
| [Task 248](../../tasks/248-task248/) | Diagnose stationary interfacial feedback using finite-flux probes and response spectra. |

## Environment repair note (2026-11)

2026-11 环境修复：042、061、071–074、110、112、113 的模型执行前失败及复测流程见 [环境修复记录](environment-repairs.md)。015/020 见 Bench 03。
