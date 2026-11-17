# 有限封存cohort的静电吸附热贡献与气体对照

## 背景

独立插入统计矩描述 298 K 有限 cohort 的静电吸附热效应。

公开输入提供队列、来源矩、模型背景及热力学约定。

## 任务

重建全部纳入组的 DDEC3−NO_Q 效应及配对结构的 H2S 效应−CO2 效应。

## 要求

- 保留已取得 11 组和固定 10 组 cohort（CO2 六组、H2S 四组）；按来源排除 GAZLAW_clean/CO2，不能按效应正负筛选。只有四个配对结构参与气体差。由 primary/audit 矩重建 Qst=RT-cE、组内/组间方差、舍入及确定性能量界，完整公式见 所列输出约定。源数据条件仍为总半宽 <=0.5 kJ/mol、数值部分 <=0.05。使用 Fieller/Cauchy–Schwarz 分母修正；组差用两个 97.5% 包络（t 分位 0.9875），气体差用四个 98.75% 包络（t 分位 0.99375）。两遍区间均支持才判断符号，否则 unidentified。自主选择 CO2、H2S 或 paired_gas_difference 主问题，不遗漏结果。六位小数序列化（界 5.1e-7），无界端点留空。Student/渐近名义覆盖仅逐比较，不作总体或实验认证。
- 仅使用本题公开输入，保留全部必要状态、失败、单位及可复现证据。

- 在本地容器内依据提供的充分统计量完成有限队列分析，不生成新轨迹、不调用远程科学引擎、不推断所给观测中缺失的结构或气体效应。全部产物写入 `/app/outputs/`，提交代码须支持公开产物契约规定的固定重放命令。

- 将 analysis.py 及依赖提交至 outputs/code/，并支持在空目录重新生成科学结果。

- `decision.json` 的 `denominator` 必须是 JSON 整数（不能是布尔值或公式字符串），表示所选 focus 的行数：CO2 为 6，H2S 为 4，paired_gas_difference 为 4。`supporting_ids` 必须包含该 focus 的全部组或配对结构。
- 受控重放时，`/submission` 和 `/inputs` 为只读；`/out`、`/tmp` 与私有 `/dev/shm` 可写。公开运行时及 `/dev/null`、`/dev/urandom` 可用；不提供 `/proc`、私有数据或宿主专有路径。请使用命令行给出的路径，不要依赖宿主文件系统布局。
- 按所列输出约定提交规定产物。

## 文件

| 路径 | 说明 |
| --- | --- |
| `/opt/qeq-public/` | 公开数据、模型与计算参数。 |
| `/opt/qeq-public/output-contract.yaml` | 输出内容与提交格式。 |
| `/app/outputs/` | 提交结果与必要运行证据。 |
