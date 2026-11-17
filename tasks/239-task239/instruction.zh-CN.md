# BEP势垒标度：成对分组验证与外推边界

## 背景

所供 BH76 参考势垒用于描述性 BEP 验证；这是外部扩展，并非 Rad-6 论文动力学复现。

输入包括 BH76 势垒记录及 GMTKN55 背景和使用说明。

## 任务

对全部38个正向pair做带截距OLS，计算34折TS留组LOGO与38折pair留一LOPO，量化参考耦合与迁移边界。

## 要求

- BH76 `.res` 仅作为文本，不执行；保留物理行号、源顺序/大小写、化学计量系数及负势垒。相邻记录为正反向pair，首条固定正向；以C=0.043364104241800934 eV/(kcal/mol)换算，Eaf=首条*C、Ear=次条*C、deltaE=Eaf−Ear。
- 全部38正向pair等权做带截距OLS，执行34折TS留组LOGO、38折pair留一LOPO。正反向不可拆分；LOGO无TS重叠，报告LOPO重叠；给出验证MAE、baseline、最大误差和外推计数。
- 重算参考物种/重复TS计数、总体恒等式cov(deltaE,Eaf)=var(Eaf)−cov(Eaf,Ear)，以及各重复TS共同模式扰动对协方差和OLS系数的影响。
- fold按唯一fold_id、预测/敏感性按pair_id对齐；保留具有语义的源顺序，不漏项、重复ID/JSON键或泄漏。数值绝对/相对容差1e-8，计数和布尔精确。
- 解释参考耦合与外推边界，不宣称因果BEP、普适/前瞻精度、动力学速率或未执行的控制。这是描述性外部扩展，不复现Rad-6动力学；不新增DFT、TS搜索或微动力学。
- 本地使用给定数据，不联网。

- 按所列输出约定 将所需结果和证据提交至 `/app/`。

## 文件

| 路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 势垒数据与分析参数。 |
| `/app/` | 提交结果与必要运行证据。 |
| `/app/environment/assets/OUTPUT-CONTRACT.yaml` | 输出内容与提交格式。 |
