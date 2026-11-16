# 迁移率各向异性与限制机制诊断

## 背景

材料迁移率张量随载流子浓度、温度和方向变化。不同机制的迁移率与整体迁移率之间是什么关系？由宏观迁移率构造的调和估计在何种条件下适用？

## 任务

用给定的 GaAs、GaN、Si 和 SnSe 传输数组，按相同材料、浓度、温度和方向比较整体迁移率与各机制迁移率，评估调和估计的偏差。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 按公开输出契约提交每种材料所有输入浓度、温度及 `xx/yy/zz` 方向的 `results.json`；逐条件计算 `harmonic_proxy=1/sum(1/mu_mechanism)` 和 `(harmonic_proxy-overall)/overall`。
- 报告各材料的机制限制趋势、SnSe 的方向差异，并用实际结果解释宏观调和估计的适用边界。报告证据覆盖要求见公开输出契约。
- 提交可复算的 `analysis.py`、运行记录 `run.log` 和科学摘要 `report.md`。脚本须使用 `python analysis.py --inputs environment/assets --output final` 读取公开数组并生成结果；记录格式见公开输出契约。不要用外部抄录值替代数组分析。
- 将四个必需文件 `results.json`、`analysis.py`、`run.log` 和 `report.md` 全部写入 `/app/final/`；`run.log` 须为公开输出契约规定的 JSON 对象。
- `report.md` 的格式及字段见 `environment/assets/public/output-contract.md`。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/raw_data/unpacked/` | 上文指定材料和方法的输运数据 |
| `/app/environment/assets/public/output-contract.md` | 公开提交规范 |

工作目录为 `/app`，输入位于 `environment/assets/raw_data/unpacked/` 下的 `mobility/` 材料目录，使用 GaAs、GaN、Si、SnSe 各自的 `AMSET_transport.json`。结果写入 `/app/final/`。

**交付物**

| 路径 | 内容 |
| --- | --- |
| `/app/final/results.json` | 量化结果 |
| `/app/final/analysis.py` | 可复现分析代码 |
| `/app/final/run.log` | JSON 运行记录 |
| `/app/final/report.md` | 科学报告 |
