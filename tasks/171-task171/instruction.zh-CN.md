# 任务：—诊断电声计算活动

## 背景

`assets/epc-campaign.tar.gz` 包含四条重建的 QE/EPW 风格运行链、设置、SCF 记录、谱和汇总、声子频率与线宽。
这些是合成训练重建，不是原始输出。
内嵌病理标签仅适用于该训练数据；
真实计算中类似症状可能有其他原因。

## 任务

解包并检查所有链。
根据输出与设置找出唯一可信运行链，为其他链列出适用的内嵌病理，并为每个判断引用具体证据。
独立积分所选 a2F 数据，提取 λ、ω_log、μ*=0.16 时 Tc，并找到最大线宽及对应模频率。
说明 Γ 点三个声学频率和各链 SCF 收敛记录反映的问题。

## 要求

病理标签仅允许：`unconverged_scf`、`insufficient_vacuum`、`insufficient_k_mesh`、`insufficient_q_mesh`、`excessive_smearing`。
根据此训练数据报告准确标签；
可信链的标签数组为空，其他每条链至少一个。
每条证据须引用具体设置或输出观察。
与给定资料协议比较：80 Ry、16×16×1 SCF、192×192 k / 96×96 q、`sk=0.05 eV`、`sq=0.5 meV`、40 Å 真空、μ*=0.16。
结果从所选链提取；
独立 λ 积分与该链汇总值误差≤5%。
线宽第 3 列单位 cm⁻¹，第 4 列单位 meV。

### 输入与产物细则

写入 `/app/final/diagnosis.json`。
`runs` 对象必须且仅含 `run-A`、`run-B`、`run-C`、`run-D`，每项为含布尔 `trustworthy`、字符串数组 `pathologies`、字符串 `evidence` 的对象。
`selected_chain` 为唯一可信链 ID 字符串。
`extracted` 对象含有限数值 `lambda`、`omega_log_cm1`、`tc_mu016_K`、`lambda_from_a2f_dat`、`gamma_max_meV`、`gamma_max_mode_omega_cm1`。
不得照抄结果模板或根据文件名推断可信度。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `assets/epc-campaign.tar.gz` | 给定科学输入或资源；格式和单位见任务要求。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final/diagnosis.json` | 提交结果；内容与格式按上文要求。 |
