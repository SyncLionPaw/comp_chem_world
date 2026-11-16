# 任务：冻结 DeepVES 记录的证据关联诊断

## 背景

分析两条按时间排序且匿名化的轨迹（`run-A.csv`、`run-B.csv`）、对应元数据及 `NeuralNetworkVes.cpp`。A 使用非周期坐标和自然能量单位（`kBT`，T=1）；B 使用弧度表示的周期角、kJ/mol 和 T=300 K。保持轨迹名称匿名。独立的 `ala2_ref/COLVAR` 记录不在范围内。

每个系统只有一条有限轨迹，且实际每次运行的 PLUMED ARG 设置及完整物理输入不可用。结果只支持描述性关联，不能识别 CV 完整性、因果关系或跨系统速率排序。

## 任务

在 `/app/` 创建 `statistics.json`、`analysis-contract.json`、`diagnosis.md` 和 `intervention.md`。使用所给资产计算统计量，`statistics_builder.py` 提供完整布局。请将所有科学结论及其支持证据记录在 `analysis-contract.json` 中；该结构化分析是研究发现的权威记录。诊断和干预方案是阅读说明，措辞与排版可灵活安排。请提交两个非空 UTF-8 文本文件；可使用可选的 `render_contract.py` 生成。不得运行模拟或声称有新的 MD 证据。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

读取 CSV 列 `time,cv1,cv2,bias,force2,kl,lrscale`；数值须有限、时间间隔均匀。保留行顺序、哈希、单位、帧数、缺失值数量、时间范围和 builder 全部输出。引用从零开始的数据行（CSV 行号 = 数据索引 + 2）。首个 `lrscale < 5e-5` 行是记录边界；静态分析从下一次 calculation 开始，固定 bias 分析仅使用之后的样本。报告相邻且时长相等的 freeze 前/后窗口及较晚的 post 窗口，端点均包含。

使用 20 帧连续 dwell 检测事件。A 核心区是 `cv1 <= -0.5`/`cv1 >= +0.5`；B 核心区是 `sin(cv1) < -0.5`/`sin(cv1) > +0.5`，跨越分支切口不算事件。先在完整窗口检测，再分配至等时长左开右闭 `(left,right]` block。使用 5、10、20 个时间 block 和双侧 Student-t 临界值（`df=blocks-1`）报告区间。这些区间描述单条轨迹内部变化；事件速率是操作性代理量，不是经验证的转变速率或独立 seed 不确定性。

A 使用原生单位 `beta=1`；B 使用 `beta=1/(RT)`，`R=0.00831446261815324 kJ mol^-1 K^-1`。仅对严格晚于边界的样本以稳定权重 `exp(beta*bias-max(beta*bias))` 全局重加权，另报 Kish ESS。半球概率 `p=sum(wI)/sum(w)` 使用 delete-block `p_b=(sum(wI)-block_sum(wI))/(sum(w)-block_sum(w))` 和 `SE=sqrt((B-1)/B * sum((p_b-mean(p_b))^2))`，并单独标示等 block 异质性。

使用 FFT 自协方差，滞后分母 `n-k`，初始正值配对 `rho[1]+rho[2]`、`rho[3]+rho[4]`、……，最大滞后 `min(4000,floor(n/4))`；在首个非正配对处停止，报告 `g=max(1,1+2*sum(rho[k]))`。分别计算权重、CV 状态、半球、加权状态残差和周期正弦/余弦分量。常数序列取 `g=1` 并标记；达到滞后上限为截断。常数权重可取 `g=1`；常数状态/残差及截断结果不能证明 observable ESS 可分辨。周期坐标报告圆周正弦/余弦均值、resultant、`SD=sqrt(-2 log(R))`（resultant 接近零时为 null），不得报告线性角度均值。每条轨迹另做一项敏感性分析：threshold 0.3–0.8、整数 dwell 10–100 帧、window scale 0.75–1.0，至少一项不同于 `0.5/20/1.0`；报告 pre-freeze/post-freeze/late-post 的 start/end/count/rate。

比较 freeze、正交坐标、有限采样/相关性和系统特异解释，并关联计算证据；机制无法区分时使用 `not_identified`，不得声称因果已识别。至少设计两项匹配干预，每项仅改变 CV 定义或预注册 freeze trigger。匹配物理控制和配对初态，在 seed 内考虑序列相关，并预注册同运行 crossing-proxy-rate 结果、正的 expected effect、minimum effect（为零或至少为 expected effect 的 10% 且小于它）及 early/late 配对 95% 区间。只有当两个 signed 区间下限均高于 expected effect 时判为支持；只有当两个上限均低于 minimum effect 时判为反驳；否则为 inconclusive。结果反转、区间重叠、序列支持不足或 seed 过少均为 inconclusive；控制、单位或 exposure 不匹配则设计无效。合成挑战仅测试该规则，不是机制或模拟证据。

### 输入与产物细则

输入位于 `environment/assets/`：`run-A.csv`、`run-B.csv`、`metadata.json`、`NeuralNetworkVes.cpp`、`statistics_builder.py`、`render_contract.py`。必需输出为 `/app/` 下四个文件。合同使用下列字段；未知键无效，可省略可选描述元数据。

| 对象 | 必需字段 |
|---|---|
| 根对象 | `source_behavior,claims,hypotheses,interventions,alternative_sensitivities` |
| `source_behavior` | `source_sha256,comparison,threshold,condition_line,optimizer_guard_line,optimizer_step_line,static_branch_line,grid_read_line,lr_decay_line` |
| Claim | `id,kind,scope,evidence,assertion,inference`；scope=`run_id,window,observable,unit`；evidence=`input_sha256,run_id,window,metric_ref,operator,value,row_start,row_end,time_start,time_end`；assertion=`left,operator,right` |
| Hypothesis | `id,mechanism,status,evidence_claim_ids,competes_with,measurement_ref,prediction`；prediction=`intervention_id,change_factor,observable_ref,direction,discriminating_outcome` |
| Intervention | `id,run_id,controls,arms,cv_plan,freeze_criterion,paired_seed_ids,freeze_rule,window_rule,primary_metric_ref,estimand,uncertainty,prediction` |
| Sensitivity | `id,run_id,event_core_threshold,dwell_frames,window_scale,windows`；`windows.{pre_freeze,post_freeze,late_post}` 各包含 `start,end,count,rate` |

至少 3 条 claim、2 项 intervention，每个 run 恰有一项 sensitivity。各列表 ID 唯一且符合 `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`。Claim kind=`observation`；inference=`observed/compatible/not_identified/refuted`。scope run=`run-A.csv/run-B.csv/source`；window=`pre_freeze/post_freeze/late_post/strict_static/source/pre_post`（`pre_post` 仅用于 claim scope，须引用两个组成窗口）。`scope.observable` 指明 assertion 主指标；每条 claim 对该主要指标至少有一项 evidence。相关因子使用 `correlation_g.<observable>`。`right` 是有限数值或 `{metric_ref:...}`；运算符=`eq/lt/le/gt/ge`。证据须匹配重算指标、哈希、单位和精确行/时间范围；strict-static 轨迹行从 marker+1 开始。容差：evidence `rtol=1e-6/atol=1e-10`；假设测量/敏感性 `rtol=2e-6/atol=1e-10`。

`source_behavior` 使用 `<` 和阈值 `5e-5`。locator 为正的 1 起始行号，或经空白规范化并去掉末尾 `//` 注释后匹配的源码行文本。它们依次定位设置 `static_bias` 的阈值条件、动态 `if (!static_bias)` 守卫、优化器步骤、唯一 `//if static bias:` 标记后的 `} else {`、静态分支使用当前 CV 和已初始化网格计算 bias/derivatives 的语句（不是创建/加载网格文件），以及学习率缩放更新。源码证据引用 SHA 和整份源码，`row_start,row_end,time_start,time_end` 均为 null；须提供全部六个 locator。规范 claim 指标为 `source_behavior.threshold`、`runs.<run>.windows.{pre_freeze,post_freeze}.crossing_proxy_rate_per_time`、`runs.<run>.windows.pre_freeze.cv2_sd`、`runs.<run>.reweight.correlation_g.<observable>`；数值 observable 为 `weights,cv1,cv2,hemisphere_state,weighted_cv1_residual`（B 另有 `sin_cv1,cos_cv1`）。单位分别为 `optimizer-scale`、`1/<time unit>`、A=`native-CV-unit`/B=`radians`、`dimensionless`。

这些指标的 `scope.observable` 通常使用现有 observable 名称（`threshold`、`crossing_proxy_rate_per_time`、`cv2_sd` 或 `correlation_g.<observable>`）；也可以重复 `assertion.left` 中完全相同的规范指标引用。此时该引用必须与声明的 `scope.run_id` 和 `scope.window` 匹配（包括 `source/source`，或对应轨迹及 strict-static 重加权窗口），并按该指标现有的短 observable 名解释。不得截取任意指标引用的后缀来转换。

`assertion.left`、每个 `evidence.metric_ref` 及 `right.metric_ref`（如有）都必须使用完整规范指标路径，例如 `runs.<run_id>.windows.<window>.<metric>` 或 `source_behavior.threshold`，不得使用短别名。`assertion.left` 明确指定主指标；`scope.window=pre_post` 时，须明确选择 freeze 前或后的路径。不得根据 `right` 或 evidence 列表推断所选指标。

假设覆盖 `freeze_removes_adaptation,orthogonal_slow_coordinate,finite_sampling_correlation,system_specific_dynamics`，并以相同规范标识符作为 `id` 和 `mechanism`。status=`compatible/not_identified`；`measurement_ref` 是非空 metric-ref 到有限数值映射。Prediction factor=`add_orthogonal_cv/delay_freeze`，direction=`increase/decrease/either`（须匹配所连 intervention 登记方向或为 `either`），outcome=`supports/weakens/remains_unresolved`。引用有效 claim ID 和竞争假设 ID；prediction 连接到处理因子相同且 primary metric 同运行的 intervention。Freeze 关联源码阈值和同运行前后速率；orthogonal 坐标含 `cv2_sd` 且为 `not_identified`；finite-sampling 引用相关性受限/截断支持；system-specific 使用两条 run 且为 `not_identified`。

Intervention 的 `controls` 恰含 `temperature,energy_unit,forcefield,initial_state_protocol,integrator_dt,target_distribution,exposure,output_interval`；温度和能量单位匹配 metadata。其他六项均填 `matched`，依次表示：同一 archived forcefield fingerprint 且运行前确定精确值；配对相同初始坐标/速度/checkpoint；同一 archived timestep 且运行前确定精确值；同一物理 target/thermostat；每个配对 seed 模拟时长相同；输出间隔相同。`arms` 按 baseline/treatment 排序，各含 `id,changed_variable,value`；baseline=`{id:baseline,changed_variable:baseline,value:recover_source_configuration}`；treatment 的 `id=treatment`，且只改 `cv_definition` 或 `freeze_rule`。Treatment 值为 A CV `add_predeclared_orthogonal_cv2`、B CV `add_predeclared_complementary_periodic_cv2` 或 freeze `later_pre_registered_objective_gradient_trigger`。`cv_plan` 恰含 `baseline_status,coordinate_mapping,periodic_embedding,treatment_token`，使用 `unidentified,cv2,none`（A）/`sin_cos`（B），且 `treatment_token` 等于 treatment value。

`freeze_criterion` 恰含 `metric,operator,threshold,persistence_evaluations,baseline_time_fraction,treatment_time_fraction`；使用 `metric=relative_objective_gradient_norm,operator=le`、(0,1) 内阈值、至少 3 的整数 persistence、(0,1) 内时间比例。CV-only 用相等比例和 `same_pre_registered_objective_gradient_rule`；freeze-only 用较晚 treatment 比例和 `pre_registered_later_objective_gradient_rule`。至少三个唯一非空配对 seed ID。`estimand={formula,unit,minimum_effect}`，formula=`paired_mean_delta`；`uncertainty={method,alpha,serial_block_rule,minimum_independent_seeds}`，使用 `paired_t_interval,0.05,block_within_seed_before_paired_seed_summary`，seed 数 3–30。`window_rule=equal_exposure_predefined_windows_with_late_sensitivity`；primary metric 为同运行 crossing-proxy rate；`prediction={direction,expected_effect,unit}`，direction=`increase/decrease`，expected effect 为正，单位匹配速率。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 匿名化轨迹、元数据、源码及分析工具。 |

| 路径 | 内容 |
| --- | --- |
| `/app/statistics.json` | 重算统计量与时间窗诊断 |
| `/app/analysis-contract.json` | 科学主张及其证据 |
| `/app/diagnosis.md` | 对两次运行及证据边界的诊断 |
| `/app/intervention.md` | 拟议的配对干预实验 |
