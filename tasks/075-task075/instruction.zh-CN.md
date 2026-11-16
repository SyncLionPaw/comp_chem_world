# 任务：Asp50/Asp397 二联体质子交换能垒

## 背景

研究低介电蛋白内部环境中 Asp50/Asp397 共享质子的交换；化学问题与模型背景见 `environment/assets/qm_task.md`。使用两个羧酸根（乙酸根或甲酸根）的小片段模型，分别计算无桥连水和含一个桥连水的情形；隐式溶剂介电常数取近似 4。此模型和 3.0 kcal/mol 的分类阈值用于本任务解释，不代表普适物理定律。

## 任务

选择并说明羧酸根、初始构象、桥连水位置及过渡态搜索方法。对每种模型分别定位质子在两侧的两个极小点和一个质子转移过渡态，用频率确认驻点，并由原生电子能量计算正向、反向能垒。判断该模型下交换是否容易；不得预设能垒数值或结论。报告电子能垒，除非确实计算了零点能或热修正；未执行 IRC 时不得声称路径经 IRC 确认。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 geomeTRIC、h5py、NetworkX、NumPy、PySCF、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

如果使用 HPC 计算资源，请查阅 `ikkem-slurm`。

- 提交的每个极小点和过渡态都须有真实程序产生的原生 CML/XML（包括 XML 格式）和匹配的优化 XYZ，不得用手写摘要、合成日志或其他文件代替原生计算证据。每个无水模型组成为乙酸根质子共享模型 C4H7O4 或甲酸根 C2H3O4；桥连水模型分别为 C4H9O5 或 C2H5O5，桥水为位于两羧酸根之间的完整水分子。原生输出需包含优化坐标、Hartree 电子能量、全部 3N−6 个 cm⁻¹ 频率和对应模位移、优化完成及驻点证据、程序/单位、原子、总电荷 −1、自旋多重度 1、方法、基组、隐式溶剂及介电常数。原生输出按以下 CML 约定提交：使用文本内容为数值的唯一 `cc:hfenergy`（`units` 含 `hartree`）、`cc:frequency`、`cc:displacement` 数组，以及 `cc:program`、`cc:method`、`cc:basis`、`g:charge`、`g:mult`、`g:solvent`、`g:eps` 标量。另以 `g:optimization` 文本明确包含 “optimization completed” 和 “stationary point found”；可附 `g:gradientmax`（Hartree/bohr）及 `g:stationarytype`（`minimum` 或 `transition_state`）。这些 `dictRef` 值须逐字匹配；XML namespace 前缀可不同，但 CML 元素须使用 `http://www.xml-cml.org/schema` namespace。`cc:hfenergy`、`cc:frequency`、`cc:displacement` 的文本须分别为一个有限能量值、一个以空格分隔的完整频率数组、一个以空格分隔的位移数组；频率数组和位移数组节点各恰有一个。频率/位移文本顺序须一致：每个频率模式依次列出全部原子的 x,y,z 位移。`cc:program`、`cc:method`、`cc:basis`、`g:charge`、`g:mult`、`g:solvent`、`g:eps` 的值可置于任意后代元素的 `dictRef` 标量中。每个端点的 JSON 能量须与原生能量相差不超过 2×10⁻⁵ Hartree，频率不超过 1 cm⁻¹，XYZ 文件为标准行式文本：首行为原子数，第二行为注释行，随后每行依次为元素符号和 x、y、z（Å）；元素顺序须与 CML 一致，坐标不超过 0.025 Å；若原生输出含最大梯度，极小点不得超过 4×10⁻⁴、过渡态不得超过 5×10⁻⁴ Hartree/bohr。
- 两个极小点须将质子定位在相反羧酸根上，且不得有低于 −20 cm⁻¹ 的显著虚频。过渡态恰有一个低于 −20 cm⁻¹ 的频率；其原生位移对指定 O–H–O 质子转移坐标的绝对归一化投影至少为 0.20。`transfer_atoms` 使用 1 起始索引标明 `oxygen_a`、`proton`、`oxygen_b`。如有轻微负频率（−20 至 0 cm⁻¹）的极小点，结果需人工复核。
- 每个模型报告前向和反向电子能垒（kcal/mol），由过渡态能量减去相应极小点能量并以 627.509474 kcal mol⁻¹ Hartree⁻¹ 换算。JSON 与原生端点重算值的差不得超过 0.02 kcal/mol。报告中说明模型、方法、TS 频率/模态投影、单位换算和局限，不把描述性证据夸大为超出模型的结论。
- 结构化分类按每个模型的最大双向电子能垒执行：阈值固定为 3.0 kcal/mol，低于或等于阈值为 `facile`，高于为 `not_facile`。这只是本任务的操作性解释。自动校准仅适用于 acetate、B3LYP/6-31G(d)、介电常数 3.95–4.05；其他方法/模型路线须标为需专家复核，不等于计算本身失败。
- 遵循主机执行配置及本题运行预算。完成满足上述证据要求的两个模型计算和分析。总执行时间预算为 14,400 秒；计算未完成或缺少交付物均不算完成。

包括显式水模型在内，所研究的质子转移均直接发生在指定的两个羧酸根氧之间。鞍点的两个 O–H 距离须为 0.65–1.55 Å，O–O 距离不超过 2.8 Å。每个极小值的较短 O–H 距离不超过 1.25 Å，较长距离不超过 1.8 Å，二者至少相差 0.15 Å。连通性按 C–O <1.75 Å、乙酸根 C–C <1.85 Å、C–H 或水分子的 O–H <1.25 Å 判断。完整水分子的氧距两个转移氧均不超过 4.25 Å。

### 输入与产物细则

在 `final/` 提交 `barriers.json`、`structures/` 和 `report.md`。`barriers.json` 顶层为 `{"schema":"case06-barriers/v1","models":[...]}`，至少包含一个无水和一个桥连水模型。每模型含唯一非空字符串 `model_id`、布尔值 `bridge_water`、`energy_unit`=`hartree`、`barrier_unit`=`kcal/mol`、整数 `charge`=−1、整数 `multiplicity`=1、非空字符串 `method`/`basis`、`solvent: {model,dielectric}`（model 为 `cpcm,cpcm-like,pcm,implicit` 之一，介电常数 3.5–4.5）、`transfer_atoms: {oxygen_a,proton,oxygen_b}`（三个不同的 1 起始整数索引）、两个 `minima`、一个 `transition_state`、`barriers_kcal_mol: {forward,reverse}` 及 `scientific_assessment`。各端点含有限数 `energy_hartree`、有限数数组 `frequencies_cm-1`（也接受下划线写法 `frequencies_cm_minus_1`）、`native_output` 和 `geometry_xyz` 非空字符串路径；路径相对应用根目录解析，例如 `final/structures/...`。两个极小点的质子定位侧必须相反。

`scientific_assessment` 含 `barrier_basis`=`electronic_energy`、`facile_threshold_kcal_mol`=3.0、由原生端点重算的 `maximum_bidirectional_barrier_kcal_mol` 和 `verdict`。计算路线不属于上述校准范围时，证据完整仍转专家复核；轻微负频极小点（−20≤ν<0 cm⁻¹）也转专家复核。原生梯度只有在输出中提供时才按上述限值检查。在 `report.md` 中以 `<!-- CASE06_SCIENTIFIC_ASSESSMENT_BEGIN` 与 `CASE06_SCIENTIFIC_ASSESSMENT_END -->` 包围匹配的 JSON 块，结构为 `{"schema":"case06-scientific-assessment/v1","models":[{"model_id":"...", ...}]}`，且各模型 assessment 必须与 `barriers.json` 一致；模型顺序也须一致。assessment 至少含非空 `model_id`、`barrier_basis`、有限数 `facile_threshold_kcal_mol` 和 `maximum_bidirectional_barrier_kcal_mol`、`verdict`。可附 `final/native-run.log` 作补充佐证，但它不能取代原生端点输出。原生端点输出须使用 CML/XML 格式；不得伪造原生证据。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `environment/assets/qm_task.md` | 给定数据、参数或方法说明；用途见任务要求。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final/barriers.json` | 结构、频率及电子能垒 |
| `/app/final/structures/` | 端点几何及原生证据 |
| `/app/final/report.md` | 科学解读及评估 |
