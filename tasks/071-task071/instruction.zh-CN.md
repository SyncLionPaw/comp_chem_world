# 任务：Hsp60 催化二联体的结构质子化评估

## 背景

`/app/assets/` 提供 apo 单环 S_V72I、ATP 结合双环 D_V72I 和 football F_V72I 的 Amber 拓扑与坐标。输入中 Asp50 和 Asp397 均为去质子化态。拓扑没有链标识；按重复序列识别第一条完整 Hsp60 单体链。成熟编号与系统编号的映射因体系而异：S 中成熟 Asp50/Asp397 对应系统残基 51/398；D、F 中对应 50/397。研究的生理 pH 范围为 7.0–7.4。

## 任务

对 S_V72I、D_V72I 和 F_V72I 中 Asp50 与 Asp397 的结构环境进行 pKa 估计，分析 ATP、Mg²⁺、K⁺及口袋环境可能造成的差异，并建议后续模拟应优先考察的二联体质子化状态。选择并说明配体/金属处理和选区策略。单点 pKa 不是二联体微观状态概率；不要把两个位点的独立估计组合成联合占比。结论须反映预测方法和结构模型的局限，不预设数值或生物学结果。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、ParmEd、PROPKA、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

使用从所给拓扑和坐标导出的第一条 Hsp60 完整蛋白链作为链 A。S、D、F 分别按各自编号映射定位目标残基。D、F 还须记录活性位点 ATP、Mg 和 K 的保留或排除策略及化学理由，并将清单中的辅因子映射回输入拓扑和坐标。为统一结构选区，使用距 Asp50/Asp397 的 CG、OD1、OD2 原子 12.0 Å 的选择半径并保留该范围内的原生 ATP/Mg/K；其他有依据的选择可提交完整证据，但会转专家复核。

基准计算方法为 PROPKA 3.5.1。必须从实际提交的链 A 结构运行预测，保留每个体系的原始 `.pka` 文件、完整工具版本、实际命令和退出码；不得以外部数值或示例结果代替。其他 PROPKA 3.x 版本或预测器须提交相应原始输出和完整来源证据，并按需进行专家复核。说明 PROPKA 不提供经过校准的置信区间，点估计不应被解释为此类区间。

### 输入与产物细则

在 `final/` 提交 `pka.json`、`protonation_plan.json`、`report.md` 及以下证据：`evidence/structures/` 下的 `S_V72I_chainA_site.pdb`、`D_V72I_chainA_site.pdb`、`F_V72I_chainA_site.pdb` 和 `selection_manifest.json`；`evidence/provenance.json`；以及 `evidence/propka/` 下三个同名体系的原始 `.pka` 文件。PDB 须保留完整第一条蛋白链及所有纳入的完整辅因子残基，并使用链 A 和原生系统残基编号；同时保留原生残基名与原子名（含 Amber 组氨酸名 `HID`/`HIE`/`HIP` 及离子名），因为 PROPKA 的质子化模型依赖这些名称。

`pka.json` 的 `schema_version` 为 `case02-pka/v1`，`physiological_ph_range` 为 `[7.0,7.4]`；`method` 记录 `name`、`version` 和非空 `uncertainty`。`systems` 恰含 `S_V72I`、`D_V72I`、`F_V72I` 三项。每项以 `Asp50`、`Asp397` 为键，分别记录数值 `pka`、整数 `mature_residue`、`system_residue`；同级另含 `input_structure_sha256`、`source_topology_sha256`、`source_coordinates_sha256` 和相对 `final/` 的 `evidence` 路径。S 的系统残基编号为 51/398，D、F 为 50/397。PROPKA 版本采用完整格式，如 `propka3 3.5.1`；JSON 数值应为数字而非字符串。

`protonation_plan.json` 的 `schema_version` 为 `case02-protonation-plan/v1`；`physiological_pH` 含 `minimum: 7.0`、`maximum: 7.4`、`reference: 7.2`。`state_names` 定义：`AspAsp` = `Asp50− / Asp397−`，`AshAsp` = `Asp50H / Asp397−`，`AspAsh` = `Asp50− / Asp397H`，`AshAsh` = `Asp50H / Asp397H`。`systems` 恰含三个体系；每项含与 pKa 结果一致的 `predicted_pka`，以及以四个状态名为键的 `assessed_states`。每个状态对象含 `decision`（`recommended`、`sensitivity` 或 `low_priority`）和非空 `rationale`。`recommended_states` 为非空状态名数组，且恰与标为 `recommended` 的状态一致。`coupling_caveat` 非空，说明独立位点估计不能表示耦合二联体的微观态概率。

`selection_manifest.json` 使用 `schema: case02-propka-inputs/v1`，顶层含 `systems`，恰以三个体系名为键。每项的 `input_topology`、`input_coordinates` 含输入实际文件校验值的 `sha256`。`selection` 含整数 `protein_residue_count`（526）、`pdb_chain`（`A`）、整数 `protein_atom_count`、`retained_atom_count`、非空 `ligand_policy`、数值 `cofactor_radius_angstrom` 和 `cofactor_residues` 数组。每个辅因子对象含 `name`、整数 `topology_residue_number`、`nearest_dyad_distance_angstrom`、布尔 `included`；距离是辅因子任一原子至任一目标 Asp 的 CG/OD1/OD2 原子的最小距离，记录到 4 位小数。`target_residues` 以字符串键 `"50"`、`"397"` 索引；每项含 `system_residue_number`、`topology_residue_index_1based`、`residue_name`（`ASP`）、`cg_coordinate_angstrom`，及恰含 `CG`、`OD1`、`OD2` 的 `atoms` 对象。每个原子对象含 `topology_atom_index_1based`、`coordinate_angstrom`（原始精度三数值数组）、`bonds`（按名称排序）。`structure` 含 PDB 基名 `path` 和实际 `sha256`。完整蛋白和纳入的完整辅因子 PDB 坐标须对应输入，不能只提交口袋片段；PDB 坐标精度为 0.001 Å。

`provenance.json` 记录 `case_id: case-02-dyad-protonation`、与 `pka.json` 一致的 `propka_version`、实际 `selection_manifest_sha256`，及以体系名为键的 `systems` 对象。每体系含 `command`（实际参数数组）、整数 `returncode`（成功为 0）、`pdb: {path, sha256}`、`source_topology_sha256`、`source_coordinates_sha256`、`parsed_pka: {Asp50, Asp397}`，以及 `pka_output: {path, sha256}`。PROPKA 计算命令使用 `propka3 --log-level INFO`，PDB 为最后一个参数。`report.md` 应以可读文字说明 pH 范围、估计不确定性、ATP/Mg/K 处理、四种状态、六个 pKa、结构选择、编号和解释限制，并与结构化数据和实际证据一致。

只将结果与证据写入上述 `final/` 路径。用提交的原生拓扑、坐标、PDB、选择清单和 PROPKA 输出使其他研究者能够复现链选择、辅因子处理、原子映射及 pKa 解析；不得声称执行未实际运行的命令或采用未实际使用的方法。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 给定输入与资源目录。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final` | 提交结果；内容与格式按上文要求。 |
