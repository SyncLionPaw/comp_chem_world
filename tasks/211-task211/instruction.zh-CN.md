# 可达孔体积中的周期静电势保真

## 背景

原子电荷误差未必代表可达孔内周期势误差。

公开输入提供体系面板和电荷数据、几何与映射信息、势模型及方法约定。

## 任务

在固定四个 MOF 上比较全部四种电荷方法的完整周期孔内场。

## 要求

- 保留 DDEC3、PQeq_GMP、EQeq_ox_exp、NO_Q，以及 5.1e-6 精度下整行联动的完整兼容匹配。conducting Ewald 势单位 V；保持电荷原值，残余净电荷使用均匀背景，同几何/掩码上各场减去自身孔均值。孔排斥距离 UFF_sigma/2+1.5 Å，含等号；保留孤立孔袋，另报连通体积。采用 0.2 Å 基准网格及实际加密或位移，区分 padding 和空掩码。声明 tau_V/tau_F 与预算，区分网格/Ewald/映射误差，提供完整场 witness、保守界及 periodic_field.py 的 grid、pore_clearance、green_matrix。原场容差上限 1e-5 V；有限网格敏感性不证明连续收敛。
- 仅使用本题公开输入，保留全部必要状态、失败、单位及可复现证据。
- 提供自包含的 `periodic_field.py` 和 `accuracy.json`，以公开输入支持场回放。
- 回放调用 `green_matrix` 时可选支持 `apply_to=Q`，直接返回 `(G @ Q, proof)`。未实现该参数时返回 `(G, proof)`。两种计算形式均须给出全部可达网格点的同一零均值场。

- 对映射敏感的方法，`mapping_method_bounds` 必须保留 `conservative-pointwise-envelope` 控制；另行给出的更强全局极值结果不能替代该控制。
- 按所列输出约定提交规定产物。

## 文件

| 路径 | 说明 |
| --- | --- |
| `/opt/qeq-public/` | 公开数据、模型与计算参数。 |
| `/opt/qeq-public/output-contract.yaml` | 输出内容与提交格式。 |
| `/app/outputs/` | 提交结果与必要运行证据。 |
