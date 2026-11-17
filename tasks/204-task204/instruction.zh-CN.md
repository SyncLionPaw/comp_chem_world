# 铜离子参数的自旋态与能差诊断

## 背景

孤立铜原子的自旋态影响电离能和 QEq 参数。

公开输入给出原子计算与原生对照协议。

## 任务

比较 Cu(0)、Cu(+1)、Cu(+2) 能量，按最低能选态，诊断 triplet 替换及后续稳定性。

## 要求

- 采用 CCSD(T)/def2-QZVPP 全电子相关。主对照为非相对论 RHF/UHF，无 ECP 或冻结核：Cu0 doublet、Cu1 singlet/triplet、Cu2 doublet；quartet 可选。保留全部尝试。SCF 收敛 1e-12 Eh，CC 能量 1e-10 Eh、幅度步 1e-8；能量比较 1e-6 Eh、S² 1e-4。计算 IP0、IP1、chi=(IP0+IP1)/2、J=IP1-IP0，提供 J-K 异号的两个中性 pair 反模型。
- 仅使用本题公开输入，保留全部必要状态、失败、单位及可复现证据。

- 按所列输出约定提交规定产物。

## 文件

| 路径 | 说明 |
| --- | --- |
| `/opt/qeq-public/` | 公开数据、模型与计算参数。 |
| `/opt/qeq-public/output-contract.yaml` | 输出内容与提交格式。 |
| `/app/outputs/` | 提交结果与必要运行证据。 |
