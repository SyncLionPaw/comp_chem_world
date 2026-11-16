# 任务：从五个响应目标反演双模介电核

## 背景

公开输入 `/app/assets/response_targets.json` 给出由固定双模核生成的五个合成观测量。核的形式固定：

`eps(k) = 1 + 1/(K21 + K22 k^2) + 1/(K11 + K12 k^2 + K13 k^4)`，`chi(k) = 1 - 1/eps(k)`，

其中 `k` 单位 Å⁻¹，`K11`/`K21` 无量纲，`K12`/`K22` 单位 Å²，`K13` 单位 Å⁴，且 `K12` 为负。

## 任务

从目标反演五个系数。选择并论证反演方法、初值与重启策略，并检查是否存在同样满足目标的另一参数分支。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 matplotlib、MDAnalysis、NumPy、pillow、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 遵守 DKM 规则：实轴 `k >= 0` 上，有限值的 `eps(k)` 不得落在 `0 <= eps(k) < 1`。`A(k)=K11+K12 k²+K13 k⁴` 极点附近 `eps` 可能取很大的负值，这本身不构成违规；需在极点之间检查有限值，而不是只看 `eps` 的最小值。
- 每条响应的残差向量顺序为 `[eps_w, k_min, chi_min, k_max, delta_k]`，数值为 `(features - targets) / [1, 0.02, 0.01, 0.02, 0.02]`。在 0 到 8 Å⁻¹ 的 200001 个等距点计算 `chi(k)`；取最小 k 的局部极小值和 `chi` 最大值，并用三点二次曲线细化极值位置，再线性插值得到该位置的 `chi`。在 `k_max ± 3 Å⁻¹` 内找半峰值交点并线性插值，以最左和最右交点计算 `delta_k`。
- 本容器中，输入为 `/app/assets/response_targets.json`，输出写入 `/app/final/`。使用 `python solver.py /app` 拟合。通过 `python solver.py /app --objective-rpc` 提供目标回调响应时，同一源码还须支持确定性重放。
- 目标服务重放模式下，stdout 专用于 JSON Lines 请求，例如 `{"type":"objective_query","seq":0,"K":[K11,K12,K13,K21,K22]}`；从 stdin 读取对应响应，例如 `{"type":"objective_result","seq":0,"residual":[r1,r2,r3,r4,r5]}`。诊断信息写入 stderr。公开文件 `/app/assets/objective_features.py` 定义特征映射和缩放残差。符号组合无效但仍有限的系数返回五个 `10.0` 残差；非有限系数属于无效 JSONL 输入，会被拒绝。最终系数须至少查询一次；重放生成的 `kernel_params.json` 与 `response_curves.csv` 必须和提交文件逐字节一致。
- 重放必须确定：固定随机种子并使用稳定的数值输出格式，使重放生成的参数和曲线文件与提交文件逐字节一致。
- 目标服务重放限制：墙钟时间 175 秒，最多 10000 次目标函数请求，源代码最大 2 MB，每个输出文件最大 5 MB，每条 JSONL 请求最大 64 KiB。

合格系数须使五个观测量分别在 `eps_w`、`k_min`、`chi_min`、`k_max`、`delta_k` 的容差 0.02、0.002 Å⁻¹、0.001、0.005 Å⁻¹、0.01 Å⁻¹ 内匹配目标。DKM 禁带须在非负实轴上满足解析规则，曲线还须与系数在数值上一致。

曲线比较使用相对容差 3e-6 和绝对容差 2e-8，单位沿用各列约定。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/response_targets.json` | 五项公开响应目标。 |
| `/app/assets/` | 配套模拟输入与方法文档。 |

- 输入：
  - `/app/assets/response_targets.json`：五个公开响应目标。
  - `/app/assets/objective_features.py`：公开特征映射和缩放残差辅助函数。
- 输出：
  - `/app/final/kernel_params.json`：数值字段 `K11`、`K12`、`K13`、`K21`、`K22`。
  - `/app/final/response_curves.csv`：表头 `k_Ainv,eps,chi`；从约 0 递增到至少 6 Å⁻¹，至少 200 行有限值，每行都由所提交的系数生成。
  - `/app/final/solver.py`：可运行反演程序；拟合和目标服务重放使用同一源码。
  - `/app/final/solver.log`：JSON 对象；仅在实际观察到时写入数值字段 `objective_requests` 和 `final_residual`，未观察到的字段可省略。`final_residual` 为最终缩放残差向量的范数。
