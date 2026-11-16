# Seebeck 极性、各向异性与弛豫时间敏感性

## 背景

扩散 Seebeck 系数、载流子符号、迁移率和电导率的关系依赖模型和单位换算；不同材料的传输数据覆盖范围也可能不同。

## 任务

用 GaAs、p-GaAs、SnSe、Si 和 CdS 的 AMSET 与 CRT 数组，比较 Seebeck 系数，检查电导率与迁移率的单位一致性，并分析散射模型对结论的影响。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 覆盖公开数据中的全部材料、浓度、温度和 `xx/yy/zz` 方向。以微伏/开尔文报告 `S`，计算 `delta_S=S_amset-S_crt`。
- 以 AMSET 的电导率和整体迁移率计算 `sigma_from_mu_S_m=abs(n_cm3)×1e6×e_C×mu_cm2_Vs×1e-4`，并给出 `(sigma_from_mu_S_m-sigma_S_m)/sigma_S_m`；不要把名义掺杂与实际载流子归一化的差异强行置零。
- 报告载流子极性、SnSe 方向差异和模型差别；根据能量依赖与输运矩分析弛豫时间因子是否消去，并说明数据对扩散项及声子拖曳的适用范围。
- 判断 `diffusive_only_materials` 时，须区分给定资料实验比较的范围与 AMSET/CRT 数组所含的物理贡献；请查阅随附给定资料及补充材料。
- 提交可复算的 `analysis.py`、运行记录 `run.log` 和科学摘要 `report.md`。脚本须使用 `python analysis.py --inputs environment/assets --output final` 读取公开数组并生成结果；记录格式见公开输出契约。不要用外部结果替代数组分析。
- 将四个必需文件 `results.json`、`analysis.py`、`run.log` 和 `report.md` 全部写入 `/app/final/`；`run.log` 须为公开输出契约规定的 JSON 对象。
- 报告字段、覆盖要求及格式见 `environment/assets/public/output-contract.md`。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/raw_data/unpacked/` | 上文指定材料和方法的输运数据 |
| `/app/environment/assets/public/output-contract.md` | 公开提交规范 |

工作目录为 `/app`，输入位于 `environment/assets/raw_data/unpacked/` 下的 `seebeck/` 材料目录，使用 GaAs、p-GaAs、SnSe、Si、CdS 各自的 `AMSET_transport.json` 和 `CRT_transport.json`。配套 PDF 说明文件位于 `environment/assets/` 下。结果写入 `/app/final/`。

**交付物**

| 路径 | 内容 |
| --- | --- |
| `/app/final/results.json` | 量化结果 |
| `/app/final/analysis.py` | 可复现分析代码 |
| `/app/final/run.log` | JSON 运行记录 |
| `/app/final/report.md` | 科学报告 |
