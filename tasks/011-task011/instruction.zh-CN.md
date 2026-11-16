# 任务：裂尖氢占据与断裂自由能

## 背景

输入包含公开吸氢参数、弹性常数、数字化断裂能和注册 FCC 裂尖列几何。吸氢公式与图注的宽度解释不同；断裂能锚点温度不明，能量与熵贡献的分离依赖条件参考。

## 任务

预测应力驱动的裂尖氢占据及条件断裂自由能，区分解理和位错发射覆盖度，评估纳米扩散、熵与温度效应。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 求体相化学势闭合及注册 12 列模型的占据率，采用 Hill 各向同性泊松比、拉伸驱动压力、ΔV=2.8 Å³ 和一致单位，计算解理/发射平均及带饱和约束的纳米扩散覆盖度。
- 保留印刷尺度与图注标准差两种解释。覆盖六种合金 5800 appm/300 K，以及 SS304 的 2600 appm/300 K 和 4000 appm/300、400 K；Kapp 从 0 到 1.2 MPa√m、步长 0.1。
- 以 5800 appm、假定 Tref=300 K 的断裂能锚点减去组态熵，构造条件能量参考；在覆盖锚点间线性插值，比较其他条件时保持该能量族不变。一致恢复熵、处理 0 ln 0 端点，并传播 ±0.05 J/m² 图像区间。
- 核查零应力体相闭合、共同参考平移与占据边界，不拟合来源观测以消除差异。在 SS304、Kapp=0.6/0.8、两种宽度下，对比 Voigt/Reuss、ΔV=2.7/2.9 Å³ 和 ±0.1 列间距原点扰动。
- 区分数值细化与来源/模型不确定度。反演能量项依赖断裂能锚点，不是独立表面能证据；不声称绝对化学势或已全面验证的宏观预测。
- 对原点偏移敏感性，可将有符号参数解释为原点位移或相对坐标位移；需说明并在整组敏感性记录中保持同一符号约定。
- 将位点占据与 Fig. 1(b) 读图区间逐点比较，并解释 SS304 温度对照。

- 采用 n(x)=exp(−x²)/sqrt(pi)，定义 eta=mu−Ebar−EZP，体相与局部占据均对同一能量分布积分：Cb=integral n(x)f(sigma*x−eta)dx，c_i=integral n(x)f(sigma*x−p_i*DeltaV−eta)dx，其中 f(y)=1/(1+exp(y/(kB*T)))；零应力下 c_i=Cb。采用 C_cleave=mean(c1…c9)、C_emit=mean(c10…c12)、C_S=min(1,1.5*C_cleave)。

### 输入与产物细则

使用 `/app/assets/` 中的参数、坐标及来源对照表。自行创建 `/app/final/`，提交以下科研结果、可执行 `calculation_source.py` 和 `run_metadata.json`。

- `occupation.csv`（2808 行）与 `fracture_free_energy.csv`（234 行）共用 `condition,alloy,Cb_fraction,T_K,Kapp_MPa_sqrt_m,width_interpretation` 标识和 `eta_eV_mu_minus_Ebar_minus_EZP,C_cleave,C_emit,C_S` 数值。占据表另含 `site_column,c_i`；自由能表另含 `Cb_recomputed,nu_hill,DeltaV_A3,A0_A2,gamma_E_J_m2,gamma_E_low_J_m2,gamma_E_high_J_m2,gamma_S_J_m2,gamma_F_J_m2,gamma_F_low_J_m2,gamma_F_high_J_m2`。宽度标识为 `printed_formula_scale,caption_standard_deviation`，四个条件标签可自定但须一致。
- `thermodynamic_model.json` 记录 `width_interpretations`（两种已定义宽度倍率 1 和 sqrt(2)）、`DeltaV_A3`、`gamma_E_condition`、`conditional_assumptions` 和 `sensitivity_summary`。条件参考用 `{status:"conditional",reference_temperature_status:"assumed",reference_Cb_fraction:0.0058,reference_temperature_K:300,image_half_width_J_m2:0.05}`。用自己的语言说明至少三项条件假设以及密度、压力和弹性闭合模型，不要求固定的公式文本或来源标签措辞。
- 28 项敏感性结果放入 `sensitivity_summary.one_at_a_time_model_sensitivity`，每项含 `width,Kapp,variant,parameters={DeltaV_A3,origin_delta_over_dx},coverages={C_cleave,C_emit,C_S}`。变体标识为 `baseline,nu_Voigt,nu_Reuss,DeltaV_2.7,DeltaV_2.9,origin_-0.1,origin_0.1`。
- `limiting_checks.json` 包含 `maximum_bulk_concentration_residual,maximum_common_reference_shift_eta_residual_eV,site_occupancy_bounds`（最小/最大值对）及按合金记录的 `gamma_S_endpoint_checks={gamma_S_cs0_J_m2,gamma_S_cs1_J_m2}`。`mechanism.md` 解释占据、来源对照、温度响应和适用边界。

表格采用 UTF-8，区间写 JSON 数组。运行记录使用 `schema="compchemworld-calculation-run/v1"`、`calculation_sources=[{name,sha256}]`、`inputs={asset_basename:hash}`、`outputs={relative_output_path:hash}`、`python` 与 `execution_context`，列出全部输入及除运行记录外的全部结果文件。运行记录中的字节摘要可用十六进制或 `sha256:` 前缀形式。

`python` 可为非空版本字符串或 `{version:...}`；`execution_context` 可为非空说明或对象。

一般数值的绝对比较容差为 2e−7。体相残差不得超过 2e−10，参考平移残差不得超过 1e−9。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 给定输入与资源目录。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final` | 提交结果；内容与格式按上文要求。 |
