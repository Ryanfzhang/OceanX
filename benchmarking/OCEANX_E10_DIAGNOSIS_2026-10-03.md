# OceanX E10：运行、交付与效率问题记录

本文所有时刻统一使用日本标准时间（JST，UTC+9）；日期为 2026-10-03。
耗时、运行 ID、路径和原始记录保持不变。

本文记录本次对话中已经检查的代码和服务器运行证据，供下一轮设计讨论与修复使用。
它不是执行指令，不授权修改服务器、终止任务、重跑付费实验或调整研究策略。
本次只新增这份诊断文档，没有修改运行逻辑。

## 1. 结论与范围

研究深入本身不是这次需要压缩的对象。需要消除的是：

1. 保存的文件被复用，但上一次分析的语义和上下文没有有效接续，导致重复理解数据。
2. benchmark 的 OceanX 仍承担生产端交互图的发布、注册和绑定要求，其他方法只需保存图。
3. 绘图 API 说明自称完整，实际上缺少本次使用的接口、参数和组合限制，导致模型试探。
4. 补图仍按普通 Expert 工作流执行，并扩展为接口调试、结果检查和大篇幅报告重写。
5. Research 模式预设了一次文献咨询，而不是完全由 Coordinator 按证据缺口决定是否咨询。
6. Search Expert 的咨询扩展为数值分析，其中两次执行等待占用了约 9 分 40 秒。
7. 一个后续节点的首次尝试未绑定到研究树；已有报告仍触发恢复委派。
8. 新的报告兜底、时间预算与运行记录补丁尚不能证明以上问题已经解决，并有单独的边界风险。

这些问题分属工作接续、交付协议、接口说明、委派边界和树绑定，不应统一归因于
“模型慢”“研究过深”或“服务器权限出错”。

本文不声称所有 query 都会发生这些问题，也不把一个 E10 的前后差异当作严格 A/B 效果。
没有重新评分科学报告，也没有根据诊断给三个方法排名。

## 2. 检查对象与版本

### 2.1 服务器运行

- 项目 checkout：`/home/mafzhang/code/OceanX`。
- r2 运行目录：`/import/home3/share/oceanx-bench/methods-oceanx-flash-r2/runs/OceanX`。
- attempt：`E10/attempt-1791005003095548036-f34bb7b3`。
- 状态数据库：该 attempt 下的 `state/workspace.sqlite3`。
- 任务目录：`workspace/OceanX Tasks/E10--f07113931f5e`。
- task ID：`task_f07113931f5e4442be824e5fcaa74ccf`。
- request ID：`req_f21456986b324486bf8ff97ec4ab3ea3`。
- 开始时间：14:23:29 左右。
- 运行启动时的提交：`6cbd4f0`。
- 模型调用记录中的模型：`deepseek-flash`。

数据库以只读方式打开；检查使用模型调用记录、执行记录、研究树、报告和少量代码/日志。
没有加载原始大型 NetCDF 数组或完整大型 conversation checkpoint。

**时间边界：**整体运行状态的最后一次已记录检查约为 15:34；补图和 Search Expert 的
已结束尝试随后被单独回溯检查。本文不把 15:34 的状态当作阅读本文时的实时状态，
也没有审计该时刻之后的最终完成情况。

### 2.2 实际提交的问题

> Using the supplied GLORYS12 monthly temperature, salinity, velocity, sea surface height and mixed-layer thickness for 2011-2020 off California and Oregon (30-48 N, 130-116 W), compare the product's mixed-layer thickness with mixed-layer depths you compute from the temperature and salinity profiles. Quantify the differences by season and region, and determine how much comes from definitions and averaging and how much from the ocean state.

问题需要分析、定量比较和解释，但没有明确要求交互式可视化。
确认产品 MLD 定义与时间平均方式具有科学价值；不能由此推出需要完整的初始文献综述，
也不能推出图必须通过 OceanX 交互图协议交付。

### 2.3 本地未提交的 Claude 补丁

本地 working tree 在检查时已有报告交付、研究时间预算、kernel preflight、运行 inventory
以及文档和测试的改动。详情见 `CODEX_HANDOFF.md`。

这些工作树改动不属于 r2 启动时的 `6cbd4f0`。不能把本地已有实现当作 r2 已经应用，
不能期待运行中的进程自动加载之后的源码修改。本文对新补丁的评价是代码审查意见，
不是部署后的效果验证。

## 3. 已有证据：时间花在哪里

### 3.1 整体运行快照

约 15:30（开始后约 66.6 分钟）的已记录快照：

| 项目 | 观察 |
|---|---|
| 模型请求记录 | 440 条，其中 1 条当时仍在运行；包含上下文压缩请求 |
| 模型调用活跃时间的区间并集 | 约 48.24 分钟，约占当时墙钟时间 72% |
| 代码执行 | 215 次：194 成功、20 失败、1 超时 |
| 代码执行活跃时间的区间并集 | 约 20.8 分钟，部分与模型调用重叠 |
| 执行方式 | 44 次 kernel、171 次 shell |
| 已写出的节点报告 | 7 份，不等于最终答案已经完成 |
| 已完成请求的 token 记录 | input 35,264,677；output 778,821，output 包括推理 token |

不同 Expert 可并发；模型时间、代码时间与墙钟时间不能直接相加。
input 数字包括缓存输入，不能按全部未缓存输入估算费用。

约 15:34（约 71 分钟）时，当前执行仍为 `in_progress`，尚未看到最终 `answer.md`
和完成态 `result.json`。已经有节点报告和部分图，因此“没最终结果”不等于“没有产物”。

### 3.2 主要阶段

| 阶段 | 已观察耗时 | 说明 |
|---|---:|---|
| 初始数据问题 B1.1 | 约 3.75 分钟 | 与初始文献/定义咨询并行 |
| Search Expert B1.2 | 约 17.84 分钟 | 包含产品文档咨询、数值分析、两次长等待 |
| 主要比较 B1.3 | 约 8.87 分钟 | 已交付报告和 3 个视图 |
| 分解 B1.3.1 / 统计 B1.3.2 | 分别约 10.73 / 10.83 分钟 | 并行，不能把两者相加成串行耗时 |
| 实现差异诊断 B1.3.1.1 | 约 14.86 分钟 | 已有报告，但没有已发布视图 |
| 同节点补图 | 约 6.4 分钟 | 54 个模型请求；见下一节 |
| 更深的 B1.3.1.1.1 | 首次约 12.5 分钟 | 与补图并行；首次未绑定，之后恢复委派 |

后续科学检查有可能合理；是否必要应看它能否改变结论，而不是仅凭树深度判断。
目前有明确证据的浪费集中在接口试探、咨询扩展、重复交付和绑定恢复。

## 4. 补图的 54 次请求：逐项诊断

### 4.1 尝试标识与数据

- 节点：`B1.3.1.1`。
- Agent：`ocean-process-255e6b81a2`。
- attempt ID：`12bd371705e94a0babec6dc5193fb2f3`。
- delegation ID：`0200d7d38ac14a94a2b5d43e6d1b7ff2`。
- 时间：15:18:01 至 15:24:26，约 6 分 25 秒。
- 模型请求：52 次普通请求、2 次上下文压缩，共 54 次。
- 模型 duration 求和：约 361 秒。
- output token：71,343，包含推理 token，不是全部可见文字。
- 代码执行：23 次，19 成功、4 失败；按执行开始/结束时间求和约 10.16 秒。

执行成功状态不代表内部所有操作成功。部分脚本用 `try/except` 捕获绘图错误，
错误只写入 stdout，整个代码执行仍标为成功。因此不能只看 4 个失败状态来判断绘图试错次数。

### 4.2 实际行为

| 时间 | 行为 | 诊断 |
|---|---|---|
| 15:18 起 | 打开父节点 `annual_fields.nc`、`mld-attribution-partition.nc`，查看变量、维度、坐标与属性；读取本节点 NPZ | 需要读取数据，但在重新理解已有结果的含义 |
| 15:18:33 | 读取 NPZ 对象数组失败：`Object arrays cannot be loaded when allow_pickle=False` | 随后修正读取方式；不是绘图耗时 |
| 15:18:57 起 | 试探图类型、面板方法、热图参数与轴要求 | 未直接使用一套明确且完整的接口说明 |
| 15:20 左右 | 地图保存报错：`spatial_map requires exactly one field2d layer` | 多层图与单层空间图的类型限制没有被预先说明 |
| 15:20:26 | 生成 4 个 `_probe_*` 测试图 | 接口试验已成为工作流的一部分 |
| 15:21:16 | 删除测试图预览；保存 `mld-partition-layers.nc` | 第一张正式图保存 |
| 15:21:28 至约 15:21:29 | 保存 `mld-partition-season-region.nc` | 两张正式图已经保存 |
| 此后至 15:24:26 | 重读图和父结果、核对数字与解释、重写报告并收尾 | 正式图保存后又花约 3 分钟，不是渲染计算 |

报告被重写为 424 行；一次生成报告重写脚本的模型请求输出约 9,420 token，耗时约 38 秒。
“补图”由此变成数据解释、API 调试、检查和报告重整的组合。

### 4.3 问题 P01：复用目录，没有有效接续工作上下文

**已证实：**每次委派重新编译并运行 Expert 子工作流；同一个身份/目录不代表继承前次
完整模型消息。`graphs.py::expert` 在尝试结束后关闭 kernel。新尝试可读旧文件，
但不能依赖上一次的内存变量仍存在。

任务原始数据描述由 `_describe_task_data` 缓存共享；这不等于所有派生数组、NPZ 对象、
分解项与绘图映射都有共享说明。`_earlier_work` 主要给祖先/依赖目录路径；新的
`_earlier_attempt` 补丁也主要指向已有报告和文件，并不恢复前次对话。

**影响：**模型重新读文件、查形状和含义，甚至探测已有计算的组织方式。

**分析：**加载数组用于绘图合理；重复发现已经完成的分析语义不是常规必要成本。
不建议为此恢复跨节点共享 kernel：那会重新引入并发串行化与变量污染。
应讨论如何让一个小交付动作明确接续已有结果，而不是把“同文件夹”当作“已接续”。

**尚未确认：**单独恢复更多历史消息能节省多少时间；不能从这一例推算效果。

### 4.4 问题 P02：benchmark 沿用生产端交互图交付要求

**已证实：**`run_oceanx.py` 走生产 Agent Server 路径，提交原始 query。
通用 Expert 规则要求 `ScientificFigure.save('name.nc')`；Coordinator 把 server-verified
Published results key 作为图的交付边界，独立 PNG 不被视为 desktop result。

`ScientificFigure.save` 生成自描述结果和 PNG 预览；`collect_oceanx.py` 收集已有注册结果及
预览，不负责自动把任意计算数组画成图。`run_oceanx.py` 在运行结束后调用 collector。

**影响：**即使 benchmark 最后评分读取的是 PNG，OceanX 仍要先完成交互图的结构、发布与绑定。
Claude 和 Finch 的 runner 要求保存最终图文件，没有同等的 OceanX 注册要求。

**分析：**这是交付协议负担不对称。PNG 同样需要 Expert 或代码选择科学表达，但不必为了
PNG 评分先做交互视图。可讨论 benchmark 专属的静态图交付方式，保持 desktop 交互行为不变。
这只是待批准方向，本文没有修改协议。

### 4.5 问题 P03：绘图说明不完整，却被标为 complete

**已证实：**`graphs.py::build` 注入的文本是
`Figure API (complete; do not read OceanX source code to learn it)`，实际提供构造函数和
3 个示例：时间序列、单层地图、散点图。

`expert_execution.py::FIGURE_API_CONTRACT` 和本次磁盘上的 `result-api.md` 也是这份简略说明，
没有完整的热图/分类图参数、支持的图类型与多面板/多图层组合限制。

本次试错包括：

- `categories(..., values=...)` 参数不接受。
- `heatmap(..., variable=..., units=...)` 参数不接受。
- 不带 x/y 创建 panel，报缺失必需参数。
- `spatial_map` 保存多 `field2d` 图层，报类型限制错误。

**影响：**模型猜参数、检查方法、测试图类型、生成测试图，再改写正式图代码。

**分析：**模型没有直接按已有例子工作也是行为因素，但文档与实际 API 的契约缺口是真实诱因。
不能靠增加一句“不要试错”解决。应提供准确、短小、针对能力的参考与可运行示例，
最好从接口/测试保持同步，而不是单纯加长系统 prompt。

### 4.6 问题 P04：补图只有文字边界，没有独立的任务完成语义

**已证实：**`COORDINATOR_VISUAL_DELIVERY_POLICY` 允许一次补图，并要求从保存证据发布，
不做新分析、不做美化。但它仍进入普通 Expert 工具和调用预算，没有明确的
“保存要求的图、补必要引用、结束”完成机制。

**影响：**本次补图发生接口试验和报告大改写；虽然符合一次补图委派的数量限制，
仍产生 52 次普通模型请求。

**分析：**需要减少的是补交付的工作范围，不是降低科学研究深度。
不建议增加 visualization Expert、科学模板或多层自动修复链；这些不是解决本例的必要条件。

### 4.7 问题 P05：报告“本次更新”判据可能增加补交付成本

**代码事实：**`collect_report(previous_revision=...)` 对没有变化的已有报告返回空结果。
当委派文本包含同一个节点号时，`expert_assignment_key` 通常得到稳定的
`reports/<node_id>/report.md` 路径。因此这里的主要问题不是文件必然换位置或丢失，
而是“已有报告没有变化”会被视为“本次没有收集到报告”。另一个独立边界是报告目录键
从委派文本推断，而不是直接使用结构化 node_id；文本缺失/歧义的实际影响尚未核实。

**分析与风险：**补图明明可以复用科学结论，但交付语义强调本次有新报告，可能诱导重写或复制。
不能把本次 424 行重写完全归因于这个判据：模型决策、委派文本也有影响。
应区分“报告可复用”“本次补了图引用”“本次没有有效回答”，不靠大篇幅重写证明交付。

### 4.8 待核实：测试图注册后的清理

本次测试图通过 `ScientificFigure.save` 保存；该接口同时注册结果。之后看到测试预览被删除。
尚未逐项核对 registry 中对应记录是否撤销，以及最终回执是否完全排除了测试结果。
不能宣称最终已污染；应检查是否存在删除文件但保留注册记录的情况。

## 5. 文献咨询的近 18 分钟：逐项诊断

### 5.1 已结束尝试

- 节点：`B1.2`。
- Agent：`literature-3db00e8330`。
- attempt ID：`0697f5a9488a4f37ab222395d539f71f`。
- 首次模型调用：14:24:07；末次模型调用结束：14:41:58。
- 墙钟约 17 分 50 秒；53 次模型请求。
- 模型 duration 求和约 377 秒；output 74,243 token，包含推理。
- 报告约 32 KB，含产品定义、月平均影响、区域文献及自行计算的检查。

### 5.2 问题 P06：初始文献咨询是 Research 模式预设步骤

**已证实：**`runtime.py::OCEAN_EXPLORATION_POLICY` 要求初始咨询与数据描述并行启动；
`build_ocean_runtime_composition` 中的 research team policy 要求用一次独立 Search Expert 咨询
构建研究树。实际运行的 `6cbd4f0` 同样含有这些要求，不只是本地最新文本。

Coordinator 仍选择咨询问题，但“是否需要先咨询”并非完全自由。
`BENCH_LITERATURE_MODE=search_only` 限制全文获取，不代表禁用搜索、不代表短咨询，
也没有设置咨询专属的较小时间或调用预算。

**影响：**Research 模式带来固定的初始咨询倾向，且初始数据任务完成后可能等待咨询。

**分析：**文献可以帮助提出竞争解释，但不应默认是所有数据分析问题的启动门槛。
应讨论由 Coordinator 根据具体定义/方法/机制证据缺口决定是否咨询。
本例确认产品 MLD 定义有必要，不能把整个咨询都认定无价值。

### 5.3 问题 P07：Search Expert 将定义咨询扩展成数据分析

**已证实：**这个 Search Expert 不只检索资料，还读取温盐/MLD 文件，编写和运行
`mld_probe.py` / `mld_probe2.py`，比较不同定义并对 120 个月做检查。

其中两次长执行：

| 时间 | 执行 | 结果 |
|---|---|---|
| 14:28:51 起 | `python mld_probe.py 201101` | 约 300.3 秒后运行时超时 |
| 14:34:01 起 | `timeout 280 python ... M.process('201101')` | 约 280.2 秒后失败；命令自身带 280 秒上限 |

两次长等待共约 580.5 秒，即 9 分 40 秒。后来修改的脚本全月运行约 18–20 秒，
又运行两次以保存/查看输出。不能仅凭末次速度认定前两次慢的底层原因，仍需核对脚本差异。

**代码边界：**Search Expert 虽然不预先启动数据 Expert 的 Python 路径，但拥有执行工具；
角色说明允许 reproduction 工作，没有从能力上禁止数值分析。

**影响：**文献/产品定义咨询成为第二条数值分析工作流，延长初始阶段，并与物理 Expert
的研究职责产生潜在重复。

**分析：**不宜一刀切禁止 Search Expert 所有计算，论文复现确有可能需要计算。
需要区分“查定义/咨询”与“复现/数据诊断”，让这次具体委派的范围清楚。
对本例，资料冲突应交回 Coordinator 决定是否委派数据验证，而不是自动扩展到全时段分析。

## 6. 问题 P08：树绑定失败导致已有报告再次委派

### 6.1 已观察事实

- 后续节点 `B1.3.1.1.1` 在约 15:18 创建并被选中。
- 首次 Expert 的模型调用记录 `node_id` 为 `None`。
- Agent `ocean-process-731940c582` 在约 15:27 已写出非空报告。
- 首次尝试约 15:30:32 结束，但研究树没有登记这次节点结果/attempt_returned。
- 15:31:18 Coordinator 说明该报告未绑定到树，并重新委派。
- 恢复尝试的模型调用记录才出现正确的 `node_id=B1.3.1.1.1`。

Coordinator 的原话包含 “placeholder probe entries”；这不是报告全文被证实都是 placeholder。
已经检查的报告有实质科学 Summary，应区分回执问题与报告内容问题。

### 6.2 代码与待证实原因

`delegation.py::resolve_delegation` 在节点当时不存在时，把指定/推断的节点降为
`node_id=None, binding=unbound`，任务仍可继续。
`graphs.py::receipt` 只有在 `run.node_id`、报告路径和 handoff 都存在时才 attach_result。

因此，“执行完成且报告存在”与“树成功接收交付”是两个独立条件。

**待核实：**是否因同一次模型回复并行调用创建节点与 task，导致绑定检查早于节点创建。
目前没有足够的精确工具调度时间证据证明这一竞态，不能把它写成已确认根因。
也应检查 node_id 是否在实际委派中被遗漏或丢失。

### 6.3 影响与建议方向

树仍把节点视为缺少结果，Coordinator 发起新的恢复工作流；该时间不是新增科学研究的必然成本。
报告自动保存补丁也不能修复 `node_id=None`，因为本例报告本来就已经保存。

应首先定位绑定丢失的位置，明确失败如何反馈/恢复；不能让执行悄悄变为 unbound，
再靠 Coordinator 完整重派来补交付。具体修法待诊断完成后决定。

## 7. 问题 P09：调用上限不是效率目标，文件存在也不是交付完整

多个 r2 Expert 尝试接近普通调用上限，且部分 report 已存在但视图未交付。
当前证据不能说明这些科学尝试全部应更早停止。

需要分开记录：

- 研究本身是否还有可改变结论的后续问题；
- 本次报告是否保存、是否对应本节点；
- 图是否交付、是否被报告正确引用；
- 树是否接受结果；
- 最终答案是否完成。

不能把四类交付问题都解释成“Expert研究还没做完”，也不能靠限制研究树深度代替修交付。
54 个模型请求里包括 2 次压缩，同理其他尝试的 ledger 请求数量可以大于框架普通调用计数。

## 8. 历史基础设施缺陷：与现存问题分开

`CODEX_HANDOFF.md` 记录的 r1 故障包括：自己 outputs 的只读错误、kernel 启动失败、
同一根分支同角色共用工作区/kernel、交付失败导致重派。

已经提交的主要修复：

| 提交 | 改动 | 本次证据与限制 |
|---|---|---|
| `8df7791` | 规范读写根重叠；Linux kernel independent 启动；保存启动日志 | r2 已检查的错误记录未出现旧 kernel 启动/自身只读故障；不证明所有情况永远正确 |
| `e9f490e` | kernel 测试使用实际解析后的解释器路径 | 测试路径修正，不是研究策略优化 |
| `6cbd4f0` | 完整节点身份；分节点目录/kernel；尝试结束关 kernel；提供祖先/依赖目录 | r2 已有可工作 kernel；同时跨尝试不再保留内存，需要文件化复用 |

工作区按节点隔离应保留；不应为了减少读文件把兄弟节点重新合并到一个 kernel。
关 kernel 可释放资源，但产生重新加载数据/导入环境的成本，应该单独测量。

之前的“没有 chmod，因此自身 outputs 不会被只读”说法不成立：Linux sandbox 的只读挂载
并不需要 chmod。也不能把现存长耗时继续一概归因于已修复的只读问题。

r2 已检查的代码错误包括数组形状/索引、缺少参数/键、路径与shell语法、NPZ对象读取、
绘图类型限制等。成功状态里可能还含捕获后的错误，应查看日志内容而非只数状态。

## 9. 最新未部署补丁的审查意见

以下内容来自本地 working tree，不是 r2 效果。

### 9.1 报告兜底：改善文件交付，但有覆盖风险

新增逻辑在本次未收集到更新报告时，把最后一条非工具文本直接保存为 report.md。
`_prose` 去掉工具标记，但不保证文本是实质性报告。

- 一句“Done”也可能成为已保存报告；文件 completeness 不等于科学 completeness。
- 如果已有完整报告本次没变化，collect_report 返回空；随后简短 closing 可能覆盖原 canonical 报告。
- 有历史副本不等于 canonical 交付始终正确。
- 这不是建议增加一个模型裁判；首先要明确保留既有报告与本次增量交付的语义。

### 9.2 第 60 轮追加一次 plain-text retry：实际请求可达 61

框架普通轮次计数仍为 60，但 middleware 可额外发起一次模型请求，测试也覆盖了这一行为。
需要对计费和 benchmark 明确披露；不能把“60轮”误写成绝对最多60次 provider请求。
压缩请求还应单独计数。

### 9.3 75% 时间预算：能停止新委派，不保证按时完成

180 分钟 query budget 对应约 135 分钟停止新委派。
已经运行的 Expert 和后续 synthesis 仍可能超过剩余时间。
这个机制不是 2 分钟/query，也不是仅改 shutdown 等待；它改变 Coordinator 的运行行为。

本例 71 分钟时的绑定与补图问题，不能靠 135 分钟停止委派来修复。
如果对照旧运行，预算提示和停止规则应作为策略/运行配置变化披露。

### 9.4 preflight 与 inventory：有诊断价值，不直接解决工作流冗余

- kernel preflight 能在付费调用前发现不支持的环境，但 r2 已有健康 kernel。
- inventory 能暴露缺失文件，不自动纠正树绑定、图引用或科学结论。
- 只读错误可能是在正确阻止写其他 Agent 文件；超时可能是算法慢。
  把它们全归为 environment failure 会把现象与原因混淆。

### 9.5 conversation checkpoint：外层 120 秒仍有内层 30 秒

benchmark client 的 shutdown 等待改为 120 秒，但 `research/launcher.py` 中
Agent Server 的内部停止等待仍是 30 秒。
因此不能仅根据外层增加等待就保证 conversation checkpoint 完整。
这是运行可审计性问题，不是 query 只能运行两分钟。

尚未对采用这份新补丁的服务器 attempt 验证 clean stop 与 checkpoint完整性。

## 10. 问题 P10：benchmark 比较口径与审计指标

### 10.1 交付要求不对称

OceanX 被生产图协议约束；Claude/Finch 保存普通图。
若论文主张比较科学研究质量和效率，应明确这个额外协议负担是方法组成部分，
还是与目标无关的 desktop 开销。不能一边按 PNG 评分，一边只要求一个方法制作交互图。

### 10.2 文献访问能力不对称

当前 `run_finch.py::prompt_for` 明确把 Finch 定义为本地 analysis-component baseline，
不提供网络或文献搜索工具；Claude 按配置可搜索，OceanX 有 Search Expert。

因此本配置不是三个方法都有相同文献工具的完整端到端对照。
这可能是合理的 baseline 选择，但需要明确披露，不能把差异全部归因于研究树或 lessons。

### 10.3 需要测量有效进展，不只数调用

建议下一次同题验证至少记录：

- 首次可辩护结论、首次节点报告、首次正式图、最终答案的时间。
- 每节点/attempt 的普通请求、压缩请求和额外 retry。
- 模型活跃区间、执行活跃区间与墙钟；明确并发，不能相加。
- 重读已有数据、API 探测、补图、报告重写、绑定恢复的用途归类。
- 真正的代码失败及捕获在 stdout 的错误。
- 报告存在但未绑定、视图保存但未引用、最终未交付的不同状态。

自动汇总可描述现象，必要时人工抽样确认用途，不把模型自报的“有效工作”当作唯一依据。
早期运行存在嵌套计量归属疑点；旧角色/节点 token 细分应审慎使用，不能用未经核实的
角色明细解释差异。当前应优先核对每条请求与 attempt/delegation/node 的实际关联。

## 11. 修复讨论顺序（尚未实施）

| 顺序 | 方向 | 验证目标 |
|---|---|---|
| 1 | 定位并修正树绑定丢失 | 正确委派的报告登记到对应节点，不因已有报告未绑定而完整重派 |
| 2 | 明确 benchmark 静态图交付 | 保存最终 PNG 即可被评分和引用，不被要求为此额外交付 interactive view |
| 3 | 补齐并校准绘图 API 文档 | 受支持的热图、多面板、多图层示例可直接运行，不必靠 probe 找限制 |
| 4 | 明确小交付动作的接续与结束语义 | 复用既有科学报告/数组；补图后只补必要引用，不重整整个研究 |
| 5 | 文献咨询按缺口选择，咨询与复现分开 | Search 不默认开展整段数据分析；需要数值判别时由 Coordinator 明确委派 |
| 6 | 收紧报告兜底的文件语义并验证记录完整性 | 不覆盖既有完整报告；准确记录模型请求、checkpoint与各类交付状态 |
| 7 | 同题新实验验证 | 比较质量、交付和耗时，不把更少调用直接等同更好研究 |

不建议此时用压缩研究树深度、恢复共享 kernel、增加 visualization Expert、
科学模板或多层自动修复来替代以上定位。

同题验证应使用新的实验目录，保留 r1/r2。运行前确认 query、数据、模型、推理设置、
并发、网络权限、预算及库快照。修改交付/咨询行为后，需说明这是系统行为变化，
不是纯环境补丁下的严格 A/B。

## 12. 对之前分析的更正

1. “补图花了 6.4 分钟”容易被误解成渲染慢。实际代码执行累计约 10 秒，
   大部分时间是围绕补图的模型工作流。
2. “18 分钟文献调研”不准确。它包含数值分析，两次执行等待占约 9 分 40 秒。
3. 补图试错不应只归因于模型不听话。API 被标为 complete，但说明缺失已被核实。
4. 同一个 Agent/目录不表示延续上下文，也不表示 kernel 内存仍在。
5. “报告已经保存”不表示树绑定、图引用和最终交付都成功。
6. r2 尚未最终交付不能说明没有科学产物；已有多份节点报告和图。
7. 旧基础设施修复有效与否，必须与新的工作流问题分开；不能把所有耗时都说成同一个 bug。

## 13. 代码定位与原始证据入口

路径相对于本仓库；代码持续变化，函数/常量名比行号更稳定。

| 文件 | 定位 | 用途 |
|---|---|---|
| `src/oceanx/runtime.py` | `OCEAN_EXPLORATION_POLICY`、`research_team_policy` | 初始文献咨询的预设要求 |
| `src/oceanx/runtime.py` | `OCEAN_EXPERT_WORKSTREAM_POLICY` | 交互图交付、派生数据与mask规则 |
| `src/oceanx/research/graphs.py` | `COORDINATOR_VISUAL_DELIVERY_POLICY` | 单次补图及Published results要求 |
| `src/oceanx/research/graphs.py` | `build`、`_earlier_work`、`_earlier_attempt` | API prompt、祖先文件与重复尝试提示 |
| `src/oceanx/research/graphs.py` | `expert`、`_close_kernel`、`receipt` | 新尝试、kernel结束、报告与树交付 |
| `src/oceanx/research/graphs.py` | `_prose`、`ExpertCallBudgetMiddleware`、`ResearchBudgetMiddleware` | 新的未部署补丁及边界风险 |
| `src/oceanx/research/delegation.py` | `resolve_delegation`、`StructuredDelegationMiddleware._prepare` | 不存在节点降为unbound、委派绑定 |
| `src/oceanx/research/services.py` | `expert_agent_key`、`report_path`、`collect_report` | 身份、报告路径与本次更新判据 |
| `src/oceanx/expert_execution.py` | `FIGURE_API_CONTRACT` | 绘图参考实际内容 |
| `src/oceanx/scientific_view.py` | `ScientificPanel.heatmap`、图类型校验、`save` | 参数差异、图组合限制、预览/注册 |
| `src/oceanx/team/profiles.py` | Search Expert profile | 文献/复现角色范围 |
| `src/oceanx/research/launcher.py` | `stop` 中30秒等待 | 内层停止与checkpoint风险 |
| `benchmarking/server/run_oceanx.py` | `oceanx_prompt`、`BenchmarkClient`、`main` | 原始query、生产运行路径、结束后collector |
| `benchmarking/server/collect_oceanx.py` | `collect_run` | 收集已有图/预览，不负责自动画图 |
| `benchmarking/server/run_claude.py` | `prompt_for` | 普通图文件交付要求 |
| `benchmarking/server/run_finch.py` | `prompt_for` | 普通图交付、无网络/文献搜索的baseline边界 |
| `benchmarking/evaluation/evaluate.py` | `code_failures`、inventory | 失败分类与完整性检查 |

服务器证据入口均在第2节的 attempt 下：

- `submitted_prompt.txt`：实际问题文本。
- `state/workspace.sqlite3`：`model_call_observations`、`code_executions`。
- 任务下 `agents/coordinator/research_tree.json` 和 `research_tree.sqlite3`：节点与事件。
- 每个 Agent 的 `reports/**/report.md`：交付文本。
- 每个 Agent 的 `.runtime/executions/<execution_id>/code/` 与 `logs/`：代码及输出。
- 补图 Agent 的 `.runtime/result-api.md`：本次实际提供的绘图参考。

再次检查时必须按 attempt ID 或准确时间段筛选：同一个 Agent 目录包含前一次研究和
后一次补图的执行记录，直接统计整个目录会把不同尝试混在一起。

## 14. 未完成核实清单

- [ ] `B1.3.1.1.1` 绑定丢失的精确工具顺序与参数传播。
- [ ] 补图四个测试图的注册记录是否被清理、是否影响回执/最终收集。
- [ ] Search Expert 两个长脚本与后来18–20秒脚本的具体算法/I/O差异。
- [ ] 各次视觉委派的任务文本，区分明确请求图与系统自行扩展的要求。
- [ ] 最新补丁部署后的 clean stop、checkpoint、canonical report保留行为。
- [ ] r2在15:34之后的最终状态、总耗时、最终引用与科学证据吸收情况。
- [ ] 三方法共同的最低交付契约和文献工具能力口径。
- [ ] 修复后同题对照的质量和效率；不提前承诺节省百分比。

上述事项仅为待核实/待讨论项，不表示已经执行或获得修改授权。
