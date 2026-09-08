# XPR1：第3节启动包

当前版本整合既有结构文件、用户结构表、来源记录与本地检查工具，供第4节开展结构清点和质量检查。
**这不是已经跑通的微型蛋白生成项目，也不是已完成生物学验证的结果。**

研究方向：后续以XPR1结构与构象信息为基础开展微型蛋白设计。现阶段不生成候选，也没有确定最终设计靶标或留出家族。

## 现在只需要做什么

1. 复核、提交本次更新，不重建原有51个结构文件。
2. 在普通电脑运行下面的检查命令，无需GPU、交我算或AI服务。
3. 返回`READY_FOR_SECTION4_INITIAL_QC`后，开始第4节的初步结构QC；这不表示第4节已经完成。

本次固定证据见[启动验收报告](reports/acceptance/report.md)。复跑会生成新的带时间戳报告，不覆盖该快照。

## 安装与运行

已实际测试：新建venv、Python 3.12.13、Gemmi 0.7.3、macOS arm64。Linux、Windows、conda安装方式与交我算尚未实机验收。
Gemmi是本地结构文件解析库，不是Gemini。只有安装依赖需联网；`check`不联网、不上传数据。

macOS/Linux，在项目目录内执行：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run_pipeline.py check
.venv/bin/python -m unittest discover -s tests -v
```

Windows PowerShell，在项目目录内执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_pipeline.py check
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

已有conda也可通过`conda env create -f environment.yml`安装独立环境。环境准备好后，每次只需：

```bash
python run_pipeline.py check
```

这里的python指本项目环境。macOS/Linux还可运行`bash run_pipeline.sh check`，优先使用项目内venv。
退出码0为技术检查通过；1为检查失败；2为命令、配置或环境错误。报告位置会打印在终端。

## 本次资料

| 内容 | 数量 | 用途 |
|---|---|---|
| 原始mmCIF | 51份，未改动 | 与用户结构表对应 |
| 结构表 | 51条、9列CSV | 保留源Excel内容及状态标签 |
| 官方组装体 | 54份 | 全部已声明组装体；3个SPX-only条目各有2个 |
| wwPDB验证报告 | 51份压缩XML | 为后续科学QC提供输入，未判定质量合格 |
| EMDB元数据 | 51份JSON | 去重后的全部关联EMDB编号；不是密度图体数据 |
| UniProt Q9UBH6 | FASTA和JSON各1份 | 标准序列，两种文件中的序列已核对一致 |
| 输入校验和 | 212个文件 | 209份结构/补充资料，加结构表及2份来源记录 |
| 自动测试 | 26项 | 正常输入、故障输入及门槛不得误放行 |

51条记录包括48个TMD条目、3个SPX-only条目，分别来自表中10个与2个论文家族。这里只描述给定快照，不是对当前文献穷尽性的重新断言。

## 检查做了什么

- 表格格式、重复编号、文件缺失、多余文件、论文家族与primary DOI的一致性。
- 原始CIF文件名、内部编号和数据块编号对应；结构可解析；原子数相符；坐标为有限数值。
- 表格DOI与CIF的primary citation DOI对应。
- 所有输入的当前SHA-256与冻结基准逐项匹配；不证明最初下载日期或历史文件从未改变。
- 补充资料可解压/解析，并与来源记录和条目身份信息对应。
- 提取构建体、链、序列引用、突变、缺失、配体、组装体及分辨率等原始元数据，保存为JSON；提取不是科学审核。

本次54个官方组装体CIF的内部编号均为`XXXX`。脚本以官方URL记录，加上原条目的标题、聚合物序列和文献交叉核对；不伪造内部编号匹配。组装几何与生物学适用性仍待第4节检查。

## 尚未完成的事项

- 18条原表记录仍为`UNRESOLVED`；其余作者状态标签也尚未跨家族统一。
- 所有结构角色仍为`UNASSIGNED`；未冻结设计、反靶标或留出集合。
- 构建体到Q9UBH6的残基映射、膜方向、糖链遮挡、局部质量和表位可设计性未验证。
- GPU、CUDA、驱动、模型权重与生成流程未验证。
- 原始51份CIF最初下载日期未记录；本次登记日期不冒充原下载日期。未逐字节比较原文件与当前RCSB版本。
- 本次未重新全面审阅论文正文及勘误/撤稿状态；关键结论使用前仍需核查。

因此，通过仅表示**可以开始第4节初步结构检查**；不表示第3节全部长期要求完成，更不表示可以跳过第4节直接生成候选。

## 文件位置

```text
config/                     检查配置；pilot/scale明确禁用
data/structure_manifest.csv  源表的CSV版本
data/checksums.sha256        已冻结输入基准，check绝不重写
data/source_snapshot.json    上游提交、源表哈希和转换记录
data/supporting_sources.json 补充下载的实际URL、时间、哈希
data/data_provenance.csv     209份资料的来源总览
data/candidate_registry.csv  空候选表，仅表头，没有虚构结果
data/raw/                   原始文件，不直接覆盖
data/processed/             后续处理结果及父文件追溯
src/                        本地检查、来源和下载实现
tests/                      自动测试
models/                     后续模型及权重来源记录
results/                    后续科学计算结果，当前为空
logs/runs/                  实际运行日志，默认不提交Git
reports/acceptance/          本次冻结验收证据和结构元数据
reports/runs/                每次复跑报告，默认不提交Git
reports/decision_log.md      决策记录
reports/risk_register.csv    风险与后续关卡
docs/                       数据更新和后续模块说明
```

## 不要为通过检查重写基准

本包已带基准，正常使用只运行`check`。报错时先查原因，不要用`snapshot`把损坏文件重新记成正确答案。
`snapshot`仅创建不存在的新基准，拒绝覆盖旧清单。有意更新数据遵循[版本规则](docs/reproducibility.md)。
补充资料已包含。`python run_pipeline.py fetch-supporting`仅供补下载，访问官方数据库且拒绝覆盖已改变文件；它会更新下载清单，冻结后不要无故重跑。

## 来源、贡献与许可

原始结构来自[上游提交](https://github.com/66H6/XPR1/tree/c1b1b7d967f125eb10f2927f0800ab384782c1b1)，初始README记录为从`XPR1_project 2.zip`提取。原提交尚无分析代码或模型结果。
CSV源于用户Excel；通过表格工具转换，对468个单元格做OOXML交叉核对，修正工具将7个空白备注误读为19的问题，未改变用户原文件。

新增代码、测试与文档由AI辅助实现，团队仍须复核、理解和运行。基础入库工具不能直接冒充项目算法创新。
Gemmi 0.7.3为MPL-2.0；项目自有代码许可证待团队决定。数据遵循[wwPDB说明](https://www.wwpdb.org/about/usage-policies)与[UniProt说明](https://www.uniprot.org/help/license)。
实现参考：[Gemmi文档](https://gemmi.readthedocs.io/en/latest/cif.html)、[RCSB下载接口](https://www.rcsb.org/docs/programmatic-access/file-download-services)、[EMDB接口](https://www.ebi.ac.uk/emdb/api/)。
此仓库为内部工作底稿，不是已审定的匿名竞赛提交包；正式提交前需另做匿名化与最新版模板检查。
