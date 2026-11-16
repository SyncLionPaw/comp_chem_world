## 背景

**任务：Wolfe–Quapp 静态变分偏置优化**

提供的输入定义自然单位制下经旋转的二维四阶 Wolfe–Quapp 势能（T=1、摩擦系数=10），定义域为 x,y∈[-3,3]。本任务只做静态优化；不要运行分子动力学。


## 任务

在 beta=1、well-tempered gamma=10 和 [-3,3]^2 上，计算目标密度 p_target(x,y)∝exp[-U(x,y)/gamma] 的偏置，使 Omega[V]=E_target[V]+log ∫exp[-(U+V)]dxdy 最小。相差加法常数的偏置等价。选择解析证书或数值优化路线。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 将 bias-grid.csv、bias_model.py、optimization-trace.csv、report.md、method-evidence.json 和 solve.py 写在 /app/。网格列为 x,y,bias_kBT，须覆盖闭区间均匀 61×61 网格且每点恰一行。bias_model.py 提供 evaluate(x,y)->scalar_kBT 和 gradient(x,y)->(dV/dx,dV/dy)；数值路线还提供基于所声明单项式基的 evaluate_theta(x,y,theta) 与 parameter_gradient(x,y,theta)。
- method-evidence.json 须包含科研必需成员 route、physics、representation、integration、stop，以及路线对应的 certificate（解析）或 solver（数值）。可附加描述性顶层元数据，但不得替代或改变这些科研必需成员。physics={beta:1,gamma:10,domain:[[-3,3],[-3,3]]}；representation={basis:monomial,parameter_order:1–64 个唯一整数指数对且每个指数在[0,8]内,scales:[3,3]}，基函数 phi_ij=(x/3)^i(y/3)^j；integration={rule:tensor_trapezoid,resolution:61–181,更大的refinement_resolution且≤241}；stop 的 criterion 为 gradient_norm 或 relative_objective_change，tolerance 为正有限数且≤1e-5，reason 为非空科研解释。
- 解析路线：certificate.coefficients 使用字符串键 "i,j"，覆盖未缩放多项式 V=Σc_ij x^i y^j 的全部25个 i,j∈{0,…,4} 系数；gauge_constant=c_00。证明 Omega 的驻点条件和全局最小性，不提供数值求解器。
- 数值路线：solver 声明 entrypoint=solve.py、uint32 seed、initial_theta、含 method/options（可选 polish 的 method/options）的 config，以及 challenge.scale∈[0.02,0.2]。每个 maxiter 是[1,1500]内整数。solve.py 提供 optimize(objective_gradient,initial_theta,config)->states；objective_gradient 返回(objective,gradient)。返回2–2000个数值状态，从 initial_theta 开始；iteration 与 bias_version 从0连续递增，parameter_step_norm 是相邻状态的欧氏步长（首项为0）。须分别从 initial_theta 和按 challenge scale 扰动的邻近初值进行独立回放，两次终态 gradient_norm 均≤max(1e-5,10*tolerance)。trace 还须符合停止条件：gradient_norm≤tolerance；或abs(ΔOmega)/max(1,abs(Omega_previous),abs(Omega_current))≤1.01*tolerance 且终态 gradient_norm≤max(1e-5,10*tolerance)。仅耗尽 maxiter 不算收敛。SciPy L-BFGS-B/BFGS 的 gtol 为正且≤梯度容差；相对目标停止时 ftol=tolerance。
- trace 列为 iteration,objective,gradient_norm,parameter_step_norm,bias_version,theta_json。解析路线只有一条驻点记录，iteration、bias_version、gradient_norm、parameter_step_norm 均为0，theta_json=analytic_stationarity；objective 用同一泛函计算。其 solve.py 是非空 UTF-8 说明且不执行。数值路线记录真实状态。report.md 为非空 UTF-8 科学摘要，说明方法、目标、表示、积分及局限，无固定模板。
- 数值精度要求：bias RMSE≤0.05 kBT、目标分布总变差距离≤0.02、网格外最大偏置误差≤0.05 kBT、积分加密前后 objective 差≤2e-4。分布检验不受偏置加法常数影响。

输入系数已处于任务坐标系，无需旋转。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/md_potential` | 势能系数 |
| `/app/environment/assets/md_input` | 模拟设置和单位 |

**交付物**

| 路径 | 内容 |
| --- | --- |
| `/app/bias-grid.csv` | 偏置网格 |
| `/app/optimization-trace.csv` | 优化轨迹 |
| `/app/bias_model.py` | 偏置模型 |
| `/app/report.md` | 科学摘要 |
| `/app/method-evidence.json` | 方法证据 |
| `/app/solve.py` | 求解程序或解析路线说明 |
