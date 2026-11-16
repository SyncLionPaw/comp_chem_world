# 任务：六种合金的内禀解理—发射竞争

## 背景

公开弹性、断裂能和不稳定层错能锚点支持内禀解理—发射竞争研究。在体相分数 0.0058、任务温度 300 K 下，表面与层错覆盖度是独立变量，不构成裂尖或宏观氢脆图。

## 任务

为六种合金构造连续二维竞争图，量化精确边界、分类面积及其对读图不确定度和成核面积的稳健性。

## 要求

- 两个独立覆盖轴仅在 0/0.5/1 锚点间线性插值，对 30/50/70 Å² 成核面积计算完整 101×101 网格，不缩并为相等覆盖度或外推。
- 一致处理 J/m² 与 mJ/m²，计算解理/发射临界强度及竞争函数上下界和中心；传播断裂能 ±0.05 J/m² 区间，将 108 Å² 的物理 USF 离散度缩放到成核面积。
- 求每个锚点矩形内的全部边界交点，省略不存在的线段；精确计算解理稳健、发射稳健及未决区域面积，使其分割单位正方形。
- 用九个锚点组合的极值及位置支持无边界和全域稳健结论；允许建立相同完整边界与面积证据的等价数学方法。
- 保留物理假设和来源。不重复加入熵或随机 50% 修正，不补造 Ni 参数，不引入裂尖偏聚或外载荷。
- 所有能量先转为 J/m²，定义 `D_center=alpha*gamma_F_mean−beta*mu_usf`、`D_low=alpha*gamma_F_low−beta*mu_usf`、`D_high=alpha*gamma_F_high−beta*(mu_usf−sigma_A)`，其中 `sigma_A=sigma_108*sqrt(108/A)`；`KIc=sqrt(alpha_GPa*gamma_F_Jm2/1000)`，发射强度使用对应 beta/USF 公式。

### 输入与产物细则

使用 `/app/assets/` 中的弹性、断裂能和不稳定层错能表及来源记录。自行创建 `/app/final/`，提交四项结果。

- `phase_map.csv`（183618 行）：标识列为 `alloy,A_nucleation_A2,C_surface,C_usf`，另含固定条件 `Cb_fixed,temperature_K`、三项 `gamma_F_{mean,low,high}_J_m2`、`gamma_usf_sigma_scaled_mJ_m2`、`D_{low,center,high}_GPa_J_m2`、`KIc_{low,mean,high}_MPa_sqrt_m`、`KIe_{low,mean}_MPa_sqrt_m` 和 `classification`（`cleavage_first_robust,emission_first_robust,competition_uncertain`）。花括号中的各项表示分别展开的列。
- `analytic_boundaries.json`：对象数组，每项含 `alloy,A_nucleation_A2,boundary,C_surface_cell,C_usf_cell,endpoints_C_surface_C_usf`；边界族为 `D_low,D_center,D_high`，坐标采用数值对。
- `region_areas.csv`（18 行）：`alloy,A_nucleation_A2,cleavage_first_robust,emission_first_robust,competition_uncertain,area_sum`。
- `extrema_certificates.json`（18 项）：`alloy,A_nucleation_A2,vertices_checked,min_D_low,max_D_low,min_D_high,max_D_high,whole_domain_certificate`。各极值记录 `C_surface,C_usf,D_low_GPa_J_m2,D_high_GPa_J_m2`；依据计算极值选择 `cleavage_first_robust_entire_domain`、`emission_first_robust_entire_domain` 或 `local_competition_or_uncertainty_present`。

CSV 使用 UTF-8 表头，坐标对用 JSON 数值数组。单位由科学量列名明确；重复的来源标签和单位字符串列不作强制要求。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 给定输入与资源目录。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final/analytic_boundaries.json` | 对象数组，每项含 `alloy,A_nucleation_A2,boundary,C_surface_cell,C_usf_cell,endpoints_C_surface_C_usf` |
