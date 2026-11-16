# 任务：四个反应几何上的 NewtonNet 与 DFT Hessian 比较

## 背景

随包提供四个过渡态几何（ID `001`、`079`、`205`、`024`），以及在同一结构上计算的
DFT Cartesian Hessian，并给出已训练的 NewtonNet checkpoint。反应路径的曲率分析依赖
模型对参考振动结构的复现程度，尤其是与跨越相关的那几个模态。

## 任务

对每个几何计算固定 checkpoint 的完整 Cartesian Hessian，投影去掉刚体模态，并把得到的
内部模态谱与 DFT 参考比较：本征值、模态对应关系与重叠。对 ID `001`，进一步量化沿某个
匹配模态做受控位移时键长的响应。请说明该比较支持关于模型的哪些结论，以及哪一部分仍受
限于只有四个几何这一范围。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 ASE、JAX、matplotlib、NetworkX、NumPy、pandas、pillow、PyTorch、PyYAML、scikit-learn、SciPy、sympy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 遵循 `analysis_protocol.json`：刚体投影、近简并聚类、子空间比较、两种已公开的模态
  匹配方法、已公开的近简并相对阈值，以及冻结的归一化位移定义。须声明你采用的方法与
  阈值。
- 保持随包的帧顺序。本征值与响应按完整精度报告；比较容差很紧。
  在 `eigenpairs.csv` 中，每个几何可统一使用同序 DFT 本征值，或使用匹配索引处的 DFT 本征值；`matched_dft_mode_index` 与 `abs_overlap` 描述匹配对。
- 在 `metadata.json` 中声明模态匹配方法、近简并阈值，以及 ID `001` 的匹配
  NewtonNet/DFT 模态对和允许的位移步长。请在 `report.md` 中解释选择该模态对和
  步长的科学依据；无需在 metadata 中重复理由。
- 报告每个几何的完整内部模态谱、所用的匹配方法、所选模态对及其证据，并说明四几何范围
  的限制。不要用这四个体系宣称模型的普遍性质。
- 全部计算限于 8 次 Hessian 调用和 40 次能量/力评估。

### 输入与产物细则

输入位于 `/app/assets`：四个几何、配套 DFT Hessian、checkpoint、模型规格、
`analysis_protocol.json` 以及 `output-contract.json`（其中固定了文件名、schema、
单位、顺序、行数与报告需覆盖的内容）。

按契约把四个 Hessian 矩阵、`metadata.json`、`eigenpairs.csv`、
`mode_comparison.csv` 和 `report.md` 写入 `/app/final`。

模本征值、重叠和键长响应的绝对比较容差分别为 2e−5 eV/Å²、2e−5、2e−6 Å。坐标容差为 1e−9 Å，模匹配并列容差为 1e−12。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets` | 给定科学输入或资源；格式和单位见任务要求。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final` | 提交结果；内容与格式按上文要求。 |
