# 多靶点姿态重排序与配对统计

## 背景

分子对接算法常在产出天然构象的同时伴生大量诱导契合假阳性姿态。评估增强采样模拟能否有效改善姿态识别能力，需要在多靶点测试集上进行系统性重排序，并针对对接基准执行严格的非参数统计假设检验。

输入包括 42 个体系、210 个姿态的 OpenBPMD+grand 评分与姿态 RMSD，以及从原始 MAE 记录提取的 IFD 评分和来源姿态编号。

## 任务

评估论文补充材料 Table S1 的全量 42 个蛋白-配体系统（共 210 个候选姿态），并利用官方 ACS SI002 原始 MAE 文件中公开的 IFD 分数与姿态编号恢复逐体系比较。完成以下工作：
1. 严格依据元动力学 `CompScore` 升序排列（分值越低表示姿态越稳定）对各系统的候选姿态进行重排序；
2. 提取每个系统预测的 Top-1 姿态，并在 2.0 Å 与 3.0 Å RMSD 阈值下计算全数据集的成功率；
3. 从每体系原始 `r_psp_IFDScore` 最小值确定 IFD Top-1，按精确 pose ID 将两种方法的 RMSD 与 Table S1 对接；对逐体系连续 RMSD 对执行双尾配对 Wilcoxon 符号秩检验，参数为 `zero_method=wilcox`、`correction=False`、`method=auto`。报告名义 p 值及预先声明的 alpha=0.05 决策；统计量和结果须由数据计算，不得强行要求显著或凑论文舍入值；
4. 诊断并识别在标准 0.3 kcal/mol 峰高下的激酶异常系统。

## 要求

- 对42体系210姿态按CompScore升序排序，不以RMSD参与选择。精确同分时选字典序最小姿态ID并报告全部同分ID；`tie_break` 和 `score_tie_policy` 均使用 `lexicographically_smallest_pose_id`。
- 计算2.0/3.0 Å的Top-1成功率；IFD Top-1按原始 `r_psp_IFDScore` 最小值选择，以明确姿态编号和精确ID连接Table S1。
- 对逐体系Top-1 RMSD（不是二元成功或名次）做双侧Wilcoxon，`zero_method=wilcox`、`correction=False`、`method=auto`；报告真实名义p值及alpha 0.05决策，不强求显著，不推断因果或普遍优势。
- 如实报告0.3 kcal/mol峰高下CDK2 2b52异常，不改分数。与OpenBPMD 2022 SI Figure S1（S=98.5、p=0.00197）对照，保留两组值及差异标志；不调整舍入源数据计算去匹配已发表汇总，也不将其归于Clark2016。
- `paired_variable`、`p_value_interpretation` 为非空自由文本；计数为排除布尔的JSON整数，分数/比例/统计量为有限数值；中位差容差1e-9 Å。

输入索引、输出字段、单位和数值协议见文件部分所列的输出协议。所有运行证据保存在`/app/` 交付目录内。

提交的 JSON 对象成员名必须唯一，数值必须有限；产物路径可指向 `/app` 内的文件。

配对效应可采用任一已声明的相减方向，中位数符号须与之对应；improved 始终表示 OpenBPMD RMSD 更低。

## 文件

| 路径 | 说明 |
| --- | --- |
| `/app/inputs/` | 姿态评分、RMSD 与方法对照数据。 |
| `/app/` | 提交结果与必要运行证据。 |
| `/app/output-contract.md` | 输出内容与提交格式。 |
