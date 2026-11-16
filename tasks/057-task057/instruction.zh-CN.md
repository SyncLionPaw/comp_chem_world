# 常数与温度缩放弛豫时间的适用性评估

## 背景

常数弛豫时间（CRT）和温度缩放弛豫时间（SRT）可能对迁移率误差和温度斜率给出不同结果。两类指标的比较会呈现怎样的关系？

## 任务

使用 GaAs、GaN 和 SnSe 的 AMSET、CRT、SRT 迁移率数组，对匹配条件下的模型误差和温度斜率进行比较，并判断 SRT 在哪些实际指标上改善或恶化。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 比较固定 `10 fs` 的 CRT 与 `10 fs × (300 K/T)` 的 SRT；仅按各数据文件实际存在的浓度、温度和 `xx/yy/zz` 方向匹配，不插造缺失温度点。
- 对所有匹配条件提交 `results.json`，并按材料、浓度和方向覆盖每项指标：`log_rmse=sqrt(mean(log10(mu_model/mu_amset)^2))`；斜率为 `(ln(mu_maxT)-ln(mu_minT))/(ln(maxT)-ln(minT))`。
- 结合实际误差和斜率评估 SRT 的表现；AMSET 是本题数组中的参照，不是实验真值。不要把完整来源数据的误差或相关性统计移植到本题。
- 提交可复算的 `analysis.py`、运行记录 `run.log` 和科学摘要 `report.md`。脚本须使用 `python analysis.py --inputs environment/assets --output final` 读取公开数组并生成结果；记录格式见公开输出契约。
- 将四个必需文件 `results.json`、`analysis.py`、`run.log` 和 `report.md` 全部写入 `/app/final/`；`run.log` 须为公开输出契约规定的 JSON 对象。
- 报告字段、覆盖要求及格式见 `environment/assets/public/output-contract.md`。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/raw_data/unpacked/` | 上文指定材料和方法的输运数据 |
| `/app/environment/assets/public/output-contract.md` | 公开提交规范 |

工作目录为 `/app`，输入位于 `environment/assets/raw_data/unpacked/` 下的 `mobility/` 材料目录，使用 GaAs、GaN、SnSe 各自的 `AMSET_transport.json`、`CRT_transport.json` 和 `SRT_transport.json`。结果写入 `/app/final/`。

**交付物**

| 路径 | 内容 |
| --- | --- |
| `/app/final/results.json` | 量化结果 |
| `/app/final/analysis.py` | 可复现分析代码 |
| `/app/final/run.log` | JSON 运行记录 |
| `/app/final/report.md` | 科学报告 |
