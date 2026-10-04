# OceanX 修复方案（带版本控制）

**方案版本：v1.13（2026-10-04）**
**状态：v1.7 记录 Owner 根据 R3 实测批准的统一优化：阻止未请求的单独补图、限制送入模型的图片大小、优先复用持久 kernel、文献与数据分析分槽、成功收集后清理全部 scratch、以及第 30 次调用的报告检查点。图片仍可进入模型以判断空间 pattern，但使用有界预览。实现和本机回归见最新 Log；正式 benchmark 尚未启动。v1.8 记录 Claude 复核已推送的 `f404221` 后，经 Owner 授权做的四处修改：预览失败不再让 Expert 崩溃；scratch 只删大于 10 MB 的文件并列出清单；补图拒绝只在 benchmark 生效且识别更宽；检查点不再拒绝第 30 次已发出的调用。v1.9 记录 Owner 的决定：先把 benchmark 里每个 Expert 的模型调用上限从 60 降到 40，测几道题看分数和用时（设置见 `BENCH_OCEANX_EXPERT_CALL_LIMIT`，桌面端仍是 60）。v1.10 记录上限 40 的第一次测试结果和随之做的两处修改：模型工具调用多一个括号时不再让整题失败；只有用户自己的问题才能授权获取数据集。v1.11 记录 Owner 对 Q08 两个版本的暂定审阅分和据此做的修改：最终综合前能看到每个节点的完整 Result 和限制，Expert 把修正写在 Result 最前面，结论措辞不超过证据。v1.12 记录 Owner 决定把 benchmark 的数据 Expert 空位由 2 改到 3，以及对 Q08 为什么仍用 87 分钟的分析。v1.13 记录 Owner 要求实现的后台委派：同一批委派不再等最后一个 Expert 返回，每个 Expert 一返回 Coordinator 就继续；是接着做这条线还是等几条结果一起定，由 Coordinator 决定。并行 Expert 数成为设置：benchmark 在 `.env`，桌面端在设置对话框。**
基于提交 `88cab8b`。问题记录见 `OCEANX_E10_DIAGNOSIS_2026-10-03.md`。
分工：Claude 负责方案和审核，Codex 负责执行，Owner 负责提交每个版本。

## 1. 这个文件怎么用

- 改动按“包”做，一个包对应一次提交。Codex 做完一个包后填写下面的进度表，由 Owner 提交，再把提交号填进表里。
- 要回退某个包，就 `git revert` 它的提交。不改历史，不强推。
- 方案内容有变化时，在“方案版本记录”里加一行并升版本号；不要直接改已批准的条目。
- 表里没有的事情不做。遇到方案没覆盖的情况，写进本文件末尾的 Log，等 Claude 处理。
- 这些东西不能碰：
  - 数据、`download/data_manifest.json`、评分标准和参考答案；
  - 研究策略 `v2-nested` 和 60 次调用上限；
  - 学习库和 skill 里的学习区域；
  - 沙箱的严格程度和网络权限。
- 隐私：CMOMS 是私有数据。不提交它的数据或由它算出的任何内容，也不发给外部服务。评分标准、参考答案不给 agent 看。
- 运行进行中不改代码。每次重跑用新的实验名。行为有变化时，同步更新 `RUNNING.md` 或 `README.md`。
- 每个包先写一个修复前会失败的测试，再做最小改动，然后跑全量测试：

  ```bash
  PYTHONPATH=src python -m pytest tests benchmarking/tests -q -p no:cacheprovider
  ```

  `benchmarking/tests/test_run_claude.py::test_timeout_kills_children_retains_outputs` 对时间敏感，失败时先重跑一次再判断。

## 2. 进度表

| 包 | 内容 | 状态 | 提交 | Claude 审核 |
|---|---|---|---|---|
| A1 | 报告不被没改报告的尝试覆盖 | v1.2 已提交 origin；服务器同步见 Log | 991466e（A1） | 通过，v1.2 已复核。见 Log。 |
| A2 | 节点绑定不再悄悄失败 | 已本地提交；未推送 | a3b9a4d（A2） | 通过，可以提交。见 Log。 |
| A3 | 草稿图不算正式结果（交互模式） | 已本地提交；未推送 | cef4736（A3） | 通过，可以提交。见 Log。 |
| A4 | 只有用户明确要图才补图 | 已实现并通过全量测试，待审核与 Owner 提交 | | 通过，可以提交。见 Log。 |
| B | 无界面和 benchmark 运行只交付普通图片，不暴露绘图接口 | Codex 独立复核通过；全量测试通过，待 Owner 提交 | | Claude 实现，Codex 独立复核通过。见最新 Log。 |
| E | 文献咨询由 Coordinator 按需决定；咨询不做数据分析 | Codex 已复核；全量测试通过，待 Owner 提交 | | 通过，可以提交（Codex 独立复核）。见 Log。 |
| D | 已保存数据的清单 | v1.5 披露检查已完成；全量测试通过，待审核与 Owner 提交 | | 通过，可以提交。v1.5 的披露检查已复核。见 Log。 |
| C | 完整的绘图接口说明（交互模式） | v1.4 三处补充和措辞已完成；全量测试通过，待审核与 Owner 提交 | | 通过，可以提交。三处补充和措辞都已复核。见 Log。 |
| F | 记录与披露（不改行为） | 说明与披露已完成；全量测试通过，待审核与 Owner 提交 | | 通过，可以提交。见 Log。 |
| G | 大文件编辑路径缺少 `EditResult` 导入（方案外缺口，v1.4 新增） | Owner 已批准并完成；全量测试通过，待审核与 Owner 提交 | | 通过，可以提交。见 Log。 |
| R3 | 服务器开跑前检查，然后重跑 E10（`methods-oceanx-flash-r3`） | 已完成并分析，见 Log | | |
| R3 follow-up | R3 的六项耗时、token 与存储优化 | v1.8 已提交（`b0a2618`）；v1.9 的上限 40 在工作区待提交；服务器全量 1020 passed、4 failed：两个已知旧沙箱测试，加两个此前从未在服务器上跑过的 Finch 沙箱测试（已改，待复跑） | | |
| Linux 测试修正 | 修正取消测试的进程号及文件隔离测试的预期，不改沙箱 | 本机与服务器全量通过；Owner 已授权提交和服务器同步，见最新 Log | | |

执行顺序：A1 → A2 → A3 → A4 → B → E → D → C → F → G → R3。A1 没合入之前不要启动任何运行。

## 3. 方案版本记录

| 版本 | 日期 | 变化 |
|---|---|---|
| v1 | 2026-10-03 | 第一版。依据 Owner 的四个决定，见第 4 节。Owner 已确认全文，包括五项细节决定。 |
| v1.1 | 2026-10-03 | 并入 `CODEX_HANDOFF.md` 里仍然有用的部分（规则、基准、运行步骤、检查表、Log），并删除该文件。R3 出现异常时改为只报告，不再有预先批准的修复。各个包的内容不变。 |
| v1.2 | 2026-10-03 | A1 补充一种情况：沿用原报告、又没有结束语时，回执也要写明这次尝试没有新产出，并给出原因。v1 的文字漏了这种情况。另外明确：额外情况只写进本文件的 Log，不再另建 `CODEX_HANDOFF.md`。 |
| v1.3 | 2026-10-03 | 把审核时留下的要求写进对应的包，各包范围不变。B：开始之前先提交并行工作的改动；补图规则的措辞（来自 A4 审核）。C：草稿规则的措辞（来自 A3 审核）。 |
| v1.4 | 2026-10-03 | 审核 E、D、C、F 之后的修订。C：说明要读到结尾、`fig.panel` 的关键字参数、提示里留一行调用骨架（这一条等 Owner 确认）。新增 G 包：大文件编辑路径缺少导入（等 Owner 确认）。D：CSV 行数统计的两条加固。R3：Linux 上加跑 D 和 B 的测试文件，检查表加数据清单一行、图一行写细。 |
| v1.5 | 2026-10-03 | 复核 v1.4 的补充之后新增一处。D：工作区不允许向模型服务商披露元数据时，不生成也不放入数据清单。R3 的 Linux 测试加上大文件编辑的测试文件。其余各包不变。 |
| v1.6 | 2026-10-03 | 服务器上第一次完整跑 Linux 测试，`tests/test_sandbox` 里有两个旧测试失败。原因已查明，不是 A 到 G 引入的。R3 的第 1 项检查改为“除这两个已知失败外全部通过”。各包不变，沙箱不改。 |
| v1.7 | 2026-10-04 | Owner 批准 R3 后续六项优化。图片不是禁止送入模型，而是转换为最长边 1024 px、最多约 450 KiB 的 JPEG 预览；成功且无收集错误的 attempt 删除全部 scratch，并留下清单和释放字节数。另加最终综合必须核对所有返回节点的约束。 |
| v1.8 | 2026-10-04 | Claude 复核 `f404221`，Owner 授权按复核意见修改。（1）静态模式读图预览失败返回 `ReadResult` 错误，不再抛异常；（2）scratch 清理由“删整个目录”改为“只删大于 10 MB 的文件，记录列出每个被删文件”，因为 R3 的报告用相对路径引用 scratch 里的小文件，脚本也在其中；（3）补图拒绝只在 static（benchmark）运行生效，“研究者要了图”的识别放宽，补图句式只看任务段；（4）检查点只拒绝第 31 至 48 次调用发出的非文件工具。其余各项不变。 |
| v1.9 | 2026-10-04 | Owner 决定先把 benchmark 里 Expert 的模型调用上限由 60 降到 40，测几道题。新增设置 `BENCH_OCEANX_EXPERT_CALL_LIMIT`（10 到 60，`.env.example` 里写 40，桌面端不设置时仍是 60）；报告检查点和收尾阶段按比例跟着上限走（上限的一半和五分之四，60 时是第 30 和 48 次，40 时是第 20 和 32 次）；值写入 `arm.json` 的 `expert_call_limit`。其余各项不变。 |
| v1.10 | 2026-10-04 | 上限 40 的第一次测试：Q07 在 21 秒内失败（Coordinator 的工具调用参数多了一个 `}`，没有可执行的调用，整个请求结束）；Q08 完成。修改两处：（1）新增 `ToolCallRepairMiddleware`，参数是完整 JSON 加多余的右括号时修复并照常执行，没有可执行的调用时重试一次，Coordinator 和所有 Expert 都装；（2）Coordinator 和 Expert 的提示里写明只有用户自己的话才能授权获取数据集，Coordinator 不能自己授权（Q08 里 Coordinator 在任务描述里写“you are authorized to acquire”WOA18 和 Argo）。其余各项不变。 |
| v1.11 | 2026-10-04 | Owner 对 Q08 的暂定审阅分：上限 40 的版本 76.25，上限 60 的版本 72.50（评分标准仍是草稿，不是正式得分）。40 次版的主要扣分是最终答案没有吸收后来节点的修正（平均流速 0.879 改成 0.778 m/s，答案仍写 0.88）、对温度差异的解释过于确定、把 Argo 称为独立验证。原因查明：Coordinator 的树视图把每个节点的 Result 截成 320 字、限制只留第一句，修正埋在长摘要里它根本看不到。修改：新增 `update_research_tree` 的 `results` 视图，列出每个已返回节点完整的 Result 和限制，最终综合前读取；Expert 的摘要规则要求修正写在 Result 最前面、第一句限制写最影响结果的那条；Coordinator 的最终综合规则增加“修正过的值取代旧值”和“结论不超过证据、没有证据不称独立”。其余各项不变。 |
| v1.12 | 2026-10-04 | Owner 决定把 benchmark 的数据 Expert 空位由 2 改到 3（`BENCH_OCEANX_MAX_PARALLEL_EXPERTS=3`，`.env.example` 和默认值；桌面端仍是 2）。Q08 在上限 40 下用时分析：最长依赖链 51 分钟，Coordinator 分批启动造成约 25 分钟，空位等待约 9 分钟。其余各项不变。 |
| v1.13 | 2026-10-04 | Owner 要求实现 `task` 的异步，并定了规则：一条委派自己的后续，结果一到就直接委派；需要几条已派出的结果共同决定的新子问题，要等，由 Coordinator 决定。实现：每个 `task` 在 Coordinator 这次运行的后台启动 Expert，下一个 Expert 一返回就把这一轮交还给 Coordinator；新工具 `await_experts` 用来等（等下一个、等指定节点、等全部）；有 Expert 未返回时 Coordinator 不能结束。并行数：benchmark 仍用 `.env` 的 `BENCH_OCEANX_MAX_PARALLEL_EXPERTS`，桌面端新增设置（1 到 4，默认 2），随每次请求发送。其余各项不变。 |

## 4. Owner 的决定

1. benchmark 只交付普通图片，并且不暴露 OceanX 的绘图接口。
2. 补图不单独限制调用次数。绘图接口的说明给够，任务就不该用到 60 次。
3. 做“已保存数据的清单”。
4. 文献查询不是必做步骤，由 Coordinator 决定。

以下几项没有批准：评审打分角色、研究树深度或委派次数上限、补图或文献 Expert 的调用上限、共用 kernel、可视化 Expert、新的通用数据格式、滚动调度。

Owner 同时确认了五项细节（2026-10-03），执行时不用再问：

- 普通图片模式用环境变量 `OCEANX_FIGURE_DELIVERY=static` 开启，由 benchmark 启动脚本设置。桌面版没有这个开关，行为不变。
- 节点 `outputs/` 目录下的图片文件都算已交付的图，试验性的图放在 `scratch/`。
- Search Expert 在咨询里只查资料，不分析任务数据。
- 数据清单每个目录最多列 12 个文件，总量约 4,000 字符。
- 完整的绘图说明放在文件里，提示里只留简短规则和文件位置。

Owner 于本轮另行明确批准 v1.4 的两项待确认改动：交互 Expert 提示增加一行简短调用骨架，以及 G 包补齐 `EditResult` 导入。其余边界不变，不授权提交、服务器同步或 R3。

## 5. 对诊断文档的审核结论

| 条目 | 核对代码后的结论 | 对应的包 |
|---|---|---|
| P01 上一次的工作没有被接上 | 成立。重复尝试和子节点只拿到目录路径。 | D |
| P02 benchmark 沿用了交互图的交付要求 | 成立。 | B |
| P03 绘图说明不完整 | 成立。说明里只有 3 个例子，`ScientificPanel` 有 11 种图层方法；`heatmap` 和 `categories` 不接受 Expert 猜的参数；`spatial_map` 只允许一个 `field2d` 图层。 | C |
| P04 补图按完整尝试执行 | 成立。按决定 2，不加调用上限。 | A1、B、C |
| P05 “本次是否更新了报告”的判据 | 成立，而且 `88cab8b` 让它更糟，见 9.1。 | A1 |
| P06 文献咨询是预设步骤 | 成立，见 `OCEAN_EXPLORATION_POLICY` 和 `research_team_policy`。 | E |
| P07 咨询扩展成了数据分析 | 服务器证据成立。代码上也允许：Search Expert 有两个运行代码的工具。 | E |
| P08 尝试没绑定到节点 | 原因已有数据支持，见下面的说明。 | A2 |
| P09 调用上限不等于交付状态 | 成立。 | F、R3 报告 |
| P10 对比口径 | 成立。 | B、F |
| 4.8 测试图成了正式结果 | 已确认。`TaskResultStore._agent_views` 会列出所有 `.nc` 仍然存在的已声明视图。 | A3 |
| 9.1 兜底会覆盖报告 | 已在 `88cab8b` 上复现：补图任务没动 `report.md`，最后只说一句话，完整报告就被这句话替换了。 | A1 |
| 9.2–9.4 | 成立。 | F |
| 9.5 内层 30 秒停止等待 | 成立。按 Owner 之前的决定不改。 | 无 |

**P08 的依据：**
- 未绑定那次尝试的目录是 `ocean-process-731940c582`。
- 它正好等于 `expert_agent_key(task_f07113931f5e4442be824e5fcaa74ccf, ocean_process_expert, node_id="B1.3.1.1.1")`。
- 未绑定的尝试只能从委派文字里的第一个节点号得到标识，所以委派文字里写了这个节点。
- 因此失败的只可能是 `tree.has_node`。节点又是在同一分钟内创建的，说明绑定检查发生在节点写入之前。

## 6. 各个包的做法

### A. 交付的正确性

**A1. 没改报告的尝试不能覆盖已有报告。** 位置：`research/graphs.py` 的 `expert` → `receipt`。

- 本次尝试改了 `report.md`：照常交付，行为不变。
- 本次没改，但有结束语：只有下面三种情况，才把结束语存为报告。
  - 节点还没有非空的报告；
  - 角色是 `scientific_discussion_partner`；
  - 结束语本身就是一份报告，即 `report_summary(closing)` 非空。
- 其他情况下，只要节点已有非空报告，就原样交付它：
  - 回执带上它的路径和它自己的 Summary；
  - 挂到研究树时用这份 Summary；
  - 回执末尾加一行 `This attempt left the report unchanged and ended with: <closing>`。这一行只给 Coordinator 看，不传给 `attach_result`。
  - （v1.2）没有结束语时，回执末尾改为加 `This attempt left the report unchanged and gave no closing answer: <原因>.`。原因和 `_missing_report` 用同一套说法：`it reached its 60-call limit` 或 `it stopped after N model calls`，由同一个辅助函数给出。不这样做的话，一次用满调用却没有产出的重复尝试，回执会和成功交付一模一样。
- `_earlier_attempt` 的提示补一句：原报告仍然是这个问题的报告，只改这次工作改变的部分，不要重写。
- 测试：以上三种情况，写在 `tests/test_oceanx/test_native_subagents.py`。（v1.2）再加两种：沿用原报告且没有结束语；沿用原报告且第 60 次调用只输出了工具乱码。

**A2. 节点绑定不再悄悄失败。** 位置：`research/delegation.py`。

- 工作区里已有“等待节点写入”的改动（`NODE_WAIT_SECONDS`、`_awaited_node`）和两个测试，保留。
- 新增：`task` 调用显式传了 `node_id`，等待结束后树里仍然没有这个节点时，不启动 Expert，返回错误消息：
  `Not started: research-tree node <id> does not exist. Add or select it with update_research_tree, then delegate again.`
- 只从描述文字里推断出来的节点号不拒绝，仍按未绑定运行。文字里可能碰巧出现像节点号的字符。
- 不在回执阶段猜节点来补挂报告。
- 测试：显式的未知节点被拒绝，并且没有调用 handler；推断出的未知节点照常运行。

**A3. 草稿图不算正式结果（交互模式）。**

- `TaskResultStore._agent_views` 跳过文件名以 `_` 或 `.` 开头的输出。
- 在绘图说明里写明这条规则（见 C）。
- 测试写在 `tests/test_oceanx/test_explicit_figure_delivery.py`。

**A4. 只有用户明确要图才补图。**

- 两种模式下，`COORDINATOR_VISUAL_DELIVERY_POLICY` 都写明：那一次补图只针对用户问题里明确要求的图。
- Coordinator 自己在委派里写的要求不算。

### B. 无界面和 benchmark 运行：只交付普通图片

**开始之前**

- B 要改 `benchmarking/server/run_oceanx.py` 和 `benchmarking/RUNNING.md`。这两个文件里现在有并行工作（benchmark 重置、Finch）的未提交改动。
- `run_oceanx.py` 里的那部分调用 `configure_run(..., stack=stack)`，它依赖 `benchmark_run.py` 里同样未提交的改动。
- 所以先由 Owner 把并行工作的改动单独提交，再开始 B。否则 B 的提交会带上其中一半，单独检出那个提交时启动脚本会报错。
- 如果 Owner 决定暂不提交那批改动，Codex 在 Log 里列出 B 在这两个文件里改了哪几处，由 Owner 只提交这几处。

**开关**

- 环境变量 `OCEANX_FIGURE_DELIVERY`，取值 `interactive`（默认，桌面版行为不变）或 `static`。
- 只在一个辅助函数里读取它。
- `benchmarking/server/run_oceanx.py::backend_environment` 把它设为 `static`。
- `arm_record` 记录 `figure_delivery`。

**什么算交付**

- `static` 模式下，节点 `outputs/` 目录里任意层级的图片文件都算已交付的图。支持 `.png`、`.jpg`、`.jpeg`、`.svg`、`.pdf`。
- 试验性的图放在工作目录 `scratch/`。

**登记**

- `TaskResultStore.list` 只在 `static` 模式下把这些文件列为 `kind="file"` 的结果，写法参照 `_agent_view_record`：
  - `agent_run_id` 是 Agent 的标识。
  - `content` 包含 `agent_key`、`result_key`、`output_path`、`render_status: "static"`、`preview_file`、`workspace_files`。
  - 附一个带大小和 sha256 的 `TaskResultFile`。
- 跳过以 `_` 或 `.` 开头的文件。
- `collect_oceanx.py` 现在就会把 `preview_file` 当作图收集，并改写引用。只补一个收集测试，不另写一套扫描。
- `cache_cleanup._published_paths` 像保护已发布视图一样保护这些文件。

**回执**

- `static` 模式下，`receipt` 列出该节点的这些记录。
- `format_expert_receipt` 输出 `Saved figures (cite these paths):`，后面是每张图的绝对路径和标题。

**不暴露绘图接口**

`static` 模式下，下面每一处都换成不出现接口名的版本：

| 位置 | `static` 模式下的内容 |
|---|---|
| `runtime.py::OCEAN_EXPERT_WORKSTREAM_POLICY` | 最终图用 matplotlib 存成 PNG，放在 `OCEAN_OUTPUT_DIR`，这个文件就是交付物。在 `report.md` 里紧跟结论引用文件名。保留“图的科学表达由 Expert 负责”和“陆地、域外要掩膜”的规则，不出现接口名。 |
| `graphs.py::build` | 去掉这几处：`Result API reference` 一行、`ScientificFigure.save` 一句、`Figure API (...)` 整块、调色板一行、`[agent/result1]` 绑定段落、`.preview.png` 说明。加上存 PNG 的说明。 |
| `native_backend.py::task_backend` | 不写 `.runtime/result-api.md`。 |
| `tools.py` 里 `ocean_expert_run_code` 的描述 | 改为“最终图存为 PNG，放在 OCEAN_OUTPUT_DIR”。 |
| `COORDINATOR_VISUAL_DELIVERY_POLICY`、Coordinator 的两段后缀、`runtime.py` 里“只引用 Published results”的规则 | 回执的 Saved figures 里列出了图，就算交付。引用图时用那里列出的路径，不编造路径。 |
| `STANDARD_EXPERT_POLICY` | 去掉 `.preview.png` 那一句。 |
| skill `scientific-figure-design` | 不放进准备好的 skill 库（`prepare_skill_library`）。 |

kernel 启动代码和结果运行器里对 `ScientificFigure` 的 import 可以保留，模型看不到它们。

**补图规则的措辞（来自 A4 审核）**

写 `COORDINATOR_VISUAL_DELIVERY_POLICY` 的静态版本时，交互版和静态版的补图规则都按下面的要求写：

- 把“哪些图有资格补”直接写进条件句。现在的写法先说 “this follow-up”，下一句才讲补图，读到时还没有所指。
- 用 “the user explicitly asked for”，不用 “the original user question”。桌面版里 Coordinator 看得到整个对话，用户在后面的消息里才要图也算数。
- 参考写法：`If the Expert answered the scientific question but omitted a visual that the user explicitly asked for, you may make one and only one follow-up task call ...`，这段规则的后面接 `A visual that you added yourself in an Expert assignment does not qualify.`
- `test_visual_follow_up_requires_the_original_user_request` 的断言随之更新，仍然覆盖两种工作流和两种交付模式。交互模式的断言里，B 只允许改这一处。

**测试**

- `static` 模式下，Expert 和 Coordinator 的提示、工具描述、skill 库里都不出现这些字样：`ScientificFigure`、`Figure API`、`result-api`、`Published results`、`bracket`、`Workbench`、`.preview.png`。
- `outputs/` 下的 PNG 在 `static` 模式下被列为 `file` 结果，在交互模式下不列。
- 回执里列出它的路径。
- 收集器的测试夹具里，它出现在 “Collected figures” 下。
- `backend_environment` 和 `arm.json` 都带有这个模式。
- 交互模式原有的测试保持通过，不做改动。

### E. 文献咨询按需进行

- `runtime.py::OCEAN_EXPLORATION_POLICY`：把“开头就启动一次文献咨询”那句改成下面的意思。
  - 先做现有数据能回答的问题。
  - 只有当研究问题依赖某个定义、方法或已发表的机制，而数据说明里没有讲清楚时，才咨询 Search Expert。
  - 咨询与数据问题并行，不排在数据问题前面。
- `research_team_policy`：咨询是可选的，不再写“一次独立的 Search Expert 咨询”。
- `team/profiles.py` 里 Search Expert 的说明加上范围限制：
  - 咨询只读资料并汇报，不分析任务数据。
  - 资料有冲突，或者需要数值验证才能判断时，说明情况后停下，由 Coordinator 把验证派给数据 Expert。
  - 只有委派明确要求复现或下载数据时，才运行代码。
- Coordinator 的提示要保持在 `tests/test_oceanx/test_bounded_delivery_policy.py` 的长度限制（5,000 字符）以内，并更新该文件里对措辞的断言。

### D. 已保存数据的清单

- **目的**：重复尝试和子节点直接知道前面的节点存了什么，不用重新查看文件。
- **位置**：在 `ExpertCodeExecutionService` 上加一个方法。它在沙箱里以只读方式对某个 Agent 的 `outputs/` 和 `scratch/` 运行 `analysis_probe.py`，做法参照 `get_task_dataset_context`。
- **每个文件的内容**：
  - 数组文件：变量、各维度的名字和大小、`units`、`long_name`，以及文件的 `title` 或 `description`。
  - 表格文件：列名和行数。
  - `.npz` 文件：数组名、形状、类型，只读文件头。这部分要在探测脚本里新增。对象数组标注为“需要 `allow_pickle`”。
- **缓存**：存到 `<agent>/.runtime/data-index.json`，以所列文件的路径、大小、修改时间为键，有变化才重算。
- **进入提示**：
  - `graphs.py` 的 `_earlier_work` 和 `_earlier_attempt` 在每个目录路径后面加上清单。
  - 每个目录最多 12 个文件，先列 `outputs/`，再列 `scratch/` 里最新的。
  - 每个文件约 200 字符，总量约 4,000 字符，并注明省略了多少个文件。
  - 探测失败时只留目录路径，记一条日志，不阻止 Expert 启动。
- **规则**：在 `OCEAN_EXPERT_WORKSTREAM_POLICY` 里加一句：每个保存的变量写上 `units` 和 `long_name`，文件写一行 `title`。
- **测试**：
  - 探测脚本能描述同一目录里的 NetCDF、CSV 和 `.npz`。
  - 缓存被复用。
  - 提示里的清单不超过上面的限制。
  - 探测失败不影响 `build`。

**加固（v1.4，来自审核；不挡 D 的提交，和 C 的三处一起做）**

- 行数统计是探测里唯一和文件大小成正比的操作。实测 `csv.reader` 约 134 MB/s，也就是每 GB 约 7.4 秒；探测超时后不写缓存，之后每次 Expert 启动都会重试并再等一次。
- 超过 256 MB 的 CSV 不数行数：`rows` 省略，清单那一行写 `rows not counted`。列名照常给出。
- `_data_rows` 打开文件时加 `errors="replace"`。现在数据行里出现一个非 UTF-8 字节，整个文件就会被标成读不出来。
- 测试：一个超过上限的 CSV 不被逐行读取（把上限调小来测）；一个含非 UTF-8 字节的 CSV 仍然给出列名和行数。

**披露策略（v1.5，来自复核；提交前做）**

- **问题**：每个工作区有一份 `ModelDataDisclosurePolicy`，默认全部允许，桌面版可以把 `metadata` 设成 `deny` 或 `prompt`。设了之后，`OceanContextBuilder.build` 不再把数据集的变量、维度等放进提示。数据清单放进提示的是同一类信息（派生文件的变量名、维度、单位、标题、CSV 列名），但它没有查这份策略。
- **复现**：把工作区对当前服务商的 `metadata` 设成 `deny`，再构建 Expert 提示。上下文里已经没有 `dataset_context`，清单却还在，内容是 `outputs/mld.nc ("Annual MLD"): mld(time=12, lat=3) [m] ...`。
- **改法**：`graphs.build` 里，只有当 `OceanContextBuilder.policy_for(workspace_id, provider_id).decision_for("metadata")` 是 `allow` 时才调用 `_saved_data_prompt`。它和 `build` 后面构建上下文用的是同一份策略。不允许时连探测也不要跑。
- **不做**：不新增审计类别，不改策略本身，不改 `_earlier_work` 给出的目录路径（路径不是元数据）。
- **测试**：用真实后端夹具。策略为 `deny` 和 `prompt` 时，提示里没有清单块，并且 `describe_saved_data` 没有被调用；设回 `allow` 时清单出现。
- **影响范围**：benchmark 每次尝试都是新工作区，策略是默认的全部允许，所以 R3 的行为不变。受影响的只有桌面版里改过这项设置的工作区。

### C. 完整的绘图接口说明（交互模式）

- 提示、`.runtime/result-api.md` 和 skill 用同一份说明，这份说明由 `scientific_view.py` 生成。内容包括：
  - 构造函数；
  - 每种 `plot_kind` 及其限制；
  - `panel(...)`；
  - `ScientificPanel` 每个公开图层方法的准确签名，用 `inspect.signature` 取得；
  - 每种 `plot_kind` 一个可运行的例子；
  - 草稿规则（A3）。写成直接的用法：试验图用下划线开头的名字保存，最终图用普通名字。不写 “In interactive mode”，Expert 不知道有“模式”这个概念。
- 系统提示里只留简短规则和文件位置：“完整说明在 <路径>，画第一张图之前读一遍”。“完整”这个说法由下面的测试来保证。
- 测试：
  - 说明里列出了每个公开图层方法和每种 `plot_kind`。
  - 每个例子都能在临时的 `OCEAN_OUTPUT_DIR` 里运行并保存。
  - skill 里的例子同样能运行。

**审核后补充（v1.4）。C 提交之前做这三处。**

第 3 项的待确认标记保留为提案历史；Owner 本轮已明确批准，见最新 Log。

1. **说明要能被读完。** 生成的说明是 260 行、16,459 个字符。Expert 的 `read_file` 默认一次只读 100 行，OceanX 的读取器每次最多返回 12,000 个字符（`native_text.TEXT_PAGE_CHARS`）。实测：默认参数要读 3 次，第一次停在 `panel.reference`，里面没有 `scatter`、`vector`、各 `plot_kind` 的限制和任何例子；`limit=300` 要读 2 次。提示、skill 和说明开头现在写的都是 “once”。
   - 三处都改成“读到结尾”，写明行数（从生成的文本算出，不写死），并告诉 Expert 用 `limit=300`、按工具给出的 offset 继续读，直到没有剩余行。
   - 参考写法：`Before drawing your first figure, read the complete Figure API at the Result API reference path above to its end ({n} lines: call read_file with limit=300 and continue from the offset it reports until no lines remain).`
   - 不要为了一次读完去删内容，也不要改读取器的 12,000 字符上限。
2. **`fig.panel` 的关键字参数。** 说明里现在印的是 `panel(figure: ScientificFigure, *, panel_id: str, x, y, ...)`，这是 `ScientificPanel.__init__` 的签名。照着写会报 `TypeError`（实测）。改成只列 `fig.panel` 通过 `**kwargs` 接受的参数，也就是去掉 `figure`、`panel_id`、`x`、`y`，并把这一行放进 `fig.panel` 一节，不要放在 `fig.save` 后面。
3. **提示里留一行调用骨架（等 Owner 确认）。** HEAD 的提示里有 3 个内联例子，每个 Expert 都看得到。C 之后提示里只有文件位置，没读文件的 Expert 连 `fig.panel` 都得猜，比 HEAD 还差。在提示里加一行：`fig = ScientificFigure(plot_kind=..., title=...)`、`panel = fig.panel(x=..., y=...)`、图层方法的名字（从代码里取，11 个）、`fig.save('name.nc')`。大约 350 个字符，原来那一块约 1,500 个字符。只加在交互模式。

**这三处的测试**

- 用 `native_text.text_read` 按 `limit=300` 翻页：2 次读完，拼起来等于原文。说明以后变长到需要第 3 次时，这个测试要失败，提醒改提示里的读法。
- 提示里有行数和 `to its end`，没有 `once`；skill 和说明开头同样。
- 说明里不再出现 `panel(figure:`；说明里列出的每个关键字参数都能传给 `fig.panel(x=..., y=..., **参数)`。
- 提示里的骨架列出了每个公开图层方法；静态模式的提示里没有这一行（B 的隔离测试已经覆盖）。

**顺手改的措辞（同一次提交）**

- 时间轴：写清 `datetime64`、`datetime` 和 ISO 字符串都会自动成为时间轴（代码先把前两种转成 ISO 字符串），`x_scale='time'` 只是显式声明。现在的写法让人以为 `datetime64` 必须加 `x_scale='time'`，而例子里并没有加。
- `add_feature`：“lines and polygons are split at the antimeridian” 读起来像是代码会自动拆。实际是跨越的线和多边形会被拒绝，要调用者自己拆。
- `ScientificFigure` 的 `source_handle`、`conclusions`、`spatial_context` 各补半句说明，现在只出现在签名里。
- 生成器取图层说明时用 `.get`。完整性由测试保证；运行时不应该因为新加的方法漏写说明，就让所有 Expert 启动失败（现在会抛 `KeyError`）。
- README 里 A4 那句 “explicitly requested in the original user question” 改成和提示一致的 “the user explicitly asked for”。

### F. 记录与披露（不改行为）

- `evaluation/evaluate.py::code_failures` 的说明改成只描述类别，不归因：只读拒绝可能是沙箱在正确地保护其他节点的文件，超时可能是代码本身慢。
- `RUNNING.md` 和 `EVALUATION.md` 写明四点：
  - OceanX 的 benchmark 运行只保存普通 PNG 图，不暴露绘图接口。
  - Expert 的最后一次调用可能多发一次请求；上下文压缩请求单独计数。两者都记在账本里。
  - 研究预算是运行设置，会改变 Coordinator 的行为。
  - Finch 没有文献搜索；Claude 取决于它的工具配置；OceanX 按需咨询。

### G. 大文件编辑路径缺少导入（v1.4 新增，Owner 已确认）

- **问题**：`native_backend.py` 的 `OceanSandbox._aedit_via_upload` 在三个出口都构造 `EditResult`，包括成功的那一个，但模块没有导入它。
- **什么时候触发**：deepagents 在一次 `edit_file` 的 `old_string` 加 `new_string` 超过 50,000 字节时走这条路径（`_EDIT_INLINE_MAX_BYTES`）。Expert 和 Coordinator 都用这个后端。
- **后果（已复现）**：60,008 字节的编辑**已经写进磁盘**，然后抛 `NameError: name 'EditResult' is not defined`。LangGraph 默认的工具错误处理只接住参数错误，其他异常会继续向上抛，所以这不是一条模型能看到并重试的错误消息。
- **范围**：HEAD 里就有，r1、r2 用的提交里也有。不是 A 到 F 引入的，现有测试都没走到这条路径。
- **改法**：在 `from deepagents.backends.protocol import (...)` 里加上 `EditResult`。不改编辑算法，不改 deepagents。
- **测试**：用真实沙箱做一次超过 50,000 字节的编辑，断言返回 `EditResult`、`occurrences == 1`、文件内容已替换；再测 `old_string` 不存在时返回带 `error` 的结果，而不是抛异常。
- **为什么建议在 R3 之前修**：触发的概率低，但一旦触发，三小时的运行可能在写大报告时失败。改动只有一行。

## 7. R3：怎么跑、看什么、出了异常怎么办

R3 只在 A 到 G 全部提交、通过 Claude 审核，并且 Owner 通知之后才跑。
它带着 B、E 这些行为变化，所以和 r1、r2 不是严格的 A/B 对比，报告里要写明这一点。

### 7.1 已有的提交和基准

| 提交 | 内容 |
|---|---|
| `8df7791` | 可写目录里的只读路径不再生效；Linux 上 kernel 能启动；kernel 的输出写进 `kernel/kernel.log`。 |
| `e9f490e` | kernel 测试改用解析后的解释器路径。 |
| `6cbd4f0` | 每个研究节点一个目录和一个 kernel；kernel 在每次尝试结束时关闭；Expert 被告知上级节点和依赖节点的目录。 |
| `88cab8b` | 第 60 次调用直接写报告，输出是工具乱码时重试一次；没写报告时把结束语存为报告；重复尝试被指向之前的报告和文件；回执显示已用时间，预算用到 75% 后不再开新委派；开跑前检查 kernel；运行记录给出失败分类。 |

| | r1（`f82bc4a`） | r2（`6cbd4f0`） |
|---|---|---|
| 观察时刻 | 约 70 分钟 | 约 66.6 分钟，当时仍在运行 |
| 模型调用 | 581 次，83% 的时间有调用在跑 | 440 次，72% |
| 代码执行 | 326 次，61 次失败，其中 34 次是 kernel 启动失败、1 次超时。之后扫描到 355 次：321 次是 shell，kernel 没有一次成功。 | 215 次：194 次成功、20 次失败、1 次超时；44 次用 kernel，171 次用 shell。 |
| 只读错误 | 32 行，其中 26 行在自己的 `outputs` | 0 |
| Agent 目录 | 整棵树只有 3 个 | 每个节点各一个 |
| 交付问题 | B1.3.1 尝试了 3 次；B1.4.1.1 用满 60 次调用，没有报告。 | B1.3.1.1.1 第一次尝试没绑定到节点，被重派；B1.3.1.1 的补图用了 54 次请求、约 6.4 分钟。 |
| 其他 | | 文献咨询约 17.8 分钟、53 次请求，其中两次执行等待共约 9 分 40 秒；研究树深 5 层。 |

这些都是运行中途的快照。完整数字以 inventory 重新生成的 `run_record` 为准。

### 7.2 运行步骤

在 Linux 服务器上做，环境是 `oceanx-bench`，目录是 `/home/mafzhang/code/OceanX`。

1. pull，确认 `git log -1` 是 Owner 指定的提交。
2. 开跑前检查，必须输出 `"environment_ready": true`：

   ```bash
   python benchmarking/server/check_setup.py --agent oceanx
   ```

3. 跑只在 Linux 上执行的测试，macOS 会跳过它们，所以必须在这里通过。后三个文件（数据清单、静态交付、大文件编辑）在 macOS 上跑过，但它们用到沙箱，Linux 上还没跑过：

   **2026-10-05 更新：**Owner 已批准修正两个旧沙箱测试的 Linux 检查方式；不改沙箱权限。它们不再作为已知失败豁免，以下测试必须全部通过。历史诊断与本次验证见 Log。

   ```bash
   PYTHONPATH=src python -m pytest tests/test_sandbox tests/test_oceanx/test_persistent_kernels.py tests/test_oceanx/test_sandbox_self_check.py tests/test_oceanx/test_saved_data_index.py tests/test_oceanx/test_static_figure_delivery.py tests/test_oceanx/test_native_large_edit.py -q -p no:cacheprovider
   ```

4. 在 `benchmarking/.env` 里只改下面这些，其他设置和 r1、r2 保持一致：
   - `BENCH_EXPERIMENT=methods-oceanx-flash-r3`
   - `BENCH_SUITE=evolution`、`BENCH_EVOLUTION_SET=`、`BENCH_TASKS=E10`
   - `BENCH_MODEL=deepseek-flash`、`BENCH_TIMEOUT_SECONDS=10800`
   - `BENCH_OCEANX_MAX_PARALLEL_EXPERTS=2`、`BENCH_RESUME=false`

   然后在 tmux 里运行 `python benchmarking/server/run_oceanx.py`。
5. 核对 `inputs/queries.jsonl` 里 E10 的问题文字和数据集与 r1、r2 相同。不同就不能对比：报告这一点，然后停下。
6. 给 r1、r2、r3 各生成一次运行记录，把命令里的 `r3` 换成对应的名字：

   ```bash
   python benchmarking/evaluation/evaluate.py inventory --runs /import/home3/share/oceanx-bench/methods-oceanx-flash-r3/runs/OceanX --out /import/home3/share/oceanx-bench/methods-oceanx-flash-r3/eval/inventory
   ```

7. 数一下 r3 里 kernel 和 shell 各执行了几次、有多少个 Agent 目录（只读）：

   ```bash
   python - /import/home3/share/oceanx-bench/methods-oceanx-flash-r3/runs/OceanX <<'EOF'
   import sys
   from pathlib import Path
   root = Path(sys.argv[1])
   runs = [p for p in root.glob("*/attempt-*/workspace/*/*/agents/*/.runtime/executions/*") if p.is_dir()]
   shell = sum((p / "code" / "command.sh").is_file() for p in runs)
   agents = {p.parents[2] for p in runs}
   folders = [p for p in root.glob("*/attempt-*/workspace/*/*/agents/*") if p.name != "coordinator"]
   logs = [p for p in root.glob("*/attempt-*/workspace/*/*/agents/*/kernel/kernel.log") if p.stat().st_size]
   print(f"code runs {len(runs)}: kernel {len(runs) - shell}, shell {shell}; "
         f"agents with code {len(agents)}; agent folders {len(folders)}; non-empty kernel logs {len(logs)}")
   EOF
   ```

### 7.3 检查表

把 r1、r2、r3 的 `run_record.md` 放在一起看。

| # | 检查项 | 合格线 |
|---|---|---|
| 1 | 开跑前检查和 Linux 测试 | 除两个已知的旧测试外全部通过（见第 7.2 节第 3 步的说明） |
| 2 | kernel 启动失败 | 0 |
| 3 | 指向自己目录的只读失败 | 0 |
| 4 | 没有报告的尝试（所有节点合计） | 0 |
| 5 | 未绑定的尝试：Expert 的模型调用里 `node_id` 为空，文献咨询除外 | 0 |
| 6 | 报告被更短的结束语替换 | 0 |
| 7 | 同一节点的最多尝试次数 | 不超过 2 |
| 8 | 状态为 `completed`，有最终报告和 `answer.md` | 是 |
| 9 | 总时长 | 少于 180 分钟；约 135 分钟之后没有新委派 |
| 10 | Agent 目录和研究树节点 | 每个节点和角色一个目录，没有两个节点共用 |
| 11 | 图 | `arm.json` 里 `figure_delivery` 是 `static`。报告：回执的 `Saved figures` 和收集结果里各列出了哪些图；有没有图只存在 `scratch/` 而没进 `outputs/`；有没有补图任务，用户的问题是否明确要了这张图 |
| 12 | 文献咨询 | 报告：有没有发生；如果有，它的耗时和调用数、数据任务等了它多久、Search Expert 有没有对任务数据运行代码 |
| 13 | 重复尝试和子节点 | 报告：第一次分析执行之前用了多少次模型调用，与 r2 对比 |
| 14 | 第 60 次调用 | 报告：有没有结束语被存为报告，有没有触发纯文本重试 |
| 15 | 最长的串行链 | 报告：深度和每层的耗时 |
| 16 | 代码失败 | 报告：“代码”类失败占全部执行的比例；kernel 和 shell 各多少次 |
| 17 | 总时长和模型调用数 | 报告：与 r1、r2 对比 |
| 18 | 数据清单 | `backend.log` 里 `Could not describe the saved data` 出现 0 次。报告：多少个 Agent 目录生成了 `.runtime/data-index.json` |

### 7.4 出了异常先看哪里

以下情况都只报告，不改代码。把证据写进 Log，由 Claude 决定怎么改。

| 现象 | 先看哪里 |
|---|---|
| 开跑前检查或 Linux 测试失败 | 错误信息里带着 kernel 自己的输出。`bwrap: execvp ... No such file or directory` 说明解释器路径没有被挂载；`Parent appears to have exited` 说明 kernel 又拿到了父进程号；`Read-only file system` 说明只读规则退回了旧行为。这时不要开跑。 |
| kernel 启动失败 | `code_executions.result_json` 里的 `error`，以及该 Agent 的 `kernel/kernel.log`。 |
| 只读失败 | stderr 里的路径。路径在自己的目录内，是代码退回了旧行为；在别的 Agent 目录或数据目录里，是设计如此，只需报告次数和节点。 |
| 有尝试没交报告 | 回执的 `Result:` 一行、第 60 次调用的原始回复、`backend.log` 里的模型服务错误。 |
| 同一节点尝试 3 次以上 | 每次回执的 `Result:` 一行。分清是 Coordinator 认为科学上还不完整，还是失败之后的重试。 |
| 超时、没有最终报告，或预算停止后仍有委派 | 运行 `grep -a -o "Research status: [^\"]*" -r <attempt>/state \| tail` 看预算有没有传到。再看有没有出现 `Not started: most of the research time budget`。 |
| 两个节点共用目录，或很多委派没绑定 | 研究树事件里 `binding` 为 `inferred` 和 `unbound` 的数量，以及显式 `node_id` 被拒绝的次数。 |
| 数据清单探测失败 | `backend.log` 里 `Could not describe the saved data` 后面的原因，以及该 Agent 目录的 `.runtime/data-index-probe/`。清单只是提示，Expert 仍会启动，所以只报告次数和原因。 |
| 代码失败多 | 按类型分组：形状或广播、名字或键、import、其他，每类举两个例子。不要手写 skill、lesson 或工具，这些由 meta-agent 负责。 |

### 7.5 报告格式

在 Log 里写三部分：

1. 检查表，r1、r2、r3 并排。
2. 遇到的每个异常和它的证据：路径、计数、简短摘录。
3. 留给 Claude 的未决问题。

测量之前不对速度提升下结论。全部合格也不要自行启动正式运行、调整并发或推理设置。

## 8. Log

Codex 在这里追加记录，最新的放在最上面。每条写：日期、做了哪个包或遇到什么情况、证据、改动、测试结果。

### 2026-10-05 — Owner 批准修正两个旧沙箱测试，并提交 origin、同步服务器（Codex）

- **范围：**只改两个测试及本文件。不修改分析代码、沙箱权限、研究策略或 benchmark 结果，不中断正在运行的任务。
- **修改前证据：**服务器 `0b5d58f` 上两项定向测试均失败。取消测试记录的是沙箱内部 PID `2`，宿主机的同号进程是 `kthreadd`；文件测试成功写入的是未挂载的 `secret.txt` 路径，宿主机的原始秘密文件和只读输入都未改变。
- **取消测试：**记录真正启动目标脚本的宿主机 launcher，先确认其进程组存在，取消后确认整个进程组消失且 launcher 已退出。不捕获 `PermissionError` 来伪装通过，不用沙箱内部 PID 检查宿主机；断言失败时也取消测试任务。
- **文件测试：**先验证宿主机秘密文件不可读，仍要求只读输入不可写；未挂载路径若能创建沙箱私有临时文件，验证读到的是新内容，并在宿主机再次断言两个原文件未变。保留网络、fork、环境秘密、asyncio 和输出目录检查。
- **本机验证：**两个相关文件 **79 passed、3 skipped**；最终完整套件 **1111 passed、8 skipped，176.22 秒**（`/private/tmp/oceanx-sandbox-test-fix-local-final.log`）。首次本机验证发现 macOS 的解释器探测也会启动进程，记录器现按目标脚本过滤，不把环境探测当成被取消的任务。
- **服务器验证：**更新测试先复制到 `/tmp/oceanx-sandbox-tests-2DcDVGXr`，不覆盖项目代码；两个文件 **81 passed、1 skipped**。全量初跑使用绝对 Python 路径但未同步设置 PATH，四项模拟图片子进程误用系统 Python、报 `PIL` 缺失；真实沙箱图片测试和两个修正测试通过。设置 `oceanx-bench/bin` 为 PATH 首项后，最终全量 **1115 passed、4 skipped，203.54 秒**（`/tmp/oceanx-sandbox-test-fix-server-final.log`）。全量使用原 checkout 的生产代码及临时目录里的两份更新测试；原两文件被替换而非跳过，测试总数与本机均为 1119。
- **静态检查：**`git diff --check` 通过。两个文件的 Ruff 提示与 HEAD 相同（两条旧类型提示、一条旧 import 排序提示），本次没有扩大范围处理。
- **交付范围：**Owner 明确授权本次三文件提交、推送 origin 并在服务器 `git pull --ff-only`。工作区修改不含任何生产源码或结果文件；测试的旧失败豁免已撤销。

### 2026-10-04 — 后台委派：Coordinator 不再等一批里最慢的 Expert；并行数成为设置（Claude，待提交）

**Owner 的要求和规则。** “实现 task 的异步，避免同一委派要等最后一个完成才继续”；“并行几个 expert 应该写在 config 里，比如 benchmarking/.env 还有桌面端前端里面”；
规则由 Owner 给出：想开一个需要几条已派出结果共同决定的新子问题，就得等；是某条委派自己的后续，就直接委派；这由 Coordinator 决定。

**为什么以前要等。** LangGraph 把一条模型回复里的每个工具调用作为同一步里的任务，这一步所有任务都结束才会再调用模型；DeepAgents 的 `task` 又是等子代理结束才返回。
所以一批 Expert 只能一起交还（Q08：B1.3 在 14 分钟返回，它的后续到 41.8 分钟才启动）。DeepAgents 自带的异步子代理是把 Expert 放到另外的服务端运行里再轮询，
会打断现在单次运行的事件流、取消和检查点结构，没有采用。

**做法（`src/oceanx/research/background_experts.py`）。**

- `task` 调用在 Coordinator 这次运行里把原生 `task` 作为后台作业启动（原生工具原样执行，所以它自己的开始、结束事件、回执、研究树绑定、检查点都不变），
  然后等到“下一个 Expert 结束”就返回：自己的 Expert 已结束就返回原来的回执；还没结束就返回一句“Started: B1.5 (...) is working in the background ...”。
- 自己的调用已经返回、之后才结束的 Expert，回执由后面的 `task` 或 `await_experts` 结果带回（标明 `Receipt of B1.5 (...)`），每份回执只交付一次。
  一次交付不超过 12,000 字符（DeepAgents 会把超过 16,000 字符的工具结果挪到文件里），放不下的留给下一次并提示还有几份。
- 新工具 `await_experts`：不带参数等下一个 Expert；`node_ids` 等指定节点都返回；`wait_for_all` 等全部。
- Coordinator 的回复如果要结束而还有 Expert 没返回或回执没交付，会被接上一次 `await_experts`，不能提前结束。
- 同一个角色、同一个节点的 Expert 还在跑时，再次委派会被拒绝（两个 Expert 会共用同一个目录和 kernel）。这是后台化带来的新情况，以前 Coordinator 在 Expert 运行期间不会被调用。
- 预算检查、节点绑定和原生工具都在后台作业里执行，所以被拒绝的委派（预算用完、节点不存在、无需求的补图）立刻返回，不拖住同一轮的其他委派。
- 运行失败或被取消时，`coordinate` 节点的 `finally` 会停掉仍在跑的 Expert。Expert 失败仍像以前一样让整次运行失败（在取回它的那次调用里抛出）。
- Coordinator 的规则写进提示（研究模式和标准模式都有）：回执到达时其他 Expert 还在跑，由它决定——这条线自己的后续马上委派；需要几条结果共同决定的新问题，用 `await_experts` 等齐。
  研究树规则里的“After each report batch consider …”改成了“As reports return consider …”，因为结果现在是一份一份到的（Coordinator 提示组合后 4,978 字符）。
  `task` 工具说明里也写明“返回时自己的参与者可能还在工作”。
- 桌面事件：一个 `task` 的结束事件现在可能出现在后面的回合里，它仍归属发起它的那个回合（`deep_runtime.py`）。

**并行数。** 空位池改为可调（`graphs._Slots`）。benchmark：`.env` 的 `BENCH_OCEANX_MAX_PARALLEL_EXPERTS`（现为 3）和 `BENCH_OCEANX_MAX_PARALLEL_SEARCH_EXPERTS`（1），不变。
桌面端：设置对话框“研究运行时”里新增“同时工作的数据专家”（1 到 4，默认 2，存在本机），随每次 `session.submit` 的 `max_parallel_experts`（1 到 8）发送，
每次 Coordinator 运行开始时用它设定全应用的空位池；搜索专家仍是独立的 1 个名额。协议文件已重新生成。

**顺带更正。** v1.10 我写“Coordinator 和所有 Expert 都装了工具调用修复”，其实标准模式的 Coordinator 没有装；这次补上了。

**验证（都在 Mac 上，没有真实模型）**

- 先在真实的库上做了实验：工具调用提前返回、嵌套图在后台继续，事件、嵌套检查点、最终状态都正常，运行结束后没有残留任务。
- 新增单元测试 22 项（单个委派原样返回、一批里第一个返回就继续、后续在兄弟节点还在跑时启动、忙时到达的回执随下一次调用带回、等指定节点或全部、不能提前结束、
  失败照旧让运行失败且只抛一次、拒绝不拖住其他委派、重复委派被拒绝、每份回执只交付一次、交付大小、关闭时取消等），重复运行 25 次稳定。写完后重读代码又发现并修了一处会卡死的情况（读不到所属回合的调用互相顶掉唤醒），有测试。
- 真实 Agent Server 加假模型的端到端测试 3 项：两个 Expert 一快一慢，研究模式和标准模式各一次，事件顺序是 B1 结束、Coordinator 的等待开始、B2 结束（带自己的回执）、等待结束，
  团队快照出现过“一个完成、一个工作中”；桌面端发送的 `max_parallel_experts=3` 到达了空位池；在 Coordinator 等待慢 Expert 时取消，5 秒内结束，慢 Expert 的模型调用确实被取消，日志无残留任务报错。
- 21 个变异检查（把每个行为改回去）全部被测试抓到；有两个最初没抓干净（一个回执被同一轮的另一个调用拿走、一个结束的 Expert 不释放空位只会让旧测试卡住），已补测试并给相关测试加了超时。
- Python 全量：**1111 passed、8 skipped、0 failed**（上一条是 1070）。桌面端：vitest **41 个文件、227 项通过**，三处 TypeScript 类型检查无错误，ESLint 只有以前就有的那一条。改动文件的 Ruff 结果与 HEAD 相同（33 条旧的，没有新增）；`git diff --check` 通过。

**没有验证、需要真实运行确认**

- 真实模型会不会按规则使用：收到第一份回执后是继续这条线还是等，会不会恰当地调用 `await_experts`。省多少时间也没有测：按 Q08 的节点用时模拟，
  “父节点一返回就启动、3 个空位”是 54.8 分钟（实际 87 分钟），这是上限，取决于 Coordinator 怎么决定。
- Coordinator 会被调用得更多（每个 Expert 返回一次，而不是每批一次），它自己的调用次数和 token 会增加。
- 3 个数据 Expert 同时跑的内存和 CPU。
- 桌面端的设置控件只做了渲染测试和类型检查，没有在运行中的应用里看过。
- Linux 上的全量测试。

**已知限制**

- 桌面端取消请求后，对话里会留下“还在后台工作”的那条工具结果，而 Expert 已随取消停止；下一次请求里没有 Expert 在跑，`await_experts` 会回答没有。
- 服务端进程重启后不能续跑后台的 Expert（以前也不支持中途续跑）。
- 这次之前的运行每批都等最慢的 Expert，用时不能和之后的运行直接比较。


### 2026-10-04 — Q08 为什么仍用 87 分钟；数据 Expert 空位由 2 改到 3（Claude，待提交）

Owner 同意空位改 3，并问为什么仍然这么耗时。以下是对上限 40 的 Q08（`/Users/ryanzhang/tmp2`）的只读分析，另用 16 个节点的实际用时做了一个调度模拟
（按原样模拟得 88.2 分钟，实际 87.1 分钟）。只有这一次运行，节点用时本身有波动。

**87 分钟的构成**

| 部分 | 分钟 | 说明 |
|---|---|---|
| 最长依赖链 | 51 | 即使资源不限、没有任何等待，B1.1 到 B1.4 到 B1.4.1 到 B1.4.1.1 到 B1.4.1.1.1 再加最终答案也要 51 分钟；每一环是一个完整的 Expert 调查，5 到 22 分钟 |
| Coordinator 分批启动 | 约 25 | 一个回合里的多个 `task` 同时跑，下一个回合要等全部返回；例如 B1.3 在 14.0 分钟返回，它的后续 B1.3.1（最长的节点，22 分钟）却要等到 B1.8 在 40.8 分钟返回后才在 41.8 分钟启动，多等了 28 分钟 |
| 数据空位等待 | 约 9 | 第 2、3 阶段各同时委派 3 个数据节点，只有 2 个空位，B1.5 等了 5.9 分钟，B1.8 等了 10.4 分钟 |
| 其他 | 约 2 | Coordinator 读结果和委派的间隔 |

模拟（用实际节点用时）：按原样（分批、2 空位）88.2 分钟；分批、3 空位 79.4；分批、空位不限 79.4；每个节点在父节点返回后立即启动：2 空位 70.9，3 空位 54.8，空位不限 51.2。
所以空位 2 改 3 约省 9 分钟（与之对应，再多空位也没有用，因为分批是瓶颈）；再取消分批约省 25 分钟，合计 87 降到约 55 分钟。

**依赖链各条的长度（含最终答案）：** B1.4 一支 51.2（B1.4.1 起是 Coordinator 自己授权获取 WOA18 和 Argo 的三个节点，v1.10 起不会再有）；B1.8 一支 47.8；B1.3 一支 39.2；B1.6 一支 33.4；B1.7 20.3；B1.5 16.8；B1.2 6.6。
去掉外部数据那一支后，这棵树的下限约 48 分钟。

**一个节点内部的时间（574 次 Expert 模型调用，共 95 分钟，平均 10 秒，中位 5.2 秒）：** 每次调用平均写 2,062 个输出 token，其中 1,123 个（54%）是推理；每 1,000 个输出 token 约 4.5 秒，
所以约 94% 的模型时间是在写输出，等待和读提示只占 6%（提示缓存命中约 80%）。时间集中在少数长调用：最慢的 5%（29 次，每次超过 30 秒）占 24%（22.5 分钟）；
只有 4 次超过 60 秒（共 7.4 分钟，推理占 93%），其中 1 次写满 32,768 个 token（147 秒）。把每次调用的输出限制到 8,192 个 token 最多省约 5.7 分钟（6%），还可能截断正常的长脚本，不值得。
代码另有 49 分钟（其中 44% 是失败或超时的长运行）。

**修改：** `.env.example` 和 `RUN_DEFAULTS` 里 `BENCH_OCEANX_MAX_PARALLEL_EXPERTS` 由 2 改为 3（桌面端不设置时仍是 2，`arm.json` 已记录该值）。
新增 4 项测试（模板写明 3、默认 3、`.env` 里的值传到后端、0 被拒绝），3 个变异检查全部被抓到。**没有验证：** 3 个数据 Expert 同时跑时服务器的内存和 CPU；第一次用这个设置时请留意内存。

**待 Owner 决定：** 取消分批需要让 Coordinator 的委派变成异步：`task` 立刻返回，Expert 在后台跑，哪个先返回就先把它的后续接上。现在的原生 `task` 是同步的，所以这是较大的改动
（预计再省约 25 分钟，Q08 87 降到约 55 分钟）。较小的办法是让 Expert 在同一次委派里把自己这一支继续做下去，上限 60 时它们就是这样做的，所以上限 40 的节点更短、层数更多、分批的损失更多。


### 2026-10-04 — Q08 两版的暂定审阅分，以及最终答案没吸收修正的原因和修改（Claude，待提交）

**Owner 的暂定审阅分（评分标准 `tasks/Q08/evaluator/rubric.json` 仍是草稿，参考结果及容差未冻结，不是正式得分；一对运行，差距在波动范围内，不能据此认为减少轮次提高了质量）：**
上限 40（`benchmarking_oceanx_40`）76.25，上限 60（`benchmarking_oceanx`）72.50。效率对照：用时 87 分 11 秒对 79 分 20 秒，Expert 尝试 16 对 12，模型调用 605 对 653，
token 4,235 万对 5,189 万（少 18.4%，用时多 9.9%）。40 次版的主要扣分：（1）最终答案没吸收最后一个速度子报告对陆地、浅水掩码的修正，第一阶段平均流速 0.879 应为 0.778 m/s，答案仍写 0.88；
（2）把温度差异归因于论文的背景参考水，但没有恢复论文的具体参考样本，过于确定；（3）把 Argo 称为独立验证，没有证明它们未参与再分析同化。

**第（1）项的原因（我从下载的运行里查明）：** Coordinator 写最终答案前只读了一次树视图（`view='full'`），没有打开任何 Expert 报告。树视图把每个节点的 Result 截成 320 字符，
Evidence and limitations 只留第一句（160 字符），而这条修正在 B1.8.1.1.1 的 5,168 字符摘要的限制部分深处（“moves the S1 window mean from 0.879 to 0.778 m s⁻¹”），视图里根本没有；
父节点 B1.8.1.1 的 Result 里的 0.88 倒是在视图里。上一轮加的“Reconcile every returned node's latest Result and Evidence and limitations”因此无法照做。

**修改**

1. `update_research_tree` 新增 `view='results'`：列出每个已返回节点完整的 Result 和 Evidence and limitations（按树的顺序），`view='full'` 不变，所以最终报告的 Research Tree 小节照旧。
2. Coordinator 的最终综合规则：先读 `view='full'` 写 Research Tree 小节，再读 `view='results'`；修正过的节点取代旧值并说明已修正；两个节点冲突或摘要不够时打开报告；
   结论不比证据更强，没有分离出原因就写 consistent with，只有证据表明独立才称独立。
3. Expert 摘要规则：修改了前面节点的数字或结论时，Result 以 `Corrects B1.x: <quantity> from X to Y` 开头；Evidence and limitations 的第一句写最影响结果的那条限制（Coordinator 只看得到这一句和 Result 的前 320 字符）。

**验证（Mac）：** 先写测试并确认失败；新增 5 项测试（视图截断与完整、顺序和只列已返回节点、工具暂存的取值、Coordinator 规则、Expert 规则），6 个变异检查全部被抓到。**没有验证：** 真实模型会不会照做。
这些只是让信息可见并写明规则，模型仍可能忽略；下一次 Q08 跑完后看最终答案是否用了修正后的值。

**待 Owner 决定的一点：外部数据。** 审阅分把 Argo、WOA 对照记为 40 次版的优点，但这两项数据是 Coordinator 自己授权下载的，题目只给 GLORYS12，并且判定里有“not testable with the supplied data”这一类。
v1.10 起提示里只有用户自己的话才能授权获取数据，以后的运行不会再下载它们。所以：上限 40 对上限 60 的分差里有一部分来自外部数据，下一批（没有外部数据）的分数不能直接和这两个版本比。
如果基准允许在题目要求解释与观测的差异时用公开观测数据，需要明确写进题目或规则，而不是让 Coordinator 自己授权。


### 2026-10-04 — 上限 40 的第一次测试：Q07 没跑起来，Q08 用时没有缩短，并发现一处授权漏洞（Claude，待提交）

Owner 把 Q07、Q08 在上限 40 下的结果下载到 `/Users/ryanzhang/tmp2`（提交 `77eb1b6`，`arm.json` 里 `expert_call_limit` 为 40）。以下都是只读分析。

**Q07：21 秒就失败，没有数据。** Coordinator 第 3 次调用发出的 `update_research_tree` 参数是 `{"changes": [], "view": "full"}}`（多一个 `}`），
LangChain 把它记成无效工具调用，没有任何可执行的调用，循环结束，请求以“OceanX stopped without a user-facing conclusion”失败。这和上限无关，也与预算提示无关（Expert 还没启动）。
Q08 的 605 次调用里没有无效工具调用。

**Q08（上限 40）与此前上限 60 的那次（Codex 的数字）：**

| | 上限 60 | 上限 40 |
|---|---|---|
| 用时 | 79.3 分钟 | 87.2 分钟 |
| Expert 委派 | 12 | 16 |
| 模型调用 | 653 | 605（含 12 次摘要） |
| token | 约 5,189 万 | 约 4,230 万（输入 4,100 万，其中缓存 3,280 万；输出 133 万） |

只有一对运行，运行间本来就有波动，所以只能说：**上限降到 40 没有缩短用时，总工作量被分摊到更多节点上**，token 少了约 18%。

- **Expert 会按预算调整工作量。** 16 个 Expert 用了 29 到 40 次调用（中位 36），15 个自己结束，只有 1 个用满；报告里 95% 的数字在第 31 次调用（中位）已经出现，
  而上限 60 时（R3）是第 48 次左右，比例几乎一样。它们读了预算提示：331 处与预算相关的文字，例如“Careful with call budget: 35 calls left, 28 for analysis”。
- **第一份报告几乎都是检查点逼出来的。** 16 个里 15 个的第一次写报告在第 22 次调用（检查点在第 21 次），没有自己提前写的；16 个都交了报告，没有“没写报告”的情况。
- **预算偏紧会留下未完成的东西，再由新节点接上。** B1.8 的报告写着“corrected recomputation was cut off by the call budget”，B1.8 这一支接着有 B1.8.1、B1.8.1.1、B1.8.1.1.1 共四层。
- **关键路径上的时间构成（87 分钟）：** 模型调用约 50%，代码约 23%，并发空位等待约 19%（第 2、3 阶段各有 3 个数据节点同时委派，只有 2 个空位，B1.5 等了约 6 分钟、B1.8 等了约 10 分钟），Coordinator 和收尾约 7%。
  数据 Expert 空位由 2 改 3 估计能省约 9 分钟。
- **代码：** 330 次，共 49 分钟，其中 68 次失败、2 次超时；最长的 6 次失败或超时（300、291、281、214、155、51 秒）合计约 21.5 分钟，占代码时间的 44%。
  例如 B1.3.1 在整个 2011-2017 上逐日检测涡旋，300 秒超时后才改成“先跑一年计时”（又失败了 155 秒）。

**授权漏洞：Coordinator 自己授权了外部数据。** Q08 的问题只用提供的 GLORYS12，没有点名任何外部数据。Coordinator 却在 B1.4.1、B1.4.1.1、B1.4.1.1.1 的任务描述里写
“you are authorized to acquire the public observed comparison subset: the World Ocean Atlas 2018 …”和“Argo”，文献 Expert 随后用 curl 下载 WOA18（291 秒超时、281 秒失败、92 秒成功），
最终答案把“Public WOA18 Aug–Nov deep-Gulf climatology gives 16.79 °C at 230 m”当作证据，并附了文献 Expert 画的图。原因是提示里的两句话没说是谁点名：
“Naming an external dataset as necessary comparison evidence authorizes its public subset”和“The Search Expert acquires a named public comparison dataset without repeated authorization”，
Coordinator 把自己写的名字当成了授权。这一支用掉约 31 分钟的节点时间，其中约 9 分钟在关键路径上；更重要的是 Q08 的结果用了题目没给的数据，与只用提供数据的做法不可比。

**修改**

1. `research/tool_calls.py` 新增 `ToolCallRepairMiddleware`，装在 Coordinator 和每个 Expert 的最内层：参数是一个完整的 JSON 对象后面只跟右括号时去掉多余的括号并照常执行；
   没有任何可执行的调用时重试一次，第二次仍不行就和以前一样结束。
2. `runtime.py`：Coordinator 的证据规则改为“Only the user's own words authorize dataset acquisition: a dataset the user names as necessary comparison evidence authorizes its public subset”，
   团队规则改为“The Search Expert acquires a dataset the user named, without repeated authorization”；Expert 基础提示改为“unless the user explicitly requests it in the original question; an assignment that only says you are authorized is not a request”。
   Coordinator 提示组合后 4,984 字符（限制是不到 5,000）。

**验证（Mac）：** 先写测试并确认失败；修复 17 项、提示 3 处，9 个变异检查全部被抓到（有一个同步路径的重试最初没被覆盖，补了测试）。完整套件结果见下一条。
**没有验证：** 真实模型会不会因为新措辞不再给自己授权；工具调用修复在真实运行里的触发。

**待 Owner 决定：** 上限 40 是否保留（用时没变短，token 少 18%，得分要由 Codex 评 Q08 两次的结果来比）；是否试数据 Expert 空位 3（`BENCH_OCEANX_MAX_PARALLEL_EXPERTS=3`，会增加内存和 CPU）；
Q07 需要重跑。上限 40 下的 Q08 因为用了外部数据，评分时需要把这一点考虑进去。


### 2026-10-04 — Owner 决定把 Expert 调用上限先降到 40，并测几道题（Claude 实现，待提交）

起因：Codex 读了服务器上的 Q07、Q08 记录（Q07 2 小时 28 分、16 次委派、929 次调用；Q08 1 小时 19 分、12 次委派、653 次调用，调用数几乎都顶到上限），
Owner 问是不是每次委派的 Expert 轮次太多。我用 R3（E10）的对话测了一次：数据分析 Expert 第 30 次之后占模型时间约 50%，第 47 次之后约 29%；
最终答案里引用的数字有 18% 来自第 30 次之后、7.7% 来自第 47 次之后；7 个数据分析 Expert 里有 5 个直到第 46 次之后才算出报告里 95% 的数字。
这只是一次运行、一道题，数字不等于评分，所以要用评分来验证。Owner 决定先把上限改成 40，自己测几道题。

- **改动：** `graphs.py` 的 Expert 模型调用上限由写死的 60 改为读环境变量 `OCEANX_EXPERT_CALL_LIMIT`（不设置就是 60，不低于 10）；
  报告检查点和收尾阶段不再写死 30 和 48，而是上限的一半和五分之四（60 时仍是 30 和 48，所以桌面端和旧测试不变；40 时是 20 和 32，最后一次工具调用后是第 40 次的无工具交付调用）。
- **benchmark 设置：** `.env` 新字段 `BENCH_OCEANX_EXPERT_CALL_LIMIT`，10 到 60（不允许调高），`.env.example` 和默认值都是 40；
  `run_oceanx.py` 启动前把它传给后端，并写进 `arm.json` 的 `expert_call_limit`。没有这个字段的旧 `.env` 拉取后也会用 40，要对照 60 就写 60。
- **同时把剩余轮次告诉 Expert（Owner 的补充）：** Expert 的指令里写一次总预算（“你有 N 次模型调用……分析工具用到第 W 次，之后只能收尾写报告，最后一次没有工具”）；从第二次调用起，每次请求把最后一个工具结果的末尾加一行 `[Budget: model call 13 of 40; 20 left for analysis, then 8 only to finish the report.]`。这一行只加在当次请求里，不存进对话，所以缓存的提示前缀不变；图片结果的图片保持原样，文字追加在后面；报告检查点期间也照常加。桌面端的 Expert 也会收到。
- **不变：** 桌面端的上限、检查点的触发条件和提示、其他所有设置。
- **验证（Mac）：** 先写测试并确认失败再改；新增 14 项，包括用编译好的 agent 走一遍 40 次的收尾（第 33 次起只剩文件工具，第 40 次无工具）和配置到环境变量的映射，
  8 个变异检查全部被抓到；剩余轮次提示另有 9 项测试（含真实后端构建的四种 Expert 角色的指令）和 6 个变异检查。完整套件结果见下方验证条目。
- **怎样选 Q07 和 Q08：** `.env` 里 `BENCH_SUITE=test`、`BENCH_TASKS=Q07,Q08`、`BENCH_RESUME=false`，`BENCH_EXPERIMENT` 换一个新名字
  （例如 `methods-oceanx-flash-cap40`），然后 `python benchmarking/server/run_oceanx.py`。
- **解读时要注意：** 同一道题两次运行本来就有很大差别（E10 在 r1、r2、r3 的用时差了一倍），一对运行分不清上限的作用和运行间的波动；
  最好各跑两次，或者同时看每个 Expert 用了多少次调用、有没有在收尾阶段才第一次写报告、评分点有没有丢。
- **没有验证：** 真实模型在 40 次上限下的行为，以及 Linux 上的完整测试（改动不涉及沙箱）。


### 2026-10-04 — 服务器全量测试：4 项失败，其中两项 Finch 沙箱测试已查明并修改（Claude，待 Linux 复跑）

Owner 在服务器上拉到 `b0a2618`（v1.8 的修改已提交），跑了第 1 节的全量命令：**4 failed、1020 passed、4 skipped，172.78 秒**。
总数 1028，与本机一致（1020 passed + 8 skipped），所以服务器上跑的是同一批测试。

- **失败的 4 项：** `tests/test_sandbox/test_execution.py::test_cancelling_sandboxed_command_terminates_its_process_group` 和
  `tests/test_sandbox/test_linux.py::test_native_linux_readonly_network_fork_and_secret_isolation`，就是上面记录的两个已知旧测试，没有变化；
  另外两项是 `benchmarking/tests/test_finch_sandbox.py` 的 `test_native_filesystem_and_network_boundary`
  （`taskset: failed to execute .../oceanx-bench/bin/python: No such file or directory`）和
  `test_native_timeout_removes_detached_descendants`（`DID NOT RAISE TimeoutError`）。
- **v1.8 的新测试在 Linux 上通过。** 它们不在失败列表里，也没有跳过标记，包括走真沙箱的
  `test_the_real_sandbox_makes_the_preview_and_reports_unreadable_images`，所以 bubblewrap 里的 Pillow 预览路径已经在服务器上验证过。
- **Finch 两项不是本轮修改引起的。** 这是它们第一次在服务器上运行：此前 Linux 命令是第 7.2 节第 3 步的定向命令，不含 `benchmarking/tests`；
  macOS 上它们因为没有 bubblewrap 被跳过。`finch_sandbox.py` 和这个测试文件自 `2e88acc` 起没有改动。
- **原因：** 服务器上 `/home/mafzhang` 是 `/import/home2/mafzhang` 的别名。R3 的执行记录里 Python 的路径是
  `/import/home2/mafzhang/miniconda3/envs/oceanx-bench/...`，pytest 的警告里却是 `/home/mafzhang/miniconda3/envs/oceanx-bench/...`。
  `sandbox_command` 只把解析后的真实路径挂进沙箱，却用别名路径（`sys.executable`）启动解释器；沙箱里没有 `/home/mafzhang/...`，
  `taskset` 找不到解释器。计时测试因为进程立刻失败，没有抛出 `TimeoutError`。OceanX 的沙箱用解析后的路径，不受影响（R3 已证明可用）。
- **修改：** `benchmarking/server/finch_sandbox.py` 的 `sandbox_command` 在真实路径和启动用的路径不同时，把同一个真实目录（只读）
  同时挂在启动用的路径上；命令本身不变，路径相同时参数也不变。新增 `benchmarking/tests/test_finch_sandbox_command.py` 3 项，只检查生成的参数，
  不需要 bubblewrap，在 Mac 上也能跑；别名那一项在修改前失败。
- **影响范围：** Finch 臂。这个问题也会让 `run_finch.py` 启动时的内核自检失败，只要内核 Python 是经由 `/home/mafzhang/...` 这个别名给出的。OceanX 的 R4 不受影响。
- **没有验证：** 那两项在 Linux 上是否转为通过。服务器 pull 后复跑：
  `PYTHONPATH=src python -m pytest benchmarking/tests/test_finch_sandbox.py benchmarking/tests/test_finch_sandbox_command.py -q -p no:cacheprovider`。
  之后第 1 节全量命令预期只剩上面两个已知旧测试失败。


### 2026-10-04 — Claude 复核 f404221 并按 Owner 授权修改（待 Linux 验证与提交）

Owner 把 Codex 的复核请求转给我，随后说“你觉得需要修改的就修改”。`f404221` 已在 origin，服务器还没有拉取，没有启动任何模型调用。
我没有碰 `f404221` 之外的东西；下面是工作区里相对 `f404221` 的改动，未提交。

**复核发现（都在 `f404221` 上复现或用 R3 真实数据测量）**

1. **预览失败会让 Expert 崩溃。** `OceanSandbox.aread` 在预览失败时返回字符串，deepagents 的 `read_file` 读 `read_result.error`，
   抛 `AttributeError`，LangChain 的 ToolNode 不处理它，这个 Expert 的委派失败。静态模式下读一个不存在或损坏的 `.png` 就会触发；
   桌面模式同样的输入只是一条普通错误。
2. **scratch 整目录删除保护不到真实的引用方式。** R3 的 11 份报告里 5 份引用了 scratch 文件，共 18 处、13 个文件，**全部是相对路径**
   （如 `scratch/stats_out.txt`），绝对路径 0 处，所以“只查绝对路径”的保护一次也不会触发。scratch 里有 Expert 的 46 个脚本和 34 张 CSV，
   `command.sh` 只按名字调用脚本（`python figure.py`），删了以后脚本只剩在对话存档的 `write_file` 记录里。大于 10 MB 的 29 个文件占 99.56%
   （5.44 GB），其余 126 个文件共 24 MB；报告引用的 13 个文件里 8 个是小文件（0.08 MB）。
3. **补图拒绝识别太窄，只看最后一条消息。** “研究者要了图”的判断对 23 种常见说法只认出 6 种（“Provide figures”“Produce maps”“请画一张图”
   “请绘制剖面图”“出图”都认不出）；桌面端每轮只带最后一条消息。54 道 benchmark 题（30 道 test、24 道 evolution）里只有 Q30、E19 含视觉词，
   对 benchmark 影响很小，对桌面有风险：误拒用户真要的图，比多花 5 分钟补图糟。R3 的 11 次真实委派里，补图句式命中 2 次：1 次真补图，
   1 次是正常分析 B1.1.1.1（因为任务下面引用的上一节点结果里有 figure 和 make）。
4. **检查点多拒绝一次。** 第 30 次调用发出时所有工具都还开放，但它的工具在执行时被检查点拒绝，浪费一步。收尾阶段已经按“工具执行时的计数包含发出它的那次调用”处理，检查点没有。

**修改**

1. `native_backend.py`：预览失败返回 `ReadResult(error=...)`。文件不存在的措辞与普通缺失文件相同（`file_not_found`），其他失败给出异常那一行，不贴整段堆栈。
2. `collect_oceanx.py`：只删除大于 10 MB（10,000,000 字节，恰好等于不删）的 scratch 文件；符号链接不跟随、不计；`scratch_cleanup.json`（`schema_version` 2）
   增加 `min_bytes`、`kept_file_count` 和 `files`（每个被删文件的相对路径和字节数）；删除中途失败记为 `partial` 并列出已删的文件，重新收集时接着做；
   绝对路径引用保护和“重新收集保留第一次记录”不变。`evaluate.disk()` 对 `partial` 也计释放字节。
3. `delegation.py`：补图拒绝只在 static 运行生效（桌面保留提示词规则）；`explicitly_requests_visual` 改用更宽的规则（复数、`visuali[sz]*`、`draw`、diagram、
   heatmap、illustrate、中文 图/画/绘/可视化）；`visual_only_followup` 只看任务段（第一个空行之前），不看后面引用的上一节点结果。
4. `graphs.py`：检查点对工具的拒绝只覆盖第 31 至 48 次调用发出的非文件工具。

没有改：预览的大小规则和缓存（读图很少，不加缓存）、检查点的触发条件和提示、讨论伙伴角色仍挂检查点（它只有读文件工具，到不了第 30 次是常态，已知边角）。

**验证（都在 Mac 上）**

- 先写测试并确认失败，再改：预览失败 4 项、补图拒绝 19 项、检查点边界 1 项、scratch 清理 3 项。每处修改还单独还原做了变异检查，12 个变异全部被新测试抓到。
- 完整本机套件：**1019 passed、8 skipped、0 failed**（`f404221` 的完整导出上是 983 passed、8 skipped、0 failed；Codex 报的 58 个失败来自它宿主的沙箱限制）。
  `git diff --check` 通过，改动文件的 Ruff 结果与 `f404221` 相同（9 条，都是旧的）。
- R3 真实数据演练（`cp -c` 复制 5.2 GB 的下载目录，原件没动）：收集 `complete`，4 个登记输出、4 张图；删除 29 个文件、5,442,466,840 字节；
  attempt 由 5.57 GB 变成 0.132 GB；46 个脚本、34 张 CSV 和报告引用的 8 个小文件都在；清单求和等于释放字节。
- R3 的 11 次真实委派上，补图句式现在只命中 1 次（那次真补图），原先 2 次。

**没有验证**

- Linux 沙箱里的预览（Pillow、bubblewrap 路径和权限；上面那个真沙箱测试在 Mac 上通过，Linux 上还没跑）。从代码看预览写在 agent 自己的 `.runtime/temporary` 里，沙箱本来就可写，Pillow 随 matplotlib 一起装，但这是推断。
- 真实模型下的行为：补图拒绝后 Coordinator 怎么做、检查点对各节点用时的影响、Expert 少存文件后子节点是否更多重算。
- 并发由 2 变成最多 3 后的内存和 CPU。

**开跑前在 Linux 要做的**：完整套件 `PYTHONPATH=src python -m pytest tests benchmarking/tests -q -p no:cacheprovider`，预期只有本文记录的两个旧沙箱测试失败；
真沙箱那组（第 3 步那条，含 `test_native_large_edit.py`），再加上 `tests/test_oceanx/test_static_image_read.py`：其中 `test_the_real_sandbox_makes_the_preview_and_reports_unreadable_images` 走真沙箱读正常、缺失、损坏三种 png，正是验证 Linux 上 Pillow 和 bubblewrap 路径的那一项。
收集命令现在会删除文件：不要在还想保留 scratch 的 R1 至 R3 旧目录上重跑。


### 2026-10-04 — Codex 实现 R3 follow-up（待 Linux 验证与提交）

Owner 批准 R3 分析提出的六项优化，并进一步确认图片仍应进入 LLM 以判断空间 pattern；
问题是原始大图反复进入上下文，不是视觉本身。本轮没有启动模型、正式 benchmark 或科学分析。

- **未请求的补图：** Coordinator 的 task 中间件会拒绝“已有结果节点上的纯补图重派”，
  除非研究者的问题明确要求 visual。静态和交互 Expert 的工作规则均把最终图改为按请求或科学
  证据需要生成。最终综合还必须核对所有返回节点的最新 Result 和限制，不得只读最早报告。
- **图片上下文：** static benchmark 的 raster `read_file` 先在原沙箱中生成最长边 1024 px 的
  JPEG 预览；若仍过大则继续缩到 768/512 px，目标不超过约 450 KiB。LLM 仍能看空间 pattern，
  完整原图留在 outputs 作为交付物。
- **报告检查点：** Expert 到第 30 次模型调用仍没有非空 `report.md` 时，暂时只给文件工具；
  保存第一份可辩护的 partial report 后恢复分析工具。60 次上限不变。
- **代码执行：** 提示明确 `ocean_expert_run_code` 在当前 attempt 保留 Python 变量，迭代数组分析
  优先用它；不再为同一次尝试的状态传递保存整份源字段，只保留后续节点或重试确实需要的检查点。
- **并发：** Search Expert 使用独立的单槽，两个数据分析槽不再被文献咨询占用；新配置
  `BENCH_OCEANX_MAX_PARALLEL_SEARCH_EXPERTS=1` 写入 `.env.example` 和 `arm.json`。
- **scratch：** completed、有最终答案且收集无错误后，删除每个 node 的整个 `scratch/`，不是只删
  大文件（v1.8 改为只删大于 10 MB 的文件，见上一条）；写 `scratch_cleanup.json` 记录文件数和释放字节。最终答案或任何嵌套 Expert report 仍引用
  绝对 scratch 路径时拒绝清理。inventory 同时记录当前 scratch 和已释放字节。

验证：最终核心运行、策略、配置、收集和评估回归 **166 passed**，图片预览的实际转换命令另测
**1 passed**；`py_compile`、相关改动的 Ruff 和 `git diff --check` 通过。完整本机套件的最后一次
原始输出是 **925 passed、8 skipped、58 failed**：其中一个是新增测试夹具漏设原问题，已修复；
一个是方案已注明的 Claude timeout 时间敏感测试，单独重跑通过；其余 56 项都是 Codex 宿主禁止
localhost 端口或 macOS `sandbox-exec: sandbox_apply: Operation not permitted` 导致的真实网关/沙箱
测试。正式开跑前需在 Linux 服务器执行完整测试，并确认图片预览、连续写 outputs 和 persistent
kernel 自检通过。

### 2026-10-04 — R3 结果分析（Claude）：时间和 token 花在哪，候选优化（记录当时未批准）

Owner 把 R3 的结果下载到本机，让我看 Codex 的总结，并问整个流程还能怎么优化。我只读了下载的文件（模型调用账本、代码执行记录、研究树、对话存档），没有改代码。实验名是 `oceanx-flash-r3`，题目 E10，状态 `completed`。

**核对 Codex 的数字：一致。** 633 次模型调用；5,034 万 token，其中缓存输入 4,103 万；文献三次委派 991 万；补图 57 次调用、531 万；失败的代码执行 23 次、共 36 秒；总时长 4,644 秒。

**时间结构：6 个串行阶段，每个阶段的长度等于一个 Expert 用满 60 次调用的时间。**

| 阶段 | 起止（分钟） | 节点 | 调用数 | 模型秒 / 代码秒 |
|---|---|---|---|---|
| 1 | 0.4–10.3 | B1.1（数据）、B1.2（文献） | 61、30 | 385 / 189 |
| 2 | 10.9–23.2 | B1.1.1（数据）、B1.2.1（文献） | 64、34 | 470 / 249 |
| 3 | 24.0–41.3 | B1.1.1.1（数据）、B1.1.1.2（统计） | 62、62 | 672 / 349 |
| 4 | 42.0–61.2 | B1.1.1.1.1、B1.1.1.1.2（数据）、B1.1.1.1.3（文献） | 61、61、58 | 520 / 383 |
| 5 | 61.9–70.1 | B1.1.1.1.2.1（数据） | 60 | 386 / 136 |
| 6 | 70.4–75.3 | B1.1.1.1.2 第二次（补图） | 57 | 265 / 18 |

“模型秒 / 代码秒”是每个阶段里决定时长的那个数据节点的数字。Coordinator 一共 23 次调用、265 秒。

**发现**

1. **每个 Expert 都是用满额度才停。** 7 个数据分析尝试的对话都正好 60 轮。其中 4 个到第 54–59 轮才第一次写报告，2 个全程没有用文件工具写报告，靠最后一轮的回复被后端存成报告（`88cab8b` 的机制起了作用）。只有 B1.1 在第 30 轮就写了。“有了站得住的部分答案就写报告”这条规则基本没被执行。
2. **补图不该发生。** 用户的问题里没有要图。Coordinator 的原话是 “using the single permitted visual follow-up to obtain the missing comparison figure”，它把“可以补一次”当成了可用的权利。起因是第一次尝试的回执写着 `Saved figures: None`，报告里写着 “no figure was rendered before the analysis window closed”。A4 的提示词没有拦住。
3. **补图那一次的 57 次调用。** 图在第 11 次代码执行（开始后 2 分 15 秒）就存好了。之前有 7 次是在弄明白自己上一次存的 CSV 的格式；之后约 37 次调用是把图裁成小块反复读、用像素统计检查空白、改标题重画、用脚本改报告里的一句话。
4. **读图极贵。** 全程 8 次 `read_file` 读图片，返回 241 万个字符，比其余所有工具结果加起来（约 172 万）还多。单次调用的输入因此从 6–9 万 token 涨到 47–51 万。全程 15 次上下文压缩，其中 7 次在补图里。模型确实能描述图的内容，但裁剪后的小图它自己也说看不清。
5. **代码几乎都走 shell。** shell（`execute`）224 次、共 1,875 秒；kernel（`ocean_expert_run_code`）34 次、共 81 秒。shell 每次是新进程，状态只能靠文件传。数据分析的 470 轮里，48% 是跑代码，25% 是写或改脚本文件，21% 是读文件，3% 是写报告。kernel 工具的说明里没有提变量会保留，提示里反而两处鼓励把中间结果存成文件。
6. **两个并行空位被文献占用。** 第 4 阶段的 B1.1.1.1.2 从被委派到第一次模型调用等了 635 秒，因为文献节点占着一个空位。
7. **文献咨询。** 三次，共 122 次调用。B1.1.1.1.3 用 curl 抓了 NEMO 的源码和产品文档来确认实际判据，是有价值的查证，但它是在 `search_only` 模式下下载了文件。B1.2.1 自己做了理想剖面的数值实验，超出了 E 定的范围。
8. **最终综合很短。** Coordinator 在 75.3 分钟读了 B1.1 和 B1.1.1 两份报告的前 120 行和研究树，76.2 分钟一次写出 28,676 个字符的最终答案。后面的节点报告它没有重读。Codex 指出的“把不同阈值下的数字拼在一起”正出在这一步。
9. **存储。** 5.4 GB 里 5.398 GB 是 `scratch/`。155 个文件中 29 个超过 10 MB，占 99.6%。82% 是 NetCDF，17% 是 pickle。没有内容完全相同的重复文件，都是未压缩的 float32。最大的 `ts_stacked.nc`（1.25 GB）是把源数据的温度和盐度又存了一份。正式输出只有 1.6 MB。

**检查表里能从下载文件判断的项**

- 状态 `completed`，有最终答案；11 次尝试都交了报告；没有未绑定的尝试；同一节点最多 2 次（B1.1.1.1.2）。
- 没有 kernel 启动失败，没有只读失败；23 次失败都是代码错误（KeyError、ValueError、SyntaxError 等）。
- 5 个 Agent 目录生成了 `data-index.json`；Expert 从被委派到第一次模型调用只有 1–3 秒，数据清单的探测没有拖慢启动。
- 第 11 项：有一次补图，用户的问题没有要图。
- `backend.log` 是空文件，第 18 项里的警告次数无法核对。

**候选改动（后续已由 Owner 批准；最终实现以 v1.7 和最新 Log 为准）**

| # | 改动 | 依据 | 这次能省多少 |
|---|---|---|---|
| 1 | 不为图单独派任务，除非用户的原话要了图；Expert 规则写明图是可选的 | 发现 2、3 | 4.9 分钟、531 万 token |
| 2 | benchmark 里 `read_file` 给模型最长边 1024 px、大小有界的 JPEG 预览；原图仍保留 | 发现 4；Owner 明确要求模型仍能判断空间 pattern | 主要是 token；避免原始大图撑大上下文 |
| 3 | 告诉 Expert kernel 会保留变量，分析优先用它；不再鼓励存中间文件 | 发现 5、9 | 未知，需要对比运行 |
| 4 | 文献咨询使用独立的单槽，不占两个数据分析空位 | 发现 6 | 约 4 分钟 |
| 5 | 成功且无错误地收集后删除全部 node `scratch/`，留下清单；最终文字仍引用 scratch 时拒绝清理 | 发现 9；Owner 确认 scratch 都是可丢弃的中间结果 | 5.4 GB 降到正式结果和运行记录的大小 |
| 6 | 中途提醒一次“答完就写报告收尾” | 发现 1 | 未知，需要对比运行 |

第 1 项里有我的责任：静态模式下 Expert 的那句 “Make a final figure with matplotlib…” 是我写的，读起来像每个节点都要出图。

### 2026-10-03 — Owner 授权修复 NFS 实验共享锁并推送、同步服务器

- 实际失败发生在公共启动层，不是 Finch 模型或执行器。服务器输出根目录是 NFS；已有实验锁文件以只写方式打开时申请共享锁，实测返回 `EBADF`，读写方式成功。未改文件内容，未运行分析。
- 最小修复：`benchmark_run.experiment_guard` 打开锁文件从 `a` 改为 `a+`，共享/排他和非阻塞锁语义保持不变；不增加机制，不修改沙箱。`RUNNING.md` 同步说明 NFS 兼容性。
- 新回归测试按 NFS 的要求检查共享锁 FD 可读、排他锁 FD 可写。修复前 **1 failed, 1 passed**；修复后该文件 **29 passed**，既有并发启动与重置保护测试仍通过。
- 全量 **974 passed, 8 skipped**，144.70 秒，日志 `/private/tmp/oceanx-nfs-lock-full.log`。`git diff --check` 通过；两个改动 Python 文件的 Ruff 问题与 HEAD 相同（共四条），未扩大范围处理。
- 当时仍正常运行的 Claude 是更新前启动的旧 runner，旧版本没有实验共享锁，因此没有走到失败路径。新版三种方法共用这个入口，均受到同一修复。
- Owner 已授权提交、推送 origin 和服务器拉取；服务器仅验证共享锁，不重置实验或启动 benchmark。

### 2026-10-03 — 服务器上的 Linux 测试：新加的部分全部通过，两个旧的沙箱测试失败（Claude 分析，不挡 R3）

Owner 在服务器上拉到 `2e88acc`，跑了第 7.2 节第 3 步的命令，结果是 **2 failed, 152 passed, 1 skipped，38.65 秒**，并把截图发给我。本轮只改了本文件。

**结论：这两个失败不是 A 到 G 引入的，也不挡 R3。沙箱不改。**

**通过的部分**

- 数据清单（`test_saved_data_index.py`）、静态图片交付（`test_static_figure_delivery.py`）、大文件编辑（`test_native_large_edit.py`）、kernel 和自检，在 Linux 的真实沙箱里全部通过，没有被跳过。
- Linux 专有的 `test_native_linux_scientific_netcdf_zarr_and_plot` 也通过了：在沙箱里写 NetCDF、zarr，并用 matplotlib 把图存成 PNG。这正是静态交付要用的路径。
- 跳过的 1 个是需要手动开启的联网测试，和平台无关。

**依据**

- `git diff cef4736 2e88acc -- src/oceanx/sandbox tests/test_sandbox` 是空的。最后一次提交没有碰沙箱代码和沙箱测试。
- 最近一次改沙箱的是 `8df7791`，它只让“可写目录里的只读路径不再生效”，和这两个测试查的东西无关。

**失败 1：`test_cancelling_sandboxed_command_terminates_its_process_group`，`PermissionError: Operation not permitted`**

- 测试让沙箱里的进程把自己的进程号写进文件，取消之后在宿主机上用 `os.kill(pid, 0)` 看它还在不在。
- Linux 的沙箱有独立的进程号空间，沙箱里拿到的是内部编号（通常是 2）。宿主机上的 2 号进程是内核线程，普通用户无权探测，所以得到“没有权限”，而不是测试期待的“进程不存在”。
- 这是测试写法在 Linux 上不成立，不说明取消功能有问题。生产代码取消时杀的是宿主机上 bubblewrap 的进程组，再加上 `--die-with-parent`。
- 测试是 `427ac68`（9 月 4 日）加的，在 macOS 上能通过，因为那里没有独立的进程号空间。

**失败 2：`test_native_linux_readonly_network_fork_and_secret_isolation`，沙箱里报 `outside write allowed`**

- 测试让沙箱里的脚本去写两个地方：只读目录里的文件，和所有声明目录之外的 `secret.txt`，并要求两次都报错。
- Linux 沙箱的根目录是 bubblewrap 自建的一块内存文件系统，只有声明过的目录被挂进来，而且根目录本身可写（命令里没有 `--remount-ro /`，历史上也从来没有过）。所以往没声明的路径写文件不会报错：文件落在沙箱自己的内存里，沙箱结束就消失。宿主机上的 `secret.txt` 既读不到也改不了。
- 所以这不是数据泄漏，也不是只读数据被改，而是“写到没声明的地方不报错、文件悄悄丢掉”。它和测试的预期不一致。
- 我的判断里有一步是推断：截图分不出是哪一次写入成功。我认为是 `secret.txt` 那次，依据是只读挂载在这台服务器上确实生效，r1 的扫描里有 32 条 `Read-only file system` 报错。
- 测试是 `80cb82c`（9 月 6 日）加的。

**为什么以前没发现**

- 这两个测试在 macOS 上一个通过、一个跳过。GitHub 的 CI 在 9 月 30 日被移除。之前在服务器上只单独跑过 kernel 的 5 个测试。就我所知，这是 `tests/test_sandbox` 第一次在真实的 Linux 沙箱上完整跑。
- r1 和 r2 就是在同样的沙箱行为下跑的。

**现在不改沙箱的理由**

- 方案第 1 节规定不碰沙箱的严格程度。
- 把根目录设成只读（`--remount-ro /`）能让这类写入明确报错，但它可能影响 kernel 启动和各种库写缓存目录的行为，而且只能在 Linux 上验证。R3 之前不值得冒这个险。

**留到 R3 之后再定的两件事（等 Owner 决定）**

1. 改测试 1：不要用沙箱内部的进程号去宿主机上探测。
2. 测试 2 二选一：把沙箱根目录设成只读，让没声明的写入明确报错；或者把测试改成断言实际保证的内容，也就是宿主机文件不变、沙箱里读不到。前者对模型更友好（会看到报错，而不是文件悄悄消失），但要在 Linux 上充分验证。

**下一步**

- 继续第 7.2 节第 2 步（`check_setup.py`）和第 4 步（跑 R3）。

### 2026-10-03 — Owner 授权将全部当前改动一起提交

- Owner 明确要求“提交一下所有改动”，本次统一纳入 A4、B、E、D、C、F、G，以及当前 benchmark/Finch 的并行改动，不再按包拆分。
- 提交前全量测试为 **972 passed, 8 skipped**，`git diff --check` 通过；待加入的新文件均为源码或测试，`benchmarking/.env` 仍被 Git 忽略。
- 此次授权仅执行本地提交，不推送 origin、不拉取服务器、不启动 R3；各包的独立审核状态沿用进度表和对应 Log。

### 2026-10-03 — Claude 审核 D 的 v1.5 披露检查：通过。A4 到 G 全部可以提交

Owner 让我审核。本轮只改了本文件，没有改代码，没有提交。

**结论**

- **D 的 v1.5 补丁通过，可以提交。** `graphs.build` 只在工作区对当前服务商的元数据策略是 `allow` 时才生成和放入数据清单，用的是和后面构建上下文同一份策略。不允许时不跑探测，已有的缓存也不会被用来绕过。
- **A4、B、E、D、C、F、G 现在都已实现、都有实现方之外的人看过，可以提交。** 方案里没有待改的代码了。

**独立验证**

- 用我上一轮自己写的复现脚本重跑：`metadata` 为 `deny` 时清单不再出现，`allow` 时照常出现。
- **变异检查 4 项全部被抓到**，在草稿目录的副本上做：去掉判断（8 个失败）、把 `prompt` 当成允许（4 个）、查错策略类别（8 个）、先探测再隐藏文字（8 个）。
- **默认策略下模型看到的文字没有任何变化**：交互模式 180 段、静态模式 174 段，和上一轮逐段相同。所以这个补丁不改变 R3 的行为。
- **全量测试 972 个通过、8 个跳过**，和 Codex 报告的一致，测试前后工作区一致。
  - 要说明的一点：我第一次跑全量时有 1 个失败，是 `test_run_claude.py::test_timeout_kills_children_retains_outputs`。第 1 节点名过它对时间敏感。当时我同时在副本上跑变异，机器负载高。按规则重跑：它单独跑 3 次都通过；没有其他任务时再跑全量，972 个全部通过。这个测试属于并行的 benchmark 工作，和本轮改动无关。
- **Ruff**：24 个改动文件，HEAD 上 24 条，现在 15 条，没有任何一条增加。

**对我上一轮说法的一处更正**

- 我上一轮写的是“提交前补”，并说受影响的是“桌面版里改过这项设置的工作区”。这次我去查了桌面界面：设置对话框里**没有**修改这项策略的入口，前端只有类型定义，没有任何代码发送 `disclosure.policy.set`。目前只有通过协议才能把它设成拒绝。
- 所以这个检查是对的，也该有（后端支持这份策略，自动放进提示的内容应该一致地遵守它），但它在今天的实际紧迫程度比我上一轮说的低。

**记录在案的两处方案外现象（HEAD 里就有，和 R3 无关，现在不建议处理）**

1. `src/oceanx/cli.py:279` 缺少 `RequestStore` 导入，`oceanx export` 一运行就报 `NameError`。上一条 Claude 的 Log 里已写，等 Owner 决定。
2. **披露策略绑定到一个服务商，换服务商会把整份策略重置成全部允许。** `OceanContextBuilder.policy_for` 发现存储的服务商和当前的不同，就新建一份默认策略。实测：为 `provider_a` 设了 `deny`，一个使用 `provider_b` 的 Expert 构建提示之后，存储的策略变成 `provider_b`、全部允许；之后 `provider_a` 再查也是允许。数据集上下文和数据清单都受同样的影响。这是策略机制本身的行为，不是 D 引入的；而且界面上现在设不了 `deny`，所以今天没有用户会碰到。以后要给界面加这项设置时，应该先把这一点定下来。

**提交时怎么分（Owner 请看）**

工作区里有两批互不相关的改动，建议分成两次提交：先提交并行的 benchmark 重置和 Finch 工作，再提交方案里的 A4 到 G。

- **只属于并行工作的 10 个文件**：`benchmarking/.env.example`，`benchmarking/server/` 下的 `benchmark_config.py`、`benchmark_run.py`、`finch_worker.py`、`run_claude.py`、`run_finch.py`，`benchmarking/tests/` 下的 `test_benchmark_run.py`、`test_run_claude.py`、`test_run_finch.py`、`test_finch_failure_replay.py`（新文件）。
- **两边都改了的 2 个文件**，要用 `git add -p` 选：
  - `benchmarking/server/run_oceanx.py` 共 6 块。后 2 块是并行工作的（`main` 拆成 `_main` 并加 `ExitStack`；`configure_run(..., stack=stack)`）。前 4 块是 B 的（`FIGURE_DELIVERY` 常量、`backend_environment` 的说明和 import、设置环境变量的一行、`arm_record` 里的 `figure_delivery`）。
  - `benchmarking/RUNNING.md` 共 5 块。前 3 块是并行工作的（Finch 的执行超时、reset 的措辞、reset 一节）。第 4 块是 F 的（Run settings and comparison limits），第 5 块是 B 的（Every OceanX attempt delivers ordinary images）。
- **其余 27 个文件都属于方案**。A4 到 G 在 `graphs.py`、`runtime.py`、`native_backend.py`、`README.md` 里互相重叠，拆不干净，合成一次提交。
- 并行工作那一批我没有审核过，只确认了带着它全量测试能通过。

**还没做的事**

1. 提交（上面两次），并推送。A2、A3 已提交但还没推送。
2. 服务器上跑第 7.2 节第 3 步的测试。A1 之后的所有改动都只在 macOS 上跑过。
3. R3，等 Owner 通知。
4. `cli.py` 的缺口，等 Owner 决定。
5. 没有任何一个包用真实模型验证过。效果要等 R3；C 只影响桌面版，R3 测不到它。

### 2026-10-03 — Codex 完成 D 的 v1.5 披露检查（待 Claude 复核与 Owner 提交）

**范围与改动**

- 按第 6 节 D（v1.5）补齐自动数据清单的披露检查，不改披露策略本身。
- `graphs.build` 使用同一个 `OceanContextBuilder`，按当前工作区和模型 provider 读取策略；只有 `decision_for("metadata") == "allow"` 才调用 `_saved_data_prompt`。
- `deny` 和 `prompt` 都跳过探测和清单注入，已有缓存也不能绕过检查；保留 earlier-work 的目录路径提示。不新增审计类别，不改缓存服务或探测脚本。
- README 同步说明这项限制。

**回归验证**

- 新增 8 个参数化场景，覆盖 `deny`/`prompt`、交互/普通图片模式、research/standard 工作流。每个场景同时验证：初次禁止时不探测、不建缓存；允许后正常生成清单和缓存；已有缓存后撤销权限仍不调用探测、不注入清单，缓存内容不变。
- 修改前新增测试 **8 failed**（`/private/tmp/oceanx-d-v15-red.log`）；修改后相关测试 **38 passed**（`/private/tmp/oceanx-d-v15-target.log`）。
- 全量测试 **972 passed, 8 skipped**，143.12 秒（`/private/tmp/oceanx-d-v15-full.log`）。运行前后 209 个 Python 文件的哈希和 tracked diff 哈希一致。
- 新增测试文件 Ruff 通过；`graphs.py` 的 Ruff 结果与 HEAD 相同，仍有既有的 I001、F401、RUF100 各一条，没有新增问题。未顺手修复它们。

**边界与待办**

- 本轮只在 macOS 使用合成测试数据验证，未进行 Linux 验证、真实模型调用或 R3。
- 未提交、推送、同步服务器或启动 benchmark；停下等待 Claude 复核和 Owner 提交。
- 上一条 Log 中的 `cli.py` 缺少 `RequestStore` 导入仍是方案外待决定事项，本轮未修改。

### 2026-10-03 — Claude 复核 Codex 的 v1.4 补充（C、D、G），并发现 D 的一处遗漏

Owner 让我复核。本轮只改了本文件，没有改代码，没有提交。

**结论**

| 包 | 结论 |
|---|---|
| C | 通过，可以提交。三处补充和措辞都按 v1.4 做了。 |
| G | 通过，可以提交。 |
| D | 两条加固通过。但复核时发现一个前两轮都没查到的问题：清单没有遵守工作区的披露策略。提交前补这一处，见第 6 节 D（v1.5）。 |
| B | Codex 已独立复核通过。至此 A4 到 G 每个包都有实现方之外的人看过。 |

**独立验证**

- 全量测试 **964 个通过、8 个跳过**，和 Codex 报告的一致；测试前后工作区一致。
- **变异检查 10 项全部被抓到**，在草稿目录的副本上做，没有碰工作区。
  - G：去掉导入，2 个失败。
  - D：去掉大小上限、去掉 `errors="replace"`、没数行数时显示成 0 行，各 1 个失败。
  - C：提示改回 “once”（4 个）、去掉调用骨架（3 个）、`panel` 那一行改回旧写法（2 个）、说明加长到三页（1 个）、skill 里留着占位符（2 个）、缺说明时重新报错（1 个）。
- **按模型实际的读取路径走了一遍。** 说明现在是 260 行、16,894 个字符。照提示的写法（`limit=300`，按返回的 offset 继续）通过真实沙箱读 `result-api.md`：2 次读完，拼起来和原文完全一致。skill 里的 `API.md` 经 `/skills/` 路径 1 次读完。准备好的 `SKILL.md` 里占位符已换成 260，没有残留。
- `read_file` 的 `limit` 参数没有上限，`limit=300` 可用。
- 占位符 `{{FIGURE_API_LINE_COUNT}}` 只存在于打包的源文件里。模型只读准备好的副本；其他读取打包 skill 的代码（学习区域、工具清单）只处理有学习区域的 skill，绘图 skill 没有学习区域，所以不会经过它们。
- **交互模式**：180 段模型可见文字里有 10 段相对上一轮有变化，都是这一轮要改的（Expert 提示、`API.md`、`SKILL.md`），没有未替换的占位符。
- **静态模式**：174 段文字相对上一轮没有任何变化，没有接口名泄漏，包括新加的骨架里的 `fig.panel`、`panel.field2d`。
- Coordinator 提示仍是 4,999 个字符。
- **Ruff**：24 个改动文件，HEAD 上 24 条，现在 15 条，没有任何一条增加。G 消掉了原有的 3 条未定义名字。

**D 的遗漏：清单绕过了披露策略**

- 发现的经过：复核完改动之后，我想了一遍 R3 之前还有什么没查过，想到清单是后端**自动**放进提示的数据信息，而 OceanX 对这类信息有一份用户可以设置的策略。
- 复现见第 6 节 D（v1.5）。`metadata` 设为 `deny` 时，后端自己的上下文已经不带 `dataset_context`，清单照发。
- 这是我定方案时漏掉的，不是 Codex 的实现问题。D 的方案里没有提这份策略。
- 对 R3 没有影响：benchmark 的工作区用默认策略。对桌面版是一个需要补上的口子，所以放在提交之前。
- 其他包我按同样的角度看了一遍：B、C、E、F、G 都没有新增自动放进提示的数据信息。

**回答 Codex 的问题**

- `tests/test_oceanx/test_native_large_edit.py` 加进第 7.2 节的 Linux 检查命令：加，已经改了。它走真实的 OS 沙箱，Linux 上是 bubblewrap，和 macOS 不是同一套实现。

**顺带发现的另一处方案外缺口（未修改，等 Owner 决定）**

- G 是 Ruff 的“未定义名字”检查发现的，所以我对 `src` 和 benchmark 脚本整体跑了一遍同样的检查。G 修好之后只剩一处：`src/oceanx/cli.py:279` 用了 `RequestStore`，但没有导入。
- 实测：`oceanx export` 这个命令行子命令一运行就报 `NameError: name 'RequestStore' is not defined`。没有测试调用它；现有的导出测试走的是协议，不是命令行。
- HEAD 里就有。它和 R3 无关，benchmark 不用这个命令；和 A 到 G 也无关。
- 改法是加一行 `from oceanx.backend.store import RequestStore`，再加一个用 `typer` 的 `CliRunner` 调用 `export` 的测试。要不要做、放在哪个提交里，由 Owner 决定。

**还没做的事**

1. D 的披露策略一处（Codex）。
2. `cli.py` 的缺口，等 Owner 决定。
3. 提交。A4、B、E、D、C、F、G 都没提交，并且在 `graphs.py`、`runtime.py`、`native_backend.py`、`README.md` 等文件里互相重叠，只能合成一次提交，或者用 `git add -p` 拆。并行的 benchmark 重置和 Finch 改动也没提交，`run_oceanx.py` 和 `RUNNING.md` 里两边的改动混在一起。A2、A3 已提交但没推送。
4. Linux 上的测试，命令在第 7.2 节第 3 步。A1 之后的所有改动都只在 macOS 上跑过。
5. R3，等 Owner 通知。
6. 没有任何一个包用真实模型验证过。C 只影响桌面版，R3 测不到它。

### 2026-10-03 — Codex 完成 v1.4 的 C/D 补充与 G，独立复核 B（待审核与 Owner 提交）

Owner 要求继续按本文件修改，并明确答复“两项都批准”：交互提示的一行调用骨架、G 包。先完成方案要求一起做的 C/D 补充并跑全量测试，然后做 G 再跑全量；期间只读复核 B。没有提交、推送、服务器操作、真实模型调用或 R3。

**C：三处补充与措辞**

- 提示、说明开头和准备好的 skill 副本均要求读到结尾，用 `limit=300`、按工具给出的 offset 续读。行数从最终生成文本计算，当前 **260 行、16,894 字符**；没有删内容或改变读取器的 12,000 字符上限。
- skill 源文件使用行数占位符，准备副本时替换；替换后的文本参与内容哈希，学习区域和旧副本不改。
- 在 `fig.panel` 一节列出真正转发的关键字参数，排除 `figure`、`panel_id`、`x`、`y`。测试把每个列出的关键字实际传给 `fig.panel`。
- 仅交互提示增加 **303 字符**的一行骨架，包含构造、panel、全部 11 个图层方法和 save；名称从代码取得。静态模式不包含这行。
- 明确 datetime64/datetime/ISO 自动成为时间轴、跨反经线几何由调用者拆分，并解释 source_handle/conclusions/spatial_context；说明查找改为 `.get`，完整性仍由测试强制检查。README 不再把补图限于最初问题。
- 修改前 **8 failed, 15 passed**。新增真实 `native_text.text_read` 翻页测试：**恰好两页、拼接等于全文**，超过两页时失败提醒。测试还覆盖提示与 skill 的动态行数、实际参数、骨架完整性和缺少图层说明不阻止生成。

**D：CSV 探测加固**

- 超过 `256 * 1024 * 1024` 字节不扫描行数；列名保留、`rows` 省略，提示写 `rows not counted`，不伪装成 0 行。
- 行数读取加 `errors="replace"`；列名探测也使用替换解码，避免 pandas 预读到非 UTF-8 数据时先失败。其余格式和缓存机制不改。
- 修改前 **2 failed**。大文件测试缩小阈值并禁止 `_data_rows`；非 UTF-8 测试还含带引号的多行字段，断言列名和 2 条记录均正确。
- C/D 完成后全量 **960 passed, 8 skipped，131.40 秒**，前后 208 个 Python 文件哈希一致。日志 `/private/tmp/oceanx-cd-v14-full.log`。

**G：一行导入修复**

- 先通过真实 OS 沙箱调用大文件 `aedit`，覆盖 Coordinator 的 `OceanSandbox` 和 Expert 的 `ResearchSandbox`；old/new 合计 **60,008 字节**，确实走大编辑路径。
- 修复前成功编辑两例在文件已改后抛 `NameError`：**2 failed, 2 passed**；另两例确认找不到 old_string 时返回 error 且文件不变。
- 源码只在 `deepagents.backends.protocol` 导入列表加 `EditResult`，不改算法、阈值、异常策略或 deepagents。修复后四例通过。

**B：独立复核通过（不新增 B 行为）**

- 逐处核对开关及 benchmark 环境/arm 记录、图片发现/哈希/路径映射、按 Agent 归属的回执和 output_refs、缓存保护、收集器移植链接、角色提示/工具/skill 隔离及交互默认行为。实现符合第 6 节 B；没有修改并行 reset/Finch 工作。
- 重跑 B、G、收集及 arm 测试：**42 passed**。B 的真实后端夹具覆盖 7 种角色/工作流，先构建交互再构建静态，检查旧 API 文件移除和模型可见文字隔离。
- 独立变异只在隔离进程里 patch，未写源码：图片发现返回空时，登记和带图回执测试 **2 failed, 1 passed**；关闭静态判断时，模型可见隔离测试 **1 failed**。关键回归确实会检测断链和泄漏。
- 这是实现审核，不证明真实模型一定存对位置、引用正确或更快，也不等于审核了无关 benchmark/Finch 改动。

**最终检查与剩余工作**

- 全量 **964 passed, 8 skipped, 763 warnings，128.57 秒**；日志 `/private/tmp/oceanx-v14-final-full.log`。全量前后 **209 个 Python 文件内容哈希和 tracked diff 哈希均一致**；之后只更新本文件。
- 新增/补充的生成器、probe 和测试 Ruff 通过；G 消除了原有三处 F821，`native_backend.py` 原有 import 排序提示保留。`git diff --check` 通过；Coordinator 提示仍 **4,999 字符**。
- 只在本机 macOS、合成数据/假模型夹具验证，无私有数据。Linux 与实际效果仍等服务器验证；G 的真实沙箱回归文件为 `tests/test_oceanx/test_native_large_edit.py`，请 Claude 确认是否加进第 7.2 节的 Linux 检查命令。
- 等 Claude 复核 C/D 本轮补充和 G、Owner 决定混合工作区提交边界；不自动进入 R3。评分、60 次上限、学习区域、沙箱和网络权限均未改变。

### 2026-10-03 — Claude 审核 Codex 的 D 补丁、C、F，并处理方案外缺口

Owner 让我查还有什么没做，并审核需要我看的部分。本轮只改了本文件，没有改代码，没有提交。

**结论**

| 包 | 结论 |
|---|---|
| E | 通过。我写的，Codex 独立复核过。 |
| D | 通过。Codex 的两处补丁正确，测试有效。两条加固写进了第 6 节 D，不挡提交。 |
| C | 实现符合方案，测试有效。但按 Expert 实际的读取路径量过以后，发现说明读不完；另有一行签名会误导。先补三处再提交，见第 6 节 C（v1.4）。 |
| F | 通过。文字里对代码行为的陈述我逐条核对过，属实。 |
| G（新） | 方案外缺口，已复现，建议 R3 之前修。等 Owner 确认。 |
| B | 仍然没有独立审核。Codex 本轮只跑了静态隔离回归，它自己也说明这不算复审 B。 |

**独立验证**

- 全量测试 **954 个通过、8 个跳过**，和 Codex 报告的一致；测试前后工作区一致。
- **变异检查 9 项全部被抓到。** 在草稿目录的副本上做，没有碰工作区。D：行数统计改回数换行（2 个失败）、缓存清理改回只在重新探测时进行（2 个失败）。C：提示不指向说明、`result-api.md` 不是生成的文本、skill 副本没有 `API.md`、例子缺 `units`、新增一个没写说明的图层方法（1 到 12 个失败）。F：说明改回归因、`EVALUATION.md` 少一条披露（各 1 个失败）。
- **桌面版的提示相对 HEAD 改了什么。** 这是 Codex 说它没做的那项。7 种角色和模式共 177 段模型可见文字，9 段有变化，都是各包要改的：Coordinator 的两句咨询规则（E）和补图规则（A4、B）；Expert 规则里的 `units`、`long_name`、`title` 一句（D）；Figure API 整块换成指向说明的短规则（C）；Search Expert 的范围（E）；绘图 skill 多了指向说明的一段、三个自包含的例子和 `API.md`（C）。工具描述和讨论伙伴的提示没有变化。
- **静态模式**：174 段文字里没有任何接口名，包括 `API.md` 和 `scientific_view`。
- **依赖**：后端 import `oceanx.research.graphs` 时没有加载 matplotlib、numpy 或 xarray，耗时不变（1.49 秒，HEAD 是 1.46 秒）。打包脚本用 `--collect-submodules oceanx`，新模块不需要登记。
- **Ruff**：23 个改动文件，HEAD 上 24 条，现在 18 条，没有任何一条增加。Codex 的说法属实。
- B 和 A4 的测试没有被放宽。

**D 的两处补丁**

- 行数改用 `csv.reader`：正确，引号里的换行不再被算成记录。代价是速度，实测 200 MB 的 CSV 用时 1.56 秒（134 MB/s），原来数字节是 0.12 秒。正常大小的表没有影响；单个目录里 CSV 合计到 8 GB 左右才会碰到 60 秒的等待上限。
- 另一个小退步：现在按 UTF-8 文本读，数据行里出现一个非 UTF-8 字节，整个文件就会被标成读不出来。
- 文件删除后清理缓存：正确。旧行为只是缓存文件里留着无用条目，不影响返回结果。
- 两条加固（大文件不数行数、`errors="replace"`）写进了第 6 节 D。

**C：为什么要先补三处**

- **说明读不完。** 说明是 260 行、16,459 个字符。Expert 的 `read_file` 默认一次 100 行，读取器每次最多 12,000 个字符。用读取器的真实函数量过：
  - 默认参数：3 次。第一次是第 1 到 100 行，停在 `panel.reference`，没有 `scatter` 和 `vector`，没有各 `plot_kind` 的限制，没有任何例子。
  - `limit=300`：2 次，第一次到第 144 行，停在第一个例子中间。
  - 提示、skill 和说明开头写的都是 “once”。这是我定方案时没量过的地方，不是 Codex 的实现问题。
- **`fig.panel` 的关键字参数那一行会误导。** 它印的是 `ScientificPanel.__init__` 的签名，带 `figure` 和必填的 `panel_id`。照着调用，实测得到 `TypeError`。这一行是我写生成器时留下的，Codex 的测试把它原样固定住了。
- **没读文件的 Expert 比 HEAD 知道得少。** HEAD 的提示里有 3 个内联例子。现在提示里只有文件位置和草稿规则。所以建议留一行调用骨架，这一条改了已确认的细节（“提示里只留简短规则和文件位置”），等 Owner 确认。
- Codex 改对的两处：整数时间戳只在显式声明时间轴时被拒绝；分类标签可以省略。我原来的写法是错的。
- 其余是措辞，列在第 6 节 C 的“顺手改的措辞”里。另外实测了两件说明里没写错、但值得知道的事：没列出的 `plot_kind`（例如 `bar_chart`）也能保存；地图坐标不单调时代码会自己排序。

**F**

- “压缩请求单独计为 summary calls”：`metering.py` 里这类请求记为 `kind: "summary"`，属实。
- “最后一次调用可能多发一次请求”：`88cab8b` 的纯文本重试会再调一次模型，账本多一行，属实。
- “预算用到 75% 后不再开新委派”：`RESEARCH_BUDGET_STOP = 0.75`，属实。
- 分类器的实现没有改，只改了说明；那个测试只是改了名字。

**G：方案外缺口的处理**

- Codex 登记的问题属实，而且比登记的更重一点：三个出口里包括成功的那一个。
- 复现：用真实沙箱编辑一个文件，`old_string` 加 `new_string` 共 60,008 字节。文件已经被改，然后抛 `NameError`。4,008 字节的编辑走另一条路径，正常返回。
- 我没有跑完整的 Agent 去看最后的任务状态。依据是 LangGraph 默认的工具错误处理只接住参数错误，其他异常会继续抛。
- 按规则这不在已批准的范围里，所以写成 G 包，等 Owner 确认。

**还没做的事**

1. C 的三处小改和措辞，D 的两条加固（Codex）。
2. G（等 Owner 确认，然后 Codex）。
3. B 的独立复核（Codex）。
4. 提交。A4、B、E、D、C、F 都没提交，而且在 `graphs.py`、`runtime.py`、`README.md` 等文件里互相重叠，只能合成一次提交，或者用 `git add -p` 拆。并行的 benchmark 重置和 Finch 改动也还没提交，`run_oceanx.py` 和 `RUNNING.md` 里两边的改动混在一起。A2、A3 已提交但没推送。
5. Linux 上的测试。B 到 F 只在 macOS 上跑过。第 7.2 节第 3 步已经加上数据清单和静态交付两个测试文件。
6. R3 本身，等 Owner 通知。检查表补了第 18 项（数据清单），第 11 项写细了。
7. 没有任何一个包用真实模型验证过。E、D、B 的效果要等 R3；C 只影响桌面版，R3 测不到它。

### 2026-10-03 — Codex 复核 E、D，完成 C、F（待 Claude 审核与 Owner 提交）

Owner 要求检查并完善 Claude 的 E、D、C、F 工作。本轮依次复核 E、D，补齐 C 接线和测试，最后完成 F；没有提交、推送、服务器操作、真实模型调用或 benchmark 运行。评分标准、数据、学习区域、60 次上限、沙箱和网络权限均未改变，其他并行改动保留。

**E：独立复核通过**

- 检查了两处 Coordinator 规则和 Search Expert 的咨询范围：按需咨询，与数据分析并行；咨询不分析任务数据，需要数值验证时交回 Coordinator。没有改掉已有代码工具。
- Coordinator 提示实测仍为 **4,999 字符**。本轮没有继续增加 Coordinator 提示。
- E、D 原有定向测试先独立运行：**25 passed**。

**D：发现并修复两项边界缺口**

- CSV 的旧计数按物理换行计算，带引号的多行字段会被误算成多条记录。先新增失败测试，再改为流式 `csv.reader` 计数，跳过表头和空白行；不把整张表读进内存。
- 文件删除后，如果没有其他文件需要重新探测，缓存不会更新；全部文件删除也会留下旧条目。先新增部分删除和全部删除两个失败测试，再让删除触发缓存清理，但不触发无必要的重新探测。
- 三个新案例修改前均失败；修复后 E、D 定向测试 **28 passed**。保留 Claude 的异步清单块位置，内容和限制与方案一致；没有把异步探测塞入同步 `_earlier_work`。

**C：完整说明已接线**

- `figure_reference.py` 的共享说明同时写入交互任务的 `.runtime/result-api.md` 和允许使用绘图 skill 的角色副本 `scientific-figure-design/API.md`；生成内容参与 skill 副本哈希。
- Expert 提示改为文件位置和“画第一张图之前读一遍”的短规则，移除旧内联 `FIGURE_API_CONTRACT`。静态模式不暴露接口、不生成这份说明。
- skill 的三个例子改为各自自包含、可运行的程序，未改学习区域。README 补充共享说明的位置。
- 校正说明中的两处细节：整数时间戳的拒绝针对显式时间轴，默认数值轴仍可用；分类标签省略时允许使用默认标签。未改绘图接口行为。
- 新测试独立枚举全部 **11 个公开图层方法**和 **7 种 plot_kind**，核对准确签名和说明；运行说明中的七个例子、skill 的三个例子并检查结果与预览；验证实际 Expert 提示、task/skill 同文和接口限制。
- C 修改前 **5 failed, 14 passed**，完成后 C 与 E/D、B 静态隔离定向测试合计 **60 passed**。这是静态隔离回归，不代表本轮完整复审了 B。

**F：只改说明与披露**

- `code_failures` 的说明改为观察到的类别，不据只读、超时或 kernel 消息直接归因。分类器实现及评分未改。
- `RUNNING.md`、`EVALUATION.md` 补齐普通 PNG 交付、额外 provider/压缩请求账本、预算影响行为、三种方法的搜索能力差异四项披露。明确这里的 Finch-local 没有文献代理，不将其等同于上游所有模式。
- 披露与归因测试修改前 **3 failed**；完成后该测试文件 **11 passed**。

**最终验证与限制**

- 全量测试：**954 passed, 8 skipped, 763 warnings，133.65 秒**；日志 `/private/tmp/oceanx-edcf-full-tests-20261003.log`。warnings 主要为现有 NumPy/NetCDF 弃用提示。
- 全量测试前后核对 **208 个 Python 文件的内容哈希**及 tracked diff 哈希，均相同。测试覆盖的就是最终代码；之后只更新本文件。
- 本轮新增/补齐的说明生成器、probe、对应测试及 evaluation 测试 Ruff 通过。对已有修改文件与 HEAD 比较，没有新增 Ruff 问题；既有问题见下一条 Log。
- 只在本机 macOS、合成数据和假模型/后端夹具中验证。未运行真实模型或 Linux 测试，未启动 R3；不能据此声称实际耗时改善。未做交互提示全部段落的逐段快照比较，已检查实际构建提示和静态模式隔离。
- A4、B、E、D、C、F 在部分源文件中重叠，其他 benchmark/reset/Finch 改动也仍在工作区。提交边界由 Owner 决定，本轮不擅自提交。

### 2026-10-03 — 方案外既有缺口：大型原生文件编辑路径缺少 EditResult 导入（未修改）

- Ruff 在 `src/oceanx/native_backend.py:127,135,138` 报告 `F821 Undefined name EditResult`。`ResearchSandbox._aedit_via_upload` 在上传失败、输出异常和成功分支均构造 `EditResult`，但模块没有导入它；触发这条路径时可能出现 `NameError`。
- 对 `git show HEAD:src/oceanx/native_backend.py` 运行同样检查，三处问题已存在，因此不是本轮 C 接线引入；全量测试通过也不覆盖该遗漏。
- 属于方案外情况，按规则只登记，未添加导入或修改这条编辑路径。请 Claude/Owner 决定是否另开最小修复及回归测试，不将本轮测试通过当作 R3 开跑授权。

### 2026-10-03 — Claude 实现 E、D；C 做了一半；F 没做（使用额度用完，在这里停下）

Owner 让我把 E、D、C、F 都做了。额度用完时 E 和 D 已完成，C 做了一半，F 没有开始。**没有提交，没有推送。**

**E（已完成，无独立审核）**

- `runtime.py`：研究树提示里“开头就启动文献咨询”改为“先做现有数据能回答的问题”；研究协调里改为“只有问题取决于 DatasetContext 没讲清的定义、方法或已发表机制时才咨询 Search Expert，与数据问题并行，不排在前面”。
- Coordinator 提示原来是 4,990 字符，限制是不到 5,000。现在是 **4,999**，只剩 1 个字符。为了放得下，我把规则合并成两句，并删掉了“用用户问题、DatasetContext 和一次咨询来搭树”这句复述性的话（研究树提示和证据规则里已有同样的意思）。以后再给 Coordinator 加字，要先腾地方。
- `team/profiles.py`：Search Expert 的说明加了三条范围：咨询只读资料并汇报，不分析任务数据；资料冲突或只有数值验证才能判断时，说明后停下，由 Coordinator 派给数据 Expert；只有委派明确要求复现或下载数据时才运行代码。没有去掉它的代码工具。
- 测试：`test_bounded_delivery_policy.py` 更新两处措辞断言并新增 1 个测试。修改前 2 个失败。

**D（已完成，无独立审核）**

- `analysis_probe.py`：新增 `describe_saved_file`。NetCDF 取变量、维度、units、long_name 和 title/description；CSV 取列名和行数（按行计数）；`.npz` 只读 `.npy` 文件头，对象数组标 `needs_allow_pickle`。读不出来的文件记为 unavailable，不影响其他文件。
- `expert_execution.py`：新方法 `describe_saved_data`。在沙箱里只读运行同一个探测脚本；outputs 在前、scratch 按最新在后，只描述前 12 个，其余只计数。缓存在 `<agent>/.runtime/data-index.json`，以（路径、大小、修改时间）为键，只重探改动的文件，消失的文件会被清掉。整体探测失败时抛 `ExpertCodeExecutionError` 且不写缓存。
- `graphs.py`：`_earlier_work` 拆成 `_earlier_keys` 和 `_earlier_work`（`_earlier_work` 的输出不变）。新增 `_saved_data_prompt`、`_saved_data_block`、`_saved_file_line`。限制：每个目录 12 个文件、每个文件 200 字符、总共 4,000 字符，并写明省略了多少个文件或目录。探测失败或超过 60 秒只记警告，Expert 照常启动。
- `runtime.py`：两个版本的 Expert 工作流规则（交互和静态）都加了一句：每个变量写 `units` 和 `long_name`，文件写一行 `title`。
- README 加了一段。
- **和方案的差别：** 清单放在 “Earlier steps…” 和 “earlier attempt” 两句之后的单独一块里，按目录分组；没有塞进 `_earlier_work`、`_earlier_attempt` 返回的行里。原因是这两个函数是同步的、现有测试直接调用它们，而探测要在沙箱里异步运行。内容和各项限制与方案一致。
- 测试：新文件 `tests/test_oceanx/test_saved_data_index.py` 共 13 个：探测三种格式；`.npz` 不读数组；脚本入口；服务的顺序、`limit`、缓存、只重探改动的文件、失败不缓存；行格式；各项上限；重复尝试看到自己的目录；探测失败和超时不影响 `build`；祖先节点按最近优先。变异检查：去掉提示接入后 2 个失败，缓存不读取时 2 个失败，随后已还原。

**C（做了一半，还没接线）**

- 已有：新模块 `src/oceanx/figure_reference.py`，`figure_api_reference()` 生成完整说明（约 16 KB）：规则、`ScientificFigure`/`panel`/`add_feature`/`save` 的签名、11 个图层方法的准确签名（用 `inspect.signature`）和说明、7 种 `plot_kind` 及其限制、调色板、每种 `plot_kind` 一个完整例子。7 个例子都手工跑通并保存了。草稿规则已写成直接用法（`DRAFT_RULE`）。目前没有任何地方 import 这个模块，不影响现有行为。
- 还没做，按顺序：
  1. `graphs.build`：交互模式里整块 “Figure API (complete; …)”（用 `FIGURE_API_CONTRACT`）换成短规则：画第一张图之前读一遍 Result API reference，它是完整的，不要读源码或试错；再接 `DRAFT_RULE`。静态模式不动。
  2. `native_backend.task_backend`：交互模式下 `result-api.md` 写 `figure_api_reference()`。
  3. 删掉 `expert_execution.FIGURE_API_CONTRACT` 和 `graphs.py` 对它的 import（没有测试引用它）。
  4. skill `scientific-figure-design/SKILL.md`：API 描述改为指向那份说明；它自己的三个例子要改成自包含、能运行的（现在用了未定义的数组）。
  5. 新测试文件 `tests/test_oceanx/test_figure_api_reference.py`：说明里有每个公开图层方法（introspection 取）和它的精确签名；有代码库声明的每种 `plot_kind`（`InteractiveViewContent.view_kind` 的取值）；每个图层方法都有说明（防止新增方法漏写）；每个例子在临时 `OCEAN_OUTPUT_DIR` 里运行并生成 `.nc` 和预览；skill 里的例子能运行；几条“限制确实被代码执行”的检查（`spatial_map` 没有 `valid_mask`、`spatial_map` 多一层、`heatmap` 做地图缺 units、`scatter` 有 `color_values` 没 `colorbar_label`、整数时间戳）；提示指向说明、`result-api.md` 等于生成的文本、不含 “In interactive mode”。
  6. README 一句，跑全量测试。注意 B 的 `test_a_static_run_shows_no_model_a_plotting_interface` 在交互模式下要求提示里有 “Figure API”，新的短规则要保留这个词。

**F（没有开始）**

- `evaluation/evaluate.py::code_failures` 的说明改成只描述类别，不归因。
- `RUNNING.md` 和 `EVALUATION.md` 写第 6 节 F 的四点。E 已实现，第 4 点可以写“OceanX 按需咨询”。

**验证**

- 全量测试 **929 个通过、8 个跳过**（B 之后是 914：D 新增 13 个，D 和 E 各新增 1 个测试）。测试前后工作区一致。
- 没有做：改动文件的 Ruff 比较；E、D 之后交互模式提示的逐段比较（这两个包有意改变了研究协调的两句、Expert 规则里的一句，以及重复尝试和子节点的清单块）；没有跑真实模型；只在 macOS 上测。

**提交范围（Owner 请看）**

- E、D：`src/oceanx/runtime.py`、`team/profiles.py`、`analysis_probe.py`、`expert_execution.py`、`research/graphs.py`、`README.md`、`tests/test_oceanx/test_bounded_delivery_policy.py`，新文件 `tests/test_oceanx/test_saved_data_index.py`。
- C 的一半：新文件 `src/oceanx/figure_reference.py`（没有被任何地方使用）。
- A4 和 B 仍未提交，和这些改动混在 `graphs.py`、`runtime.py`、`README.md`、`test_bounded_delivery_policy.py` 里。建议等 C 接线、F 做完以后一起提交，或者至少把 E、D 和 A4+B 放在同一次提交里。

### 2026-10-03 — Claude 实现 B（Codex 额度用完；待 Owner 提交）

Owner 说 Codex 的 5 小时额度用完了，让我直接实现 B。所以 B 是我写的，没有第二个人审核。

**改了什么（都按第 6 节 B，没有加范围）**

- 新文件 `src/oceanx/figure_delivery.py`：开关 `OCEANX_FIGURE_DELIVERY` 只在 `figure_delivery()` 里读取。空值是 `interactive`，写错（例如 `statik`）直接报错，不悄悄退回到会描述绘图接口的模式。另有 `static_figure_files()`：列出每个 Agent 的 `outputs/` 下任意层级的图片（`.png .jpg .jpeg .svg .pdf`），跳过 `_` 或 `.` 开头的文件名，不跟随任何符号链接。
- `task_results.py`：`static` 模式下 `list` 和 `get` 把这些图片列为 `kind="file"` 的结果，内容字段按方案：`agent_key`、`result_key`、`output_path`、`render_status: "static"`、`preview_file`、`workspace_files`，另有带大小和 sha256 的文件记录。结果按（路径、修改时间、大小）缓存。
- `cache_cleanup.py`：`static` 模式下这些图片和已发布视图一样受保护。
- `research/services.py` 和 `graphs.py`：`static` 模式下回执写 `Saved figures (cite these paths):`，每行是绝对路径和标题，不再出现 `Published results`。节点的 `output_refs` 记图片的结果键。
- 不暴露绘图接口，逐处换成静态版：Expert 工作流规则（`STATIC_EXPERT_WORKSTREAM_POLICY`，里面给了 matplotlib 存 PNG 的写法）、`graphs.build`（去掉 `Result API reference`、`ScientificFigure.save`、整块 Figure API、调色板、`[agent/result1]` 绑定段落、`.preview.png` 说明）、不写 `.runtime/result-api.md`（已有的旧文件会删掉）、`ocean_expert_run_code` 的描述、Coordinator 的引用规则和两段后缀、标准模式 Expert 提示里的 `.preview.png` 一句、skill 库里去掉 `scientific-figure-design`。
- 补图规则按 v1.3 重写，交互版和静态版措辞一致：条件句写成 “omitted a visual that the user explicitly asked for”，后面接 “A visual that you added yourself in an Expert assignment does not qualify.”。
- `run_oceanx.py`：`backend_environment` 把开关设为 `static`（覆盖 shell 里的任何设置），`arm_record` 记录 `figure_delivery`。`check_arm` 没有改，只记录。
- README 和 `RUNNING.md` 各加一段说明。

**证据**

- 新测试 `tests/test_oceanx/test_static_figure_delivery.py` 共 13 个。其中最重要的一个起一个真实的后端，对 7 种角色和模式（Coordinator 研究/标准、两个数据 Expert、文献 Expert、讨论伙伴）分别取出模型实际看到的全部文字：系统提示、所有工具的描述、整个 skill 库。`static` 下断言不含 `ScientificFigure`、`Figure API`、`result-api`、`Published results`、`bracket`、`Workbench`、`.preview.png`，`result-api.md` 不存在，skill 库里没有绘图 skill；`interactive` 下断言这些仍在，保证检查有效。
- 其余测试覆盖：开关取值；图片列表（深度、草稿、符号链接、scratch 不算）；结果记录的各个字段和重写后哈希变化；回执格式和 Expert 图的归属；缓存清理；skill 库；工具描述；两种补图规则一致。
- `test_native_subagents.py` 里 A4 的测试按计划更新了断言，并改名为 `test_visual_follow_up_is_only_for_a_visual_the_user_asked_for`（旧名字里的 “original user request” 已经不准确）。
- 基准测试：`test_run_oceanx_arms.py` 一个（环境和 arm 记录），`test_collect_oceanx.py` 一个：用真实的结果存储登记一张图，写进 `outputs.json`，收集后出现在 “Collected figures” 下，答案里引用的绝对路径被改写成可移植的链接，草稿图没有被收集。
- **变异检查：** 临时让开关失效后，11 个静态相关测试失败，交互相关的 84 个照常通过，随后已还原。
- **桌面版没有被悄悄改：** 用同一个脚本在 HEAD 和工作区各抓一遍 7 种角色/模式在 `interactive` 下的全部模型可见文字（177 段，含所有工具描述和 skill 文件）。唯一的差别是 Coordinator 两个系统提示里补图规则那一段，也就是 v1.3 要求的改动。
- 全量测试：**914 个通过、8 个跳过**（上一次 899，新增 15 个），测试前后工作区哈希一致。`git diff --check` 通过。改动文件的 Ruff 提示 20 条降到 14 条，没有新增。
- 这一轮抓到并修掉了一处真的漏洞：标准模式的静态 Expert 提示里还剩 `.preview.png`，因为原句在 “of a” 后换行，字符串替换没匹配上。现在改成把那一句参数化。

**和方案的差别（都是细节，请知悉）**

- 结果键保留扩展名（`<agent>/<路径>.png`），因为 `fig.png` 和 `fig.pdf` 要算两个结果；已发布视图的键是去掉扩展名的。
- `static` 下 Expert 提示里整段 “Your Agent key … `[key/result1]`” 去掉了，只留工作流规则里的一句“在 `report.md` 里紧跟结论写图片文件名”。
- 没有升 `OCEAN_RUNTIME_PROFILE_VERSION`：`interactive` 的权限和完成约定没有变，`static` 只用于全新的运行。
- `OceanExpertRunCodeTool` 的静态描述是在 `__init__` 里设置的实例属性，类上的交互描述不变。

**没有验证的**

- 没有跑真实模型。Expert 会不会把最终图存到 `outputs/` 而不是 `scratch/`，会不会引用回执里的路径，要看 R3 检查表第 11 项。
- 只在 macOS 上跑了测试。B 里没有依赖沙箱的逻辑，服务器上建议照常跑一遍全量测试。
- kernel 启动代码和结果运行器里仍然预加载了 `ScientificFigure`（按方案保留）。Expert 在沙箱里 `import oceanx` 理论上能看到，提示和工具里没有提它。

**提交范围（Owner 请看）**

A4 和并行工作都还没提交，所以 B 和它们改了同一批文件。

- 只属于 B：新文件 `src/oceanx/figure_delivery.py`、`tests/test_oceanx/test_static_figure_delivery.py`；改动文件 `src/oceanx/task_results.py`、`cache_cleanup.py`、`research/services.py`、`runtime.py`、`tools.py`、`native_skills.py`、`native_backend.py`、`benchmarking/tests/test_run_oceanx_arms.py`、`benchmarking/tests/test_collect_oceanx.py`。
- 和 A4 混在一起：`src/oceanx/research/graphs.py`、`tests/test_oceanx/test_native_subagents.py`、`README.md`、本方案。A4 的那两句话已经被 B 按 v1.3 重写，在同一处，没法干净分开。**建议 A4 和 B 合成一个提交**（提交名 `A4+B`）；如果一定要分开，需要用 `git add -p`，A4 单独的内容是我上一条审核里看过的那两句话和对应测试。
- 和并行工作（benchmark 重置、Finch）混在一起的两个文件，B 的改动块如下，用 `git add -p` 只选这几块：
  - `benchmarking/server/run_oceanx.py`：`LIBRARY` 后面新增的常量 `FIGURE_DELIVERY`；`backend_environment` 里的 import 和 `env[FIGURE_DELIVERY_ENV] = FIGURE_DELIVERY`（含文档字符串）；`arm_record` 里的 `"figure_delivery"`。`main` 拆成 `_main` 和 `configure_run(..., stack=stack)` 是并行工作的，不属于 B。
  - `benchmarking/RUNNING.md`：“OceanX review delivery” 一节里新增的 “Every OceanX attempt delivers ordinary images …” 一段。其余是并行工作的。
- 本次没有提交、没有推送，没有动并行工作的文件。

**下一个包是 E。**

### 2026-10-03 — Claude 审核 A4：通过，可以提交

- **实现符合方案。** `COORDINATOR_VISUAL_DELIVERY_POLICY` 加了两句：只有用户问题里明确要的图才有资格补图；Coordinator 自己在委派里加的图不算。标准和研究两种工作流用的是同一段文字。
- **没有越界。** 没改调用上限、研究策略和 Expert 的方法选择。Coordinator 仍然可以在第一次委派里请 Expert 出图，受限的只是那一次补图。
- **独立验证。** 去掉 `graphs.py` 的改动后，4 个新测试全部失败。全量测试 899 个通过、8 个跳过，测试前后工作区一致。
- **测试能说明什么。** 它检查的是提示里有没有这几句话，不能说明模型会照做。实际效果由 R3 检查表第 11 项来看：有没有补图任务，用户的问题是否要了那张图。
- **`static` 那两个测试参数现在不起作用。** `OCEANX_FIGURE_DELIVERY` 目前只有这个测试在设置，没有代码读取它，开关由 B 实现。这两个参数的用处是约束 B：静态版本必须保留这几句。
- **两处措辞留给 B 一起改，不影响本次提交。** 已写进第 6 节 B（方案 v1.3）。
  - “this follow-up” 出现在补图规则之前，读到时还没有所指。
  - “the original user question” 在桌面版的多轮对话里可能被理解成只有第一条消息。Coordinator 看得到整个对话，用户在后面的消息里才要图也应该算。benchmark 只有一条用户消息，不受影响。
- **B 开始之前要先处理一件事。** `benchmarking/server/run_oceanx.py` 里有并行工作的未提交改动，它依赖 `benchmark_run.py` 里同样未提交的改动，而 B 也要改这个文件。已写进第 6 节 B 的“开始之前”。
- **本次提交的文件。** `src/oceanx/research/graphs.py`、`tests/test_oceanx/test_native_subagents.py`、`README.md` 和本方案。另外 11 个改动文件和 1 个未跟踪文件属于并行工作，不在 A4 里。
- A2（`a3b9a4d`）和 A3（`cef4736`）还没有推送。
- 下一个包是 B。

### 2026-10-03 — Codex 完成 A4（待审核与 Owner 提交）

- A3 已按 Owner 指令单独本地提交为 `cef4736`，提交名 `A3`，仅包含下面列出的六个文件。
  本轮没有推送或服务器操作，其余 benchmark/reset/Finch 改动仍原样保留。
- 先在 `test_native_subagents.py` 写参数化回归测试，截取 `_coordinator_agent` 真正传给
  `build` 的提示后缀：标准、研究工作流各自在 `interactive`、`static` 环境值下验证。
  修复前四项均因缺少“原始用户问题”的补图约束失败：**4 failed、53 deselected**。
- 最小运行时改动仅为 `COORDINATOR_VISUAL_DELIVERY_POLICY` 的两句话：只有原始用户问题
  明确要求的图才符合那一次补图的条件；Coordinator 在 Expert 委派里自行增加的图不符合。
  两种工作流引用同一个规则；保留原有最多一次、同角色同节点、使用已保存证据的要求。
  没有改调用上限、研究策略、首次科学分析或 Expert 选择方法的权限。
- `README.md` 同步说明。当前静态交付开关尚未由 B 包实现；环境值测试仅确认这条共同
  约束不会因该配置而缺失，不声称静态图片交付已可用。测试是提示契约回归，不是模型遵从率测量。
- 针对性测试（native subagents + bounded delivery policy）：**67 passed**（2.49 秒）。
  第 1 节全量命令：**899 passed、8 skipped**（128.18 秒）。
  日志：`/private/tmp/oceanx-a4-full-tests-20261003.log`。沿用原生 Python 3.12.0 临时环境，
  未修改依赖或产品沙箱；测试前后 **203 份 Python 文件的 SHA-256 清单完全一致**。
- `git diff --check` 通过。修改源码与测试文件的 Ruff 提示与 `HEAD` 逐项一致
  （import 顺序、未使用 import 和旧的 noqa），无新增，未扩大范围去修复。
- **A4 保持未提交，停下等待审核与 Owner 提交。** 不开始 B，不启动 benchmark、
  科学分析或付费模型调用，不操作服务器。

### 2026-10-03 — Owner 授权提交 A3，然后开始 A4

- 本次提交仅包含审核通过的 A3：`task_results.py`、`expert_execution.py`、
  `research/graphs.py`、`test_explicit_figure_delivery.py`、`README.md` 和本方案。
  其余 benchmark/reset/Finch 改动保留，不纳入提交。
- 沿用下面已完成的独立审核与全量测试结果，不新增 A3 行为；C 包的措辞意见仍留给 C。
- 提交后只开始 A4，完成后停下等待审核与 Owner 提交，不启动 benchmark。

### 2026-10-03 — Claude 审核 A3：通过，可以提交

- **实现符合方案。**
  - `TaskResultStore._agent_views` 跳过文件名以 `_` 或 `.` 开头的已声明视图，子目录里的也一样。
  - 草稿文件和预览留在磁盘上，不删除。
  - 规则写进了 `FIGURE_API_CONTRACT`，提示和 `.runtime/result-api.md` 都会带上。
- **核对了会不会和 Expert 看到的信息矛盾。** 运行代码的工具只返回保存了哪些文件，不会说“已发布”。回执和 benchmark 收集器都通过 `TaskResultStore.list` 取结果，草稿在两处都被排除。
- **独立验证。** 去掉 `task_results.py` 的改动后，4 个草稿测试失败、3 个通过。全量测试 895 个通过、8 个跳过，测试前后工作区一致。
- **留给 C 包处理的一处措辞。** 草稿规则以 “In interactive mode” 开头，而 Expert 并不知道有“模式”这个概念。重写绘图说明时把它改成直接的用法：试验图用下划线开头的名字保存，最终图用普通名字。这不影响本次提交。
- A2 的提交 `a3b9a4d` 还没有推送。
- 下一个包是 A4。

### 2026-10-03 — Codex 完成 A3（待审核与 Owner 提交）

- A2 已按 Owner 指令单独本地提交为 `a3b9a4d`，提交名 `A2`，仅包含下面列出的四个文件。
  本轮没有推送或服务器操作，其余 benchmark/reset/Finch 改动仍原样保留。
- 先在 `test_explicit_figure_delivery.py` 写回归测试：`_draft.nc`、`.draft.nc` 以及
  子目录里的两种同名草稿，修复前都被列为正式结果：**4 failed、3 passed**。
- 最小过滤只在 `TaskResultStore._agent_views`：对声明的输出先验证相对路径，
  文件名以 `_` 或 `.` 开头就跳过，不读取它的 NetCDF，也不生成或返回结果记录。
  不删除草稿数据、预览或保存事件；普通文件名的交付流程保持不变。
- `FIGURE_API_CONTRACT` 新增一条共用的草稿规则，Expert 绘图提示引用这条规则；
  现有 `.runtime/result-api.md` 会随整个 contract 自动带上它。`README.md` 同步说明。
  没有提前实现 C 的完整接口说明，也没有改 A4、静态模式或科学分析逻辑。
- 针对性测试：**7 passed**（17.94 秒），覆盖根目录与子目录的两种草稿前缀、
  普通图正常交付、标题前缀不影响交付、重复列表与缓存，以及草稿与预览仍保留。
  原有“显式保存后后续执行失败，图仍保留”和“未声明的文件不列出”测试继续通过。
- 第 1 节全量命令：**895 passed、8 skipped**（131.29 秒）。
  日志：`/private/tmp/oceanx-a3-full-tests-20261003.log`。沿用原生 Python 3.12.0 临时环境，
  未修改依赖或产品沙箱；测试前后 **203 份 Python 文件的 SHA-256 清单完全一致**。
- `git diff --check` 通过，新增测试文件无 Ruff 提示。三个修改源码的 9 条 Ruff 提示
  与 `HEAD` 的提示逐项一致（未使用 import、import 顺序、旧时区写法及异常捕获），
  没有新增，未扩大范围去修复。
- **A3 保持未提交，停下等待审核与 Owner 提交。** 不开始 A4，不启动 benchmark、
  科学分析或付费模型调用，不操作服务器。

### 2026-10-03 — Owner 授权提交 A2，然后开始 A3

- 本次提交仅包含审核通过的 A2：`delegation.py`、`test_research_policy_loop.py`、
  `README.md` 和本方案。其余 benchmark/reset/Finch 改动保留，不纳入提交。
- 沿用下面已完成的独立审核与全量测试结果；不新增 A2 行为。
- 按 Owner 指令，提交后只开始 A3，完成后停下等待提交；不启动 benchmark。

### 2026-10-03 — Claude 审核 A2：通过，可以提交

- **实现符合方案。**
  - 等待结束后，显式的 `node_id` 仍不存在就返回方案规定的错误消息。
  - 拒绝发生在 `_prepare` 之前：不启动 Expert，不写委派记录，不改调用参数。
  - 只从描述推断出来的未知节点不拒绝。
  - 没有增加在回执阶段猜节点的逻辑。
- **独立验证。**
  - 去掉 `delegation.py` 的改动后，两个拒绝测试失败，其余通过。
  - 在真实的两层中间件链里（预算在外，绑定在内）：被拒绝的调用没有启动 Expert，研究树里没有它的 `delegated` 事件；合法节点照常运行。
  - 全量测试：891 个通过、8 个跳过。测试前后工作区一致。
  - `delegation.py` 没有 Ruff 提示。
- **记录两个小问题，都不在 A2 里处理。**
  1. 被拒绝的调用也被计入回执里的 `Expert assignments so far`。原因是预算中间件在调用开始时计数，它在绑定中间件外层。这个数字只是给 Coordinator 的参考，停止新委派靠的是时间，不受影响。如果 R3 里出现拒绝，再决定要不要改成只统计真正启动的委派。
  2. 桌面界面可能把重试的委派挂到被拒绝的那次调用上。`deep_runtime.py` 的 `pending_calls` 只在工具真正启动时才移除条目，被拒绝的调用会留在里面；之后参数相同的重试会匹配到这条旧记录，事件里带的是旧的调用编号。这只影响桌面界面的显示，不影响研究流程和 benchmark。预算拒绝早就有同样的情况。
- 下一个包是 A3。

### 2026-10-03 — Codex 完成 A2 拒绝部分（待 Owner 提交）

- 以已提交并推送 origin 的 A1 `991466e` 为基础，仅实现 A2，不开始 A3。
- 先写同步、异步回归测试：显式未知节点仍然调用了 handler，修复前结果为
  **2 failed、2 passed**；通过的两项确认推断未知节点仍按未绑定方式运行。
- 最小运行时改动仅在 `research/delegation.py`：保持 `NODE_WAIT_SECONDS` 和原等待流程，
  等待结束后，显式 `node_id` 仍不存在时返回方案指定的 `ToolMessage(status="error")`。
  在 `_prepare` 之前拒绝，不调用 handler、不创建委派或 attempt、不修改原调用参数。
  仅从描述推断的未知节点不拒绝；回执阶段没有增加猜节点或补挂报告的逻辑。
- `test_research_policy_loop.py` 覆盖同步、异步拒绝及推断未知节点继续运行；
  原“同轮新增节点被正确绑定”的测试保留，原“短等待后未绑定”的测试调整为
  推断未知节点场景并覆盖两条调用路径。已有合法节点、非 task 工具和上下文恢复测试通过。
  `README.md` 同步说明显式与推断节点的不同处理方式。
- 针对性测试（policy loop + native subagents）：**77 passed**（5.06 秒）。
  全量测试按第 1 节指定命令执行：**891 passed、8 skipped**（122.48 秒）。
  日志：`/private/tmp/oceanx-a2-full-tests-20261003.log`。沿用临时原生 Python 3.12.0 环境，
  未修改项目依赖或产品沙箱；测试前后 `src/`、`tests/`、`benchmarking/` 中的
  **203 份 Python 文件的 SHA-256 清单完全一致**。
- `git diff --check` 通过；`delegation.py` 无 Ruff 报错。测试文件的 import 顺序及
  单元素切片两条 Ruff 提示在 `HEAD` 上同样存在，无新增，未自行修复。
- 本轮其余 benchmark/reset/Finch 未提交改动原样保留。没有提交、推送、服务器操作，
  没有启动 benchmark、科学分析或付费模型运行。**停在 A2，等待 Owner 提交与 Claude 审核。**

### 2026-10-03 — Owner 授权提交 A1；服务器运行中，暂不拉取

- Owner 要求以 `A1` 为提交名推送 origin 并在服务器拉取。
- 提交范围仅为审核确认的 A1：`graphs.py`、`test_native_subagents.py`、`README.md`、
  本方案，以及 `RUNNING.md` 的报告交付段落。工作区其余 reset、Finch 等变动不纳入。
- 提交前复跑 A1 的针对性测试：**53 passed**（2.33 秒）；Claude 已完成当前工作区的
  独立全量复核，见下一条记录。本轮不新增运行时修改、不开始 A2、不启动 benchmark。
- 服务器只读检查：`/home/mafzhang/code/OceanX` 在 `main`，工作区干净，当前为
  `60a5ea5`；但存在 PID `810101` 的 `python benchmarking/server/run_claude.py`。
  按第 1 节“运行进行中不改代码”的规则，不能在它运行时 pull，且没有中断该运行的授权。
  先提交推送，再复查；若仍在运行，服务器同步留待 Owner 处理，不自行中断或重启。

### 2026-10-03 — Claude 复核 A1（含 v1.2）：通过，可以提交

- **v1.2 的补充符合方案。** `_attempt_stop_reason` 由 `_missing_report` 和沿用原报告的回执共用。沿用原报告且没有结束语时，回执末尾写明没有结束答复和停止原因。工具乱码不会被转发。
- **我用上次暴露缺口的场景重新跑了真实代码，三种情况的回执都正确，原报告都没有变化：**
  - 用满 60 次调用、最后输出乱码：`gave no closing answer: it reached its 60-call limit.`
  - 调用 3 次后停在工具调用上：`gave no closing answer: it stopped after 3 model calls.`
  - 只说一句结束语：`ended with: <结束语>`
- **`README.md` 的说法已改准确，`RUNNING.md` 同步。**
- **全量测试：888 个通过、8 个跳过。** 测试前后工作区一致，这个数字对应当前整个工作区，包括下面的并行改动。
- **A1 的文件：** `src/oceanx/research/graphs.py`、`tests/test_oceanx/test_native_subagents.py`、`README.md`、本文件，以及 `RUNNING.md` 里 “OceanX review delivery” 一节开头的那一段。
- **并行改动不属于 A1，也不在本方案内，建议单独提交。** 涉及 `benchmark_run.py`、三个 `run_*.py`、`finch_worker.py`、对应的测试，以及 `RUNNING.md` 里的 `--reset` 段落。内容是实验的 `--reset` 归档、运行期间持有实验锁、Finch 的交付检查和请求参数记录。我只粗看过：与本方案没有冲突，测试一起通过。没有做完整审核。
- 下一个包是 A2 的“拒绝”部分。

### 2026-10-03 — A1 v1.2 收尾检查：额外的并行改动

- 最终工作区检查发现本轮开始时还没有的 5 份额外变动：
  `server/benchmark_run.py`、`server/run_claude.py`、`server/run_oceanx.py`、
  `tests/test_benchmark_run.py`、`tests/test_run_claude.py`（均在 `benchmarking/` 下）。
  它们不是本轮 A1 修改，未编辑、回退或修复。
- 三份源码的修改时间为 18:58:29 JST；全量测试日志结束于 18:59:20 JST；
  两份测试文件分别修改于 19:00:03 和 18:59:37 JST。因此测试期间和结束后工作区
  仍在变化，**882 passed、8 skipped 是本次执行的结果，不是对最终整个工作区的
  一致快照验证**，尤其不覆盖结束后新增的测试修改。
- 按 Owner 要求仅记录，不扩大 A1。上述改动应由 Owner 另行审核处理；本轮停下等待提交。

### 2026-10-03 — Codex 补齐 A1 v1.2（待 Owner 提交）

- 按 Claude 的 A1 审核，仅补“提交前要补的两处”，不开始其他包。
- 先更新无结束语的回归断言，并加入第 60 次仅输出工具乱码的场景；补运行时逻辑前，
  两种情况均因缺少回执末尾的说明而失败：**2 failed、6 passed**。
- `graphs.py` 提取 `_attempt_stop_reason`，供 `_missing_report` 和沿用原报告的回执共同
  使用。沿用原报告且无可用结束语时，回执末尾注明没有结束答复及停止原因，
  工具乱码不转发；原报告内容、文件 revision、研究树 Summary 和报告路径均不受影响。
- 修正 `README.md` 原来“结束语一律保存为报告”的表述；`RUNNING.md` 同步注明
  没有结束语时的回执说明。三种已批准的报告保存例外保持不变。
- 针对性测试：**53 passed**。按第 1 节的全量命令执行：**882 passed、8 skipped**
  （136.81 秒）。沿用本机临时 Python 3.12.0 测试环境，获准在 Codex 执行限制外执行
  假模型及系统沙箱测试，未修改项目依赖或 OceanX 沙箱规则。
  完整输出：`/private/tmp/oceanx-a1-v12-full-tests-20261003.log`。
- `git diff --check` 通过；Ruff 仍是初版审核中确认的 4 条原有提示，无新增，不处理。
  本轮开始时已有的 Finch 源码和测试改动原样保留，未追加 Finch 修复。
- 仅在本节记录情况，没有重新创建 `CODEX_HANDOFF.md`。没有提交、推送、服务器同步，
  没有启动 benchmark、科学分析或付费模型运行。**停在 A1，等待 Owner 提交。**

### 2026-10-03 — Claude 审核 A1：通过，提交前补两处

**核对结果**

- 实现与方案一致：没改报告时沿用原报告；三种例外才把结束语存为报告；研究树拿到的是原报告的 Summary；结束语只出现在回执末尾。
- 我独立复现了 Codex 的数字：去掉 `graphs.py` 的改动后是 3 个失败、5 个通过；全量测试 879 个通过、8 个跳过（多出的 1 个跳过来自后来出现的 Finch 测试文件，与 A1 无关）。
- 结束语放在 `Report:` 一行之后，比我原先设想的位置更好：界面上的摘要不会混进这句话。
- 每次尝试都在 `report-history` 里留一份它交付的报告，沿用原报告时也留。可以接受。注意：`run_record` 里的“报告版本数”因此表示“交付过报告的尝试数”，内容可能相同。

**提交前要补的两处**

1. **没有产出的重复尝试要在回执里写明（v1.2，方案原文漏了）。**
   - 现状：节点已有报告，重复尝试用满 60 次调用、最后只输出工具乱码时，回执只有原报告的摘要和路径，和成功交付一模一样。我用真实代码确认了这一点。
   - 修改前这种情况的回执是 `Result: No report — it reached its 60-call limit ...`，所以这是一处退步。
   - 做法见第 6 节 A1 里标了“v1.2”的两条。现有测试里 `("report", "ocean_process_expert", "", False, "report")` 这一例要改成期望新的那一行。
2. **`README.md` 的一句话现在不准确。** “An Expert that ends without saving it delivers its closing reply, which the backend saves as `report.md`” 要改成和 `RUNNING.md` 新增段落一致的说法：问题已有报告时，沿用原报告，结束语只进回执。

**不用改的**

- 4 条 Ruff 提示在 `HEAD` 上就有，A1 没有新增，不处理。
- `test_finch_failure_replay.py` 不属于 A1，提交时分开处理。

**关于 `CODEX_HANDOFF.md`**

它被重新建出来，是因为转给 Codex 的那段话里还写着这个文件名，那是我的疏漏。它的两条记录已经原文搬到下面，文件已删除。以后的额外情况只写进本节。

### 2026-10-03 — Unrelated file appeared after A1's full test run（Codex，原文，自 `CODEX_HANDOFF.md` 搬入）

- The full-suite log finished at 18:44:33 JST with 879 passed and 7 skipped.
- The final working-tree check then found a new untracked file,
  `benchmarking/tests/test_finch_failure_replay.py`, modified at 18:45:33 JST.
  This file was not created or edited by the A1 work and was not in that test collection.
- It is outside A1; left untouched and not included in A1's verified changes. The
  Owner should keep it separate when committing this package. No Finch fix was attempted.

### 2026-10-03 — A1 validation: existing lint findings（Codex，原文，自 `CODEX_HANDOFF.md` 搬入）

- Ruff reports four findings in the two Python files touched by A1: import ordering
  in both files, an unused `ToolRegistry` import, and an unused `BLE001` suppression
  in `research/graphs.py`.
- Checking the exact `HEAD` contents with the same Ruff interpreter reproduces all
  four findings. A1 adds no finding; none of these pre-existing issues was modified.
- Decision deferred to the Owner/Claude; do not broaden A1 to include lint cleanup.

### 2026-10-03 — A1：保留未更新的报告（待 Owner 提交）

- 先写回归测试，未改运行时代码时结果为 **3 failed、5 passed**：完整报告被
  `The figure is saved.` 覆盖；无结束语时原报告未交付；续做提示缺少保留报告的规则。
- 最小运行时改动仅在 `src/oceanx/research/graphs.py`：未更新报告时读取已有报告；
  仅在 A1 批准的三种情况把结束语存为报告。其他情况下保持原文件和文件 revision 不变，
  回执与研究树使用原报告 Summary，结束语仅追加在 Coordinator 回执末尾。
  `_earlier_attempt` 明确只更新本次改变的部分，不重写原报告。
- `tests/test_oceanx/test_native_subagents.py` 新增 7 个参数化场景，覆盖三种例外、
  无结束语、实际更新报告、原文件不变、研究树摘要不混入结束语及 attempt 报告副本。
  同步更新 `RUNNING.md` 的交付说明。
- 针对性测试：**52 passed**。全量测试按第 1 节指定命令执行：**879 passed、7 skipped**
  （136.20 秒）。使用本机临时原生 Python 3.12.0 环境，未改项目依赖配置。
  首次受 Codex 执行限制导致端口及系统沙箱相关失败；获准在该限制外重跑后全量通过，
  未修改 OceanX 沙箱规则。完整输出：`/private/tmp/oceanx-a1-full-tests-permitted-20261003.log`。
- `git diff --check` 通过。额外发现的 4 条原有 Ruff 报错已与 `HEAD` 对照确认，
  按 Owner 本次要求记入 `CODEX_HANDOFF.md` 的 Log，未自行修复。
  全量测试结束后另出现未跟踪的 `test_finch_failure_replay.py`，不属于本次 A1，
  未修改且未纳入本次已验证范围，已在同一 Log 记录，提交时需单独处理。
- 没有提交、推送或服务器同步，没有启动 benchmark、科学分析或付费模型运行。
  **停在 A1，等待 Owner 提交和 Claude 审核，不开始 A2。**

### 2026-10-03 — 纳入全部本地改动，建立统一优化基线

Owner 要求将本地全部现有改动提交、推送并同步服务器，后续在该完整版本上优化。
本次纳入 A2 已有的节点等待机制及其两个测试；这不表示 A2 的拒绝逻辑已经实现。
计划与诊断文档、Finch 超时接入修复已分别随 `b3106c1`、`b2bc184` 提交，均属于同一条
`main` 历史，不是两个分叉版本。本轮不额外实施 A1–F，不重启或重跑 benchmark。
Finch 相关检查为32项通过、3项 Linux 测试跳过；节点等待机制在服务器同步后执行针对性测试。

### 2026-10-03 — 交接文档并入本文件

`CODEX_HANDOFF.md` 里仍然有用的内容已经并入本文件，原文件已删除。
`OCEANX_E10_DIAGNOSIS_2026-10-03.md` 里提到 `CODEX_HANDOFF.md` 的地方，对应内容在本文件第 5 到 7 节。

### 2026-10-03 — Documentation-only review handoff（Codex，原文）

- Updated the E10 issue record's historical/current version boundaries and added the
  scientific-delivery versus interactive-publication coupling analysis.
- Added pinned OpenScience source references, verified persistence/viewer behavior and
  explicit limitations; added the review questions and requested planning output above.
- Preserved Claude's existing binding patch, tests and section 4b. No runtime changes,
  server actions, new experiments, automated Claude invocation, or commit/push performed.
- Validation: document diff and whitespace checks only; no runtime tests rerun for these
  documentation edits. Server scheduling evidence and post-fix behavior remain to verify.
