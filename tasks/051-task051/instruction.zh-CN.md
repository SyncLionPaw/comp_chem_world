# 任务：历史 Ala2 NN-VES 检查点重建

## 背景

重建归档的静态 NN-VES 检查点，并评估有限历史记录上的数学输出。检查点在记录终点被强制冻结；这不代表其内在收敛。不得声称有新采样、重新训练、FES 精度或方法的普遍优势。

## 任务

在 `/app/submission.py` 实现 `forward_and_grad(angles, checkpoint)`、`frame_force(coords_nm, box_nm, checkpoint)` 和 `analyze(train, ves, control, contract)`。每次根据参数计算结果，包括被修改的检查点、帧和分析参数；不得返回记忆中的历史结果代替计算。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 网络输入为弧度制 `[sin(phi),sin(psi),cos(phi),cos(psi)]`；结构为 4→48→24→12→1，前三层后接 ReLU，输出 kJ/mol 标量偏置。checkpoint 仅含 `layers`，即按序排列的四个 `{weight,bias}` 项。源张量为 little-endian float32，依次为 `fc1.weight`、`fc1.bias`、`fc2.weight`、`fc2.bias`、`fc3.weight`、`fc3.bias`、`out.weight`、`out.bias`，形状依次为 `(48,4),(48,),(24,48),(24,),(12,24),(12,),(1,12),(1,)`。ReLU 在零处导数为零。安全解析 Torch ZIP 张量载荷，不执行任意 pickle 代码。
- 每帧22个原子；坐标和正交盒长单位为 nm，力为 kJ mol⁻¹ nm⁻¹。用1-based原子 `[5,7,9,15]` 定义 phi、`[7,9,15,17]` 定义 psi；对每条连续扭转键用 minimum-image 位移。归档 step-zero 以原始 TRR float32 坐标为准；CSV 坐标 sidecar 提供用于核对的舍入十进制区间。
- 三个 API 的顶层返回值均为 Python 字典（JSON 对象），不得为元组或列表。`forward_and_grad` 接收两个有限角度及 checkpoint，将角度包裹到 `[-π,π)`，精确返回有限的 `bias_kj_mol`、`dV_dphi_kj_mol_rad`、`dV_dpsi_kj_mol_rad`。`frame_force` 接收有限 22×3 坐标和三个正盒长，精确返回 `phi_rad`、`psi_rad`、`bias_kj_mol`、`force_kj_mol_nm`（22×3），力为偏置能量经两个扭转角传导后的负笛卡尔导数。`analyze` 返回规定的嵌套字典分析树。
- `analyze` 接收 `train`、`ves`、`control` 三组有序行；每行含整数 `step`、有限的 `time_ps`、`phi_rad`、`psi_rad`，可用时含 `bias_kj_mol`。`contract` 提供 `dt_ps`、`stride_steps`、`required_rows_per_arm`、`core_radius_rad`、`minimum_consecutive_samples`、`cores_rad`、`checkpoint_iteration`、`forced_freeze_step`、`forced_freeze_time_ps`、`static_window_start_step` 和 `static_window_end_step`（含端点）、`temperature_K`、`gas_constant_kj_mol_k_K`，以及从归档终端记录读取的 `native_terminal_status/native_science_pass`。必须使用传入值，不硬编码实例参数。历史 cadence 为每步0.002 ps、每样本0.04 ps（20步）；每臂37,501个有序样本，跨750,000步。
- 锁定的周期 core 中心（弧度）：`b1=(-1.3823,1.0053)`、`b2=(-2.5133,2.7646)`、`b3=(-1.508,2.2619)`、`b4=(1.131,-0.754)`。周期坐标距离 `hypot(wrap(Δphi),wrap(Δpsi))` ≤ `core_radius_rad` 时样本位于 core。同一 core 连续达到 `minimum_consecutive_samples` 后计一次 visit；离开或切换 core 会重置连续计数。仅新确认的 core 不同于上一个确认 core 时才计 transition，步数取完成 dwell 的行，并保留输入顺序。
- 只用静态 VES 行重加权：`logw=+beta*V`，`beta=1/(R*T)` 使用传入常数，全局以稳定 log-sum-exp 归一化。训练模型会变化，排除训练行。仅在含端点的静态窗口内计算 raw Kish ESS；这是重要性支持诊断，不是时间校正 ESS 或 FES。终端状态及科学标记须读取 terminal record。
- 分析结果必须精确符合下列结构；`?` 表示可选描述字符串：

```text
{
 freeze:{checkpoint_iteration:int,forced_freeze_step:int,forced_freeze_time_ps:number,convergence_claim:false},
 static_window:{arm:"ves",first_step:int,last_step:int,rows:int,checkpoint_iteration:int},
 arms:{train|ves|control:{rows:int,first_step:int,last_step:int,core_visits:{b1:int,b2:int,b3:int,b4:int},qualified_intercore_transitions:[{from:string,to:string,step:int}]}},
 static_ves_reweighting:{temperature_K:number,gas_constant_kJ_mol_K:number,beta_mol_per_kJ:number,log_weight_convention?:string,log_normalizer:number,normalized_weight_sum:number,core_mass:{b1:number,b2:number,b3:number,b4:number},raw_kish_ess_by_core:{b1:number,b2:number,b3:number,b4:number},raw_kish_ess_global:number,qualification?:string,limitations?:string},
 common_support:{cores_with_positive_weighted_ves_mass_and_control_visits:[string],qualification?:string},
 evidence_limits:{native_terminal_status:string,native_science_pass:boolean,fes_status?:string,time_corrected_ess_status?:string,scope?:string}
}
```

  七个可选字符串仅为描述元数据。复制终端记录中的 status 和布尔 science 标记；后者不代表本任务独立判定科学合格。其余键、值、形状和数值/布尔类型必须精确；数值字段须为有限 JSON 数值，不得是布尔值。
- 对形状错误、非有限值、行 cadence/顺序错误、静态窗口为空或逆序，抛出 `ValueError`。比较只用绝对容差（`rtol=0`）：能量 1e-8 kJ/mol、角导数 2e-7 kJ mol⁻¹ rad⁻¹、笛卡尔力 2e-7 kJ mol⁻¹ nm⁻¹、包裹帧角 1e-10 rad、分析数值字段 2e-8。使用 Python 标准库和 NumPy 2.2.6。

### 输入与产物细则

检查点、TRR 帧、轨迹和公开源码均在 `environment/assets/`。唯一必需提交为 `/app/submission.py`。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `environment/assets/` | 给定输入与资源目录。 |

提交 `/app/submission.py`。调用方式和输出约定见上文。
