# 任务：归档硅快照的静态力学

## 背景

输入包含周期性 216 原子硅快照和两个冻结神经网络偏置，需要求其静态力学量。输入不提供原生执行记录；结论限于所给模型和快照，不能证明新动力学、平衡采样、相变或与不可见记录的一致性。

## 任务

实现 `/app/final/evaluate.py --snapshot PATH --models PATH --output PATH` 并生成 `/app/final/result.json`。按收到的文件计算，快照行重排时保留原子身份，并能响应模型参数变化。不启动 LAMMPS、PLUMED、模拟或调度作业。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

每个模型含八个隐藏单元，采用 `V(q)=b2+Σi w2[i] tanh(w1[i]*(q−input_center)/input_scale+b1[i])`。坐标和晶胞单位为 Å，能量/virial 为 eV，力为 eV/Å。

对每个原子 i 使用最小镜像 `r_ij=x_j−x_i`，排除自身。设 sigma=0.4 Å、lambda=100、a=5.431 Å/4、R0=0.5、rc=max_t|t|+3sigma。模板为 `T1={(a,a,a),(−a,−a,a),(a,−a,−a),(−a,a,−a)}`、`T2={(a,−a,a),(−a,a,a),(a,a,−a),(−a,−a,−a)}`。对 rc 内邻居计算 `k_im=(1/4)Σj,t exp(−|r_ij−t|²/(4sigma²))`、`s_i=log(Σm exp(lambda*k_im))/lambda`（不减 log 2）、`Q=Σi (s_i/R0)^12/[1+(s_i/R0)^12]`。Q 无量纲。计算增益 dV/dQ 和力 `F=−(dV/dQ)∂Q/∂x`。

返回完整、不对称化的仿射 virial `W_ab=−dV/d(epsilon_ab)`：行向量坐标和晶胞均按 `x'=xF^T` 变换，模板固定在实验室坐标系。坐标及应变有限差分步长均为 h=1e-4。Q/能量/增益采用 atol=rtol=1e-11，力、virial 和有限差分诊断采用 atol=2e-9。报告力之和，各分量绝对值须 ≤2e-8 eV/Å。

### 输入与产物细则

输入为 `/app/environment/assets/snapshot.data` 和 `models.json`。程序及结果 JSON 均放在 `/app/final/`。

结果包含 `atoms`（整数原子数）、`cell_A`（3×3）及按输入模型顺序排列的 `models`。每个模型项的计算字段恰为 `model_id`、`Q`、`bias_energy_eV`、`dVdQ_eV_per_Q`、`force_eV_per_A_atom_id_order`（216×3，ID 1–216）、`virial_eV_row_a_column_b`（3×3）、`diagnostics`；可省略可选元数据；额外描述字段仅放在 JSON 根部。

`diagnostics` 包含三分量 `net_force_eV_per_A`、针对原子 ID 1、54、109 与各轴 0、1、2 的 `coordinate_probes`，以及全部九个有序轴对的 `strain_probes`。坐标记录为 `{atom_id,axis,analytic_force_eV_per_A,finite_difference_eV_per_A}`；应变记录为 `{a,b,analytic_W_eV,finite_difference_W_eV}`。索引为整数，计算值为有限数，不能用布尔值代替。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/snapshot.data` | 给定科学输入或资源；格式和单位见任务要求。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final` | 提交结果；内容与格式按上文要求。 |
