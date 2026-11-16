# 任务：分析历史激发态几何结果

## 背景

ADMM 和简化响应核可能改变优化后的激发态几何。输入包含 26 条分子/方法路线的原始公开 CP2K 输入、输出和轨迹，并附公开路线清单与输出格式契约。

## 任务

针对甲醛（M2）、硫代甲醛（M3）、甲酰氯（M14）、乙醛（M19）和吡嗪（M29），根据归档原生优化记录及相应参考几何数据重建结构比较。按经验 3.0 pm 区间规则评估 36 个非空激发态键长目标，重算 13 组 PBE0/ADMM 配对键长差，并依据原生证据分类 M14 默认 `aEX=0.2` 结果，另行评估其三条 `aEX=0.25` 补救键长。M14 默认空目标不参加数值比较。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、pandas、pillow。不要自行安装额外软件包，也不要通过网络获取依赖。

依据原生输出/轨迹选择各优化端点并说明闭合核查。将键长与正确分子、方法和参考数据配对；以 pm 计算笛卡尔距离，并对对称等价键取平均。按未舍入坐标应用冻结的 3.0 pm 区间规则，纳入规定的参考值与坐标精度不确定性。区分物理解离与启动、执行、内存或一般收敛故障。不得运行 CP2K，也不得声称新执行、极小点、驻点或正曲率。

公开格式说明 `/app/inputs/case06-v5-agent-historical-results-contract-v1.json` 定义精确产物字段、行身份、参考映射、坐标顺序、容差、分类和报告要求。`/app/inputs/case06-v5-public-native-source-manifest-v1.json` 将 26 条路线映射到固定来源文件；两者均不含结果。说明历史 launcher、stderr、scheduler 和 allocation 信息不可用，并保留冻结清单。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/public-source/` | 归档优化记录。 |
| `/app/inputs/case06-v5-agent-historical-results-contract-v1.json` | 分析与提交约定。 |

使用 `/app/inputs/public-source/` 下的原始归档成员及所给文档。在 `/app/final/` 提交 `provenance.json`、`comparison.csv`、`scientific-summary.json` 和 `report.md`。报告须涵盖 26 条路线、36 项比较、13 组配对差、M14 默认/补救结果和历史证据局限。
