# 萘自由基阳离子的 RESP 电荷拟合

## 背景
RESP 将原子电荷拟合至静电势。本题使用给定萘自由基阳离子几何与 ESP 网格；无需重新计算电子结构。

## 任务
拟合并验证 RESP 电荷。

## 要求

- 环境：使用容器 `PATH` 上的 Python；所需科学计算包已预装。不要自行安装额外软件包，也不要通过网络获取依赖。

采用 +1 电荷、双重态。确认 ESP 坐标与 XYZ 顺序一致（10 个 C 后接 8 个 H）。ESP 坐标为 bohr，电势为 hartree/e。令 Aki=1/rki，最小化 J(q)=Σk[(Aq)k−Vk]²+0.0005Σi=0..9(√(qi²+0.1²)−0.1)，约束 Σqi=1，且仅约束碳原子。记录优化器/收敛、电子态、单位和映射；保持顺序、电荷误差≤1e-6 e，重算目标函数/RMSE。读取给定 XYZ/ESP，在 /app/final/ 写 charges.json、fit-input.json、实际 fit.log、可运行 fit.py 和 analysis.md。字段/单位/容差见公开 /app/output-contract.yaml。CLI 须能在干净目录仅用输入、代码和已安装库重现拟合。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/` | 几何与静电势数据。 |
| `/app/output-contract.yaml` | 输出格式与证据要求。 |

| 文件路径 | 说明 |
| --- | --- |
| `/app/final/charges.json` | 拟合电荷 |
| `/app/final/fit-input.json` | 拟合输入及设置 |
| `/app/final/fit.log` | 原生拟合日志 |
| `/app/final/fit.py` | 可运行的拟合代码 |
| `/app/final/analysis.md` | 分析报告 |
