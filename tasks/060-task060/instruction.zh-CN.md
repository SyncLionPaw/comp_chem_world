# 诊断 Si 输运收敛性

## 背景

散射率预测受插值网格、费米–狄拉克截断能窗（`fd_tol`）、散射机制和载流子浓度影响。本题在固定计算预算内测量这些因素对硅输运的影响。

## 任务

使用提供的 Si 原生输入，在 300 K 下计算六个浓度的 ADP、IMP 和总输运。比较拟合/网格与能窗设置，提出并验证可证伪的 follow-up 预测。使用 `/app/environment/case06_rpc.py`；完整流程和输出契约见 `/app/environment/assets/public/output-contract.md`。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 AMSET、ASE、BoltzTraP2、h5py、matplotlib、netcdf4、NetworkX、NumPy、pandas、Phonopy、pillow、pymatgen、PyYAML、SciPy、seekpath、spglib、sympy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 完成三个逐步增大的基线插值因子，再运行与第三项相比只改变 `fd_tol` 的设置。第一项与第三项因子至少相差 2 倍，并从实际能窗 cutoffs 核实区间扩展。
- 对 `overall`、ADP、IMP × 六个浓度 × `xx/yy/zz` 共 54 个身份，按 `abs(old-new)/abs(new)` 和严格 2% 阈值比较。零或非有限分母属于待定数值比较；非正或非有限 native mobility 证据无效。两个轴分别采用各自最新有效相邻比较。拟合与网格同时变化不能证明纯积分网格误差；整体输运不能掩盖机制变化。
- 对可信 `global_maximum_108` 分量封存可证伪预测，无论其是否超过 2%。保留返回的轴和分量身份；并列项按返回的 `tie_rule` 与 `tie_count` 处理。拟合/网格 follow-up 的因子至少提高 1.5 倍且实际网格每维增大；能窗 follow-up 保持因子和网格不变并减小 `fd_tol`。
- 通过 `private-control` 操作，在独立对照配置揭示前登记判读规则。若存在 `window-match-3`，则与其比较；否则与 `followup-5` 比较；输运和能窗 cutoffs 使用同一父项。
- 保留每次尝试的原生 HDF、实际设置、日志、运行身份和独立输运重建。摘要本身不能证明执行。结论只适用于实际测试设置和预算，不代表渐近收敛或绝对准确度。

整个任务会话最多 1800 秒。每次 native 运行最多 180 秒、可信重建最多 300 秒、每棵受监督进程树峰值 RSS 最多 12 GiB。封存的 follow-up 预算只能收紧原生 `followup-5` 上限。如有未完成工作，须如实报告。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/inputs/` | 硅输运的原生计算输入。 |

输入目录：

```text
/app/environment/assets/inputs/
```

RPC 接口与公开输出契约：

```text
/app/environment/case06_rpc.py
/app/environment/assets/public/output-contract.md
```

只提交以下三项科学报告：

```text
/app/final/
├── report.json
├── private-control-response.json
└── report.md
```

环境会自动保全执行证据，无须手动复制。调用终端 `finalize` 前，确认 report 和 response 对象与最终提交文件一致。
