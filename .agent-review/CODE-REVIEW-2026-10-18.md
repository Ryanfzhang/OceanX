# OceanMind-v2 评审：代码整洁度 / 原生 LangGraph·DeepAgents 使用度 / 前端交互便利度

- 评审对象：`/Users/ryanzhang/Code/OceanMind-v2`，commit `89a456a`（工作区评审前干净）
- 评审日期：2026-10-18
- 约束（按你的要求）：**只评估，不改任何产品代码；不触碰智能体之间的交互逻辑，也不触碰 skill / tool 学习逻辑**
- 评审方式：3 路并行深审（原生框架 / 后端整洁度 / 前端交互与代码）+ Lead 独立复核；所有关键结论都回到 `path:line` 或实测命令验证
- 本轮唯一写入：`.agent-review/`（本报告 + 3 份明细报告，未跟踪）。三份明细见文末。

---

## 0. 结论摘要

**一句话**：这是一个「方向正确、文档密度极高、工程骨架专业」的 v2 重构，native 迁移是真实的；但它处在**大重构后的半清理状态**——核心运行时干净，外围有上帝类、纸面门禁、遗留前端与仓库脂肪；前端骨架专业但有几个用户可直接撞上的硬伤，且交互回归测试网已被删除。

| 维度 | 评分 | 一句话判断 |
|---|---:|---|
| 原生 LangGraph / DeepAgents 使用度 | **8 / 10** | 真迁移，不是包装话术；自研大多有正当理由，风险集中在私有 API 与「后台 Expert」越界 |
| 后端代码整洁度 | **6.5 / 10** | agent/runtime 核心约 8 分；`store.py`/`router.py` 两个上帝类、`mypy strict` 假门禁、仓库卫生欠账把它拉到 6.5 |
| 前端交互便利度 | **6 / 10** | 三栏工作台/流式/停止/双语/图表工作台都在，但 3 个 S1 硬伤 + 缺快捷键与失败恢复 + 中文覆盖不全 |
| **总体** | **7 / 10** | 可交付，但「好用」和「可长期维护」都还差一层收尾 |

**直接回答你的三个问题**

1. **代码是否足够整洁？** 核心链路（`deep_runtime.py`、`research/graphs.py`、`native_backend.py`、`runtime.py`）整洁度和注释质量高于同类原型，`router` 不写 SQL、`store` 不碰网络、无裸 `except`、运行时 import 环为 0；但整体不算「整洁」：`store.py` 4165 行 / 140 方法 / 26 表，`router.py` 3890 行 / 86 方法 / 35 分支 `isinstance` 派发，加上纸面类型门禁与仓库遗留，属于**中等偏上、有明显结构性债**。
2. **是否尽量用原生？** **是。** 旧 orchestrator / multi_agent 已删除，生产只有「Agent Server 跑 `coordinator` 图」一条执行路径；`create_deep_agent`、native `task` 子图、`skills=`、native summarization、`astream_events`、Agent Server checkpointer、`ModelCallLimitMiddleware`/`ModelRetryMiddleware`、`BaseSandbox` 都在用。剩下的自研多数是产品/沙箱/UI 投影必需（SSE 投影、receipt、技能快照、事件总线），真正问题只有 3 组（见 §2.4）。
3. **前端交互是否足够方便？** **骨架方便、细节不够。** 三栏可调工作台、流式输出、停止、双语、语音输入、地图/图表/交互图工作台都在；但有 3 个用户可感知的硬伤（空结果也常驻地图并占 42vw、后端崩溃后卡在「运行中」、欢迎页入口卡片点了没反应），以及无命令面板/快捷键、失败无重试、中文模式右栏/图表全英文、e2e 回归网被删。

---

## 1. 范围、方法与局限

- 后端：`src/oceanx` 共 105 个 `.py` / **34,615 行**；`tests` 74 文件 / 16,633 行 / **840 个用例**。
- 前端：`frontend/ocean-desktop`（Electron + React 主客户端）、`frontend/packages/ocean-client`、`ocean-ui`、`frontend/ocean_terminal`（遗留）。源码约 19k 行（含测试）。
- 实测：`pytest --collect-only` = 840；`mypy strict` = 893 errors / 65 files（正确包解析后）；`ruff` 全量 112–135 处；前端 `tsc --noEmit` = 0 错误。
- **局限（如实说明）**：
  - 未跑全量 `pytest`（只收集），未跑真实模型/真实桌面端会话；动态结论来自最小探针 + 上游包源码核对。
  - 前端 `vitest` 在**本机当前环境**跑不起来：Node 21.6.1 < vite 8 要求的 `^20.19 || >=22.12`（`node_modules/vite/package.json`）。这本身也是「无 CI 导致测试健康无人看守」的证据。
  - `frontend/ocean-desktop/tests/*.spec.ts` 已被删除，仓库里的 10 张视觉快照是**旧版本**（快照里品牌是 OceanMind，当前代码是 OceanX），因此本报告不依据快照判断像素级 UI。

---

## 2. 问题一：原生 LangGraph / DeepAgents 使用度（评分 8/10）

### 2.1 结论：native 迁移是真的

- 旧调度层已删除：`git ls-files src/oceanx/team` 只剩 `__init__.py / models.py / profiles.py`；历史 commit `d496fcb` 删掉了 orchestrator 与 multi_agent。
- 生产执行路径唯一：`src/oceanx/research/gateway.py:53-100` 用 `langgraph_sdk` 客户端创建并 join Agent Server run；`src/oceanx/research/server.py:21-31` 用 `run_server` 起内嵌服务；`langgraph.json:2-5` 只注册 `coordinator`。
- 本地编译图只存在于测试 fixture（`tests/test_oceanx/graph_fixture.py`），**不存在生产双引擎路径**。`agent.py` 与 `gateway.py` 不是重复实现，是「构造 vs 流式订阅」。

### 2.2 确实在用的原生能力

| 原生能力 | 证据 |
|---|---|
| `create_deep_agent`（含 `skills=`、`permissions=`、`subagents=`） | `deep_runtime.py:11,349-373` |
| 原生 harness profile（改 `task` 描述、关默认 generalist） | `deep_runtime.py:14-18,60-70` |
| native `task` 子图（`CompiledSubAgent`） | `graphs.py:1174-1176` |
| native summarization（未替换、只做计量不展示） | `deep_runtime.py:197,204-234` |
| `astream_events(v2)` + 用 `parent_ids` 屏蔽子图内部事件 | `deep_runtime.py:180-195` |
| Agent Server checkpointer / run / auth | `gateway.py:19-23,77-97`、`server.py:21-31`、`auth.py:5-14` |
| `ModelCallLimitMiddleware` / `ModelRetryMiddleware` | `graphs.py:417-439`、`provider_retry.py:14,27-32` |
| `BaseSandbox` / `CompositeBackend` / `FilesystemBasedBackend` | `native_backend.py:54,223`、`native_skills.py:13,102-106` |
| 原生取消语义 `cancel_on_disconnect` | `gateway.py:85-97` |

### 2.3 自研但**有正当理由**（不建议为了「更原生」去改）

| 自研部分 | 为什么正当 |
|---|---|
| SSE → protocol v2 事件投影（`deep_runtime.py:180-346`、`gateway.py`） | Agent Server 的序列化格式不能直接给 Electron UI；这是形式转换，不是第二执行引擎 |
| Expert receipt / handoff 三段式（`services.py:41-81`） | native task 只回最后一条 AIMessage；`response_format` 在 `CompiledSubAgent` 上不可用（上游会报错），而 UI 需要 Published results / Saved figures / Report |
| 技能内容寻址快照 + lesson 仅写保留区（`native_skills.py:25-99`） | 原生 `skills=` 只接受目录前缀，不支持「不可变快照 + 人工批准后注入」 |
| sandbox 文件后端（`native_backend.py`） | 必须复用现有 OS sandbox 与持久内核；`BaseSandbox` 子类化是官方姿势 |
| 事件总线（`backend/events.py:91-130`） | 多传输、每传输独立 sequence、workspace 广播，原生无对应物 |
| 操作幂等表 / tool_call 投影（`schema.sql`、`store.py`） | 是崩溃窗口补丁，不是会话 checkpoint 的替代 |
| `research/tree.py`、`toolbook.py`、`lessons.py` | 与 agent 生命周期解耦；tree 明确「不调度 agent」，与 README 声明一致 |

**特别说明**：`frontend` 之外，你点名的几对「疑似重复」经核对**都不是重复**，不要合并——`protocol/v2/models.py` vs `desktop_contract.py`（契约常量 ← 传输模型）、`task_results.py` vs `artifacts/`（任务输出视图 vs 工作区版本化制品）、`native_skills.py` vs `skills.py`（快照 vs 发现）、`lessons.py` vs `policy.py`（学到的建议 vs 版本化策略）、`agent.py` vs `gateway.py`（构造 vs 订阅）、`review.py` vs `reviews.py`（学习库门面 vs 外部评审输入）。

### 2.4 三组真正的问题（S1）

**S1-1 依赖 deepagents 私有 API，升级必碎。**
共 6 处（明细见 `native-usage.md` §3）：
- `native_backend.py:27-33`：`_build_edit_tmpfile_cmd`、`_get_backend_read_file_type`、`_map_edit_error`、`_parse_read_output`（`import oceanx.native_backend` 就会 ImportError → 所有 Expert 建图失败）
- `deep_runtime.py:355`：`deepagents._models.get_model_provider`
- `deep_runtime.py:372`：`FilesystemMiddleware(..., _permissions=...)`（上游 docstring 明说「Marked private for now」）
- `graphs.py:21-24`：`FilesystemState` / `SummarizationState` / `SkillsState`（半私有）
- `services.py:159`：依赖内部 `configurable["ls_agent_type"] == "subagent"`——**改名不报错，但会让所有 Expert 退化为 Coordinator 的 thread_id，文件/内核目录隔离静默失效**
- `deep_runtime.py:197` / `metering.py:45`：依赖 langchain 内部 `lc_source == "summarization"`

版本对照：`pyproject.toml` 锁定 `deepagents==0.7.9`，PyPI 当前最新为 **0.7.28**（同日核对），`0.7.28` 要求 `langchain>=1.4.6` 而当前是 1.4.0——升级不是随手可得，私有 API 会先付代价。

**S1-2 自研「后台 Expert」越过原生 tool-call/超步边界。**（`background_experts.py:115-121,260-302`）
动机是真实的：native `task` 是同步语义，同一批 Expert 要等最慢一个（文件头有 Q08 的数据）。但实现上：
- Expert 在父图 tool 节点返回**之后**继续跑（`asyncio.ensure_future`）；
- 子图完成时 native `task` 本应通过 `Command(update=...)` 写回父状态，OceanX 在「仍在运行」分支只返回新造的 `ToolMessage`，**原生 Command 的 state 更新被丢弃**；
- `_kept_waiting()` 直接给 AIMessage 注入一个模型从未生成的 `await_experts` tool_call（`background_experts.py:285-302`）——trace / metering / 重放会看到伪造的模型决策。

这条**不建议现在改**（它会改变智能体之间的交互时序，正好在你的禁区内）；建议只补「并发 + 崩溃 + 重启」回归测试并在文档里把「同步 task」措辞改准确。

**S1-3 「skills / references 只读」只到工具层，shell 层不成立。**
`skill_permissions()` 只让原生文件工具 deny 写 `/skills/**`（`native_skills.py:109-110`），但 Expert 同时有 `execute` 和持久 Python 内核，而任务技能快照位于 `work_root/.runtime/skills`，`work_root` 正是 sandbox 的 `writable_roots`（`native_backend.py:77`）。因此 shell/内核可改写本任务快照，`README` 的 read-only 声明在 shell 层不成立。影响限于单机单任务，但属于「声明与实现不一致」，建议修。

### 2.5 S2 / S3（摘要）

- **S2**：全局可变并发池 `_EXPERT_SLOTS` 会被「最新请求」resize，并发任务互相改限流（`graphs.py:126-142,1254`）；团队视图 / 取消集合是进程内内存，与原生 checkpoint 无关联（`router.py:285,2938-3030`）；**60 次模型调用预算可被绕过**——`wrap_model_call` 里二次 `handler()`（`graphs.py:487-495`、`tool_calls.py:66-72`）会让真实调用次数大于 `ModelCallLimitMiddleware` 计数（`run_limit=1` 探针已实证）；取消先提交 durable 终态、再靠 disconnect 让服务器停 run（`router.py:2854-2885`），存在「记录已取消但仍有副作用」窗口。
- **S3**：`scripts/probe_expert_round.py` 引用已删除的 `ExpertPreparation/order/save_answer`，今天必然失败；`graphs.py:1321-1334` 导出的 `physics/statistics/literature/discussion` 未在 `langgraph.json` 注册，生产无引用；`parse_expert_receipt` 用正则回读自己生成的格式，格式一改 UI 静默退化。

### 2.6 建议（全部不触碰 agent 交互逻辑）

1. 加一个 CI smoke：`python -c "import oceanx.research.graphs, oceanx.native_backend"` + 用固定样本跑一次 `build_deep_agent_graph`（专防私有 API 碎裂）。
2. 逐步替换私有依赖（顺序：P1 sandbox helper → P2 `_models` → P3 `_permissions` → P4 state 类），`services.py:159` 改为显式身份传递。
3. 修 S1-3 权限闭环：把技能快照移出 `writable_roots`，或在 `aexecute` 前做路径 deny。
4. 「后台 Expert / 预算计数 / 取消语义」三项**只补测试和文档**，行为改动留给你单独决策。

---

## 3. 问题二：代码是否足够整洁（评分 6.5/10）

### 3.1 做得好的部分（先给公道）

- **职责没有越权**：`router.py` 无 `sqlite3`、无 SQL（只在 `:1458` 拼了个文件名）；`store.py` 无 HTTP/WebSocket；SQL 全参数化，唯一 f-string 是表名白名单。
- **事务与并发基础正确**：单连接 + `RLock` + `BEGIN IMMEDIATE`（`store.py:420-427,475-485`）。
- **运行时 import 环为 0**（6 个静态环全部靠 `TYPE_CHECKING` / 函数内 import 打破——这是技巧，但至少没崩）。
- **错误处理基本合格**：裸 `except:` 0 处；宽泛 `except Exception` 49 处中 17 处有解释性 `noqa`，多数保留堆栈；`from exc` 包装使用正确。
- **风格统一**：`Optional` 0 处，已全面 PEP 604；无 mutable default / 类级可变默认值；`ContextVar` 用法正确。
- **测试规模健康**：840 用例、74 文件、测试/源码行比 0.48，静态扫描无真实网络/真实模型调用（`httpx.MockTransport`、`.invalid` 域名、缩短的超时）。
- **文档密度罕见**：模块 docstring 解释「为什么」而不只是「是什么」，例如 `background_experts.py:1-13`、`toolbook.py`、`deep_runtime.py`。

### 3.2 结构性债（S2）

**两个上帝类，必须拆，但可以低风险拆：**

| 文件 | 规模 | 拆法（保公共导入路径） |
|---|---|---|
| `backend/store.py` | 4165 行 / 1 类 / 140 方法 / 26 表 / 168 条 SQL | 拆成 `store/` 包（requests、tasks、interactions、artifacts、disclosure、usage、code_executions、tool_calls、rows），`RequestStore` 用 mixin 组合保持门面；13 个模块 + 8 个测试的 `import` 不用改 |
| `backend/router.py` | 3890 行 / 86 方法 / 35 分支 `isinstance` 派发 / 270 行 `_execute_agent_request` | 三步：①先抽纯事件构造（`:3644-3890`，零 I/O）；②`_dispatch` 改 `{RequestType: handler}` 表；③按域拆 handler，`_execute_agent_request` 最后动且先补 characterization test（它正好在禁区边缘） |

**包边界是名义上的**：`backend` 既被 core 依赖（10 个 core 模块 `import backend.store`），又依赖 core（`router` 顶层 import 26 个 `oceanx.*`），`artifacts/service.py:12` 反向依赖 `backend.store`。`backend` 实际是「数据层 + 传输层混在一起的隐式共享内核」，不是分层边界。**低风险做法**：用 `import-linter` 冻结现状（只禁止新增反向边），不要一次性大搬迁。

### 3.3 门禁是「纸面严格」（S2，这是整洁度问题的根）

| 声明 | 实际 |
|---|---|
| `pyproject.toml:105-107` `mypy strict = true` | 无 `make typecheck`（Makefile 的 `typecheck` 是前端 tsc）、无 CI；实测 **893 errors / 65 files**；缺 `src/oceanx/py.typed` 额外制造 293 条噪声 |
| `make lint` | `RUFF_TARGETS` 只列 10 个目标（8 文件 + sandbox + 1 测试）→ 该范围 `All checks passed!`，但全量 112–135 处（含 6 个未使用 import、1 个未定义名字） |
| CI | `.github/workflows/` 只有 `desktop-signed-release.yml`（发布签名），**没有 test/lint/typecheck 工作流** |
| 契约生成 | 有 `make test-contract`（协议 JSON + TS 生成），当前三份产物与代码一致，但不在 CI 里，无法防漂移 |
| 前端测试 | 37 个 vitest 文件 / 约 197 个用例，本机因 Node 版本起不来；e2e spec 已删（见 §4.4） |

**判断**：真正要修的不是「把 893 个错误全修完」，而是**先有门禁**——加 `py.typed`、把 `mypy` 冻结当前基线（只要求不新增）、`ruff --fix` 后扩到全量、CI 跑 `pytest + ruff + tsc + test-contract`。

### 3.4 唯一的确定性 bug（S1）

`src/oceanx/cli.py:279` 的 `ocean export` 使用 `RequestStore(paths.database)`，但文件顶部没有该导入（已实测 `ruff --select F821` 唯一命中，且 `vars(cli)` 中不存在该名字）→ 该命令运行时 **NameError**，且无测试覆盖。修复一行即可，建议顺手补 CLI 冒烟测试。

### 3.5 死代码 / 遗留 / 仓库卫生（S2–S3）

| 资产 | 现状 | 建议 |
|---|---|---|
| `frontend/ocean_terminal/`（13 文件）+ `src/oceanx/_ocean_terminal/dist/ocean-terminal.mjs`（**1.5MB 已提交构建产物**） | 桌面 / Python / CLI 全无引用；`CHANGELOG.md` 自己写着 "Removed … its terminal frontend"；`.gitignore` 还专门给它开入库例外；旧 release checksums 证明它被打进 sidecar | 删除；`.gitignore` 例外同步移除 |
| `benchmarking/` | 737 tracked 文件 / **177MB**（`reviews/` 176MB：547 张 PNG + 1.5MB HTML），git pack 168MB | 大产物走 LFS / 发布附件，保留 tasks/fixtures/server 代码 |
| `release-metadata/` | 10 份 `macos-x64-0.1.0*` 快照 / 30 文件 / 4.6MB，而版本已 0.1.5 | 留最近一份样例，其余 CI artifact |
| `docs/testing/` | 32 个一次性运行记录（`campeche-*` 等），部分引用**别的 checkout 的绝对路径** | 归档或移出仓库 |
| 根目录 `next_plan.md`(677)、`plan_frontend.md`(1293) | 与现状矛盾、互相取代；`plan_frontend.md` 仍描述已删除的多智能体面板/TUI | 归档到 `docs/history/` 或删除；只保留 README 引用的 `refine.md` |
| `frontend/ocean-desktop/tests/` | e2e spec 已删（`d496fcb`），只剩 README、fixtures、10 张**过期**快照；package.json 仍有 `e2e*` 脚本；`docs/desktop/workspace-interaction-contract.md:88-89` 还引用两个不存在的 spec | 要么恢复 e2e，要么删脚本/快照并改文档 |
| `frontend/packages/ocean-ui`（palette/notification/focus-manager/resize） | 桌面**未接线**，仅被测试引用 | 要么接进桌面（见 §4），要么删 |
| 本地仅存的 `src/oceanx/runs/`、`evals/` 下的 `__pycache__` | 无 tracked 文件，只有旧模块 `.pyc` | 本地清理即可 |

### 3.6 命名与文档漂移（S3，但影响理解成本）

- 产品名：代码/UI/README 是 **OceanX**，仓库目录是 **OceanMind-v2**，`CHANGELOG.md` 与旧视觉快照是 **OceanMind**，`.oceanmind/` 是旧状态目录。
- 环境变量三套前缀：`OCEAN_`（22）、`OCEANX_`（9）、`OCEANMIND_`（1），27 个名字散在 20 个文件，无集中读取封装。
- localStorage 键两套：`oceanmind.ui-language.v1` / `oceanmind.paper-acquisition.v1` vs `oceanx.project-catalog.native-v1` / `oceanx.workflow-mode.v1` / `oceanx.parallel-experts.v1`。
- README 与实现 3 处明确不一致：`:165` 说 Coordinator 有 `delete`/`execute`（allowlist 实际只有 6 个工具，`graphs.py:163-170`）；`:148,154` 的「60 次有效调用」可被绕过；`:105,122` 的「不镜像生命周期 / checkpoint 是 source of truth」与实际的内存投影不符。
- `CHANGELOG.md` 称「Standardized project state under `.oceanmind`」，README 说新状态在 `.oceanx/`。

### 3.7 明确「不要动」的清单（避免误伤）

| 文件 | 理由 |
|---|---|
| `scientific_view.py`(1540) | 它是**沙箱内公开 SDK**：`expert_execution.py:110-113` 把它复制进沙箱并生成 `from oceanx.scientific_view import ScientificFigure`，模型生成的科研脚本依赖该路径 |
| `protocol/v2/models.py`(1323/135 类) | 单文件 wire 契约是刻意设计，拆文件会影响 Pydantic `$defs`、JSON Schema 与生成的 TS |
| `research/graphs.py`、`research/lessons.py` | 直接装配 agent 行为 / 学习工作流，在禁区；最多纯搬移常量并保留别名 |
| `sandbox/execution.py`、`expert_execution.py`、`artifacts/models.py`、`task_results.py` | 平台抽象/表驱动模型，内聚；拆了收益低 |
| 超长 prompt / 中文注释 / `Any` 406 处 / E501 | 风格偏好，不要当工作量做 |

### 3.8 建议顺序（均不改 agent 行为）

1. **P0（1 天）**：修 `cli.py:279` + CLI 测试；`ruff --fix` 后把 `RUFF_TARGETS` 扩到 `src/oceanx tests scripts`。
2. **P1（1–2 周）**：`store.py` 拆包（mixin 门面）；`router.py` 第一步（抽纯事件构造）+ `_dispatch` 表驱动；`py.typed` + mypy baseline；新增 `ci.yml`（pytest/ruff/tsc/test-contract）。
3. **P2**：补 3 类关键测试（artifact intent→commit 幂等/冲突、dispatch 拒绝路径、store 事务回滚）；`import-linter` 冻结依赖；router handler 拆分（先 characterization test）。
4. **P3（需你拍板）**：仓库卫生（benchmarking / release-metadata / docs/testing / 根文档 / 死 TUI）。

---

## 4. 问题三：前端交互是否足够方便（评分 6/10）

### 4.1 亮点（底子很好）

- 三栏可调工作台（项目/任务栏 272px + 对话 + 结果工作台），`styles.css:28`；欢迎态会收起右栏。
- 对话：流式 delta、停止/取消、Enter 发送/Shift+Enter 换行、`/papers` 斜杠命令、图片粘贴、语音输入（Web Speech + 权限拒绝提示）。
- 长任务可见性：`AgentActivityPanel`、`AgentCollaborationCanvas`（专家协作拓扑）、研究日志、团队快照。
- 结果呈现：地图（MapLibre）+ 图层图例 + 联动图 dock、`ScientificView`（KaTeX/Markdown、多层图）、交互图工作台、报告工作台、补充材料（notebook）。
- 工程化：中英文 i18n（`text(en, zh)` 内联对）、主题/密度设置、`aria-live`/`role`/`aria-modal` 已用不少、主进程安全边界（sandbox/CSP/路径校验/授权 token）做得相当仔细。

### 4.2 三个 S1 硬伤（用户可直接撞上）

**S1-1 结果工作台常驻 42vw，且没有结果也初始化 MapLibre + 远程底图。**
- `App.tsx:1202` 无条件渲染 `<ResultWorkbench>`（`document=null` 时也渲染）；
- `styles.css:28` 中列宽 `272px minmax(500px,1fr) minmax(360px,42vw)` → 1440px 窗口下对话约 560px；
- `SpatialWorkbench.tsx:533-545` 在挂载时立即 `new maplibregl.Map(...)` 并加载远程底图（欢迎态只是 CSS `display:none`，`styles.css:30`，组件仍挂载、effect 仍执行）。
- 影响：对话被压窄；每个新任务无谓消耗 WebGL/网络；离线/弱网首屏变慢；也涉及隐私（未看结果就请求外部瓦片）。

**S1-2 后端崩溃/丢失终态后卡在「运行中/停止」，无法自愈。**
- `App.tsx:377` 收到 `exit` 帧只 `setInlineStatus('Backend exited (…).')` + `context=null`，**不清 `activeRequestId`/`stoppingRequestId`**；
- 重连 path（`App.tsx:506-514`）拿到 `status.running` 后只重建 handshake，**不重新 `task.open`**；
- 仓库里其实已有 `pending-requests.ts`（180s TTL，注释写明「A lost terminal event must not wedge the UI」），但**只有它自己的测试在用**，未接入。
- 影响：用户看到永远转圈的「运行中」，只能重启应用；长任务的价值被这一点显著抵消。

**S1-3 欢迎页三个「研究入口」卡片是静态 `<article>`，点击无反应。**
`OceanXWelcome.tsx:53-60`：三张带图标和文案的卡片（看起来像入口按钮）没有 `onClick`/`role="button"`/`tabIndex`。用户会点，然后认为应用坏了。

### 4.3 S2（影响手感与效率）

1. **无命令面板 / 无全局快捷键**：`docs/desktop/workspace-interaction-contract.md:57` 明确规定 `Cmd+K`/`Ctrl+K` 命令面板、`Tab/Enter` 操作，但渲染进程里**没有任何实现**（全仓无 Cmd+K handler）；`ocean-ui` 里已写好的 `CommandPalette`、`NotificationStack`、焦点管理器**都未接线**。桌面专业工具缺快捷键，效率损失每天可见。
2. **失败后没有「重试 / 继续」按钮，输入不回填**：`request-recovery.ts:3` 的 `restoreSubmittedPrompt` 只有定义、无调用；错误只显示 `inlineStatus` 字符串并可手动关闭；`awaiting_user_retry` 也只转成一行文字。
3. **切换项目/任务时直接 SIGTERM 后端，无确认**：`App.tsx:546-561` 的 `activateProject` 直接 `startBackend({workspacePath})`；契约要求的「Keep Current / Cancel and Switch」未实现，活动请求会被无提示丢弃。
4. **中文模式覆盖不全**：右栏 `SpatialWorkbench`（"Objects"、"Focus object"、"All objects"、"Result objects"、图例）、`ScientificView`、报告工作台、`AgentCollaborationCanvas`、部分 aria-label 仍是硬编码英文。
5. **流式答案的位置不理想**：正文流式与「研究日志」分置；日志区有空闲高度限制，长输出需要手动跟随；没有「后台完成」通知（切走任务后不知道何时完成）。
6. **结构化图表没有导出入口**：`SpatialWorkbench.tsx:817` 只对「文件类」结果给 Download；`ScientificView` 渲染的图表无导出按钮（对科研工作流是明显缺口）。
7. **对话框焦点**：`ModalDialog` 只处理 `Escape` 与恢复焦点，**没有 Tab 焦点陷阱**（`ocean-ui/src/modal-focus.ts` 已实现但未接线），键盘用户 Tab 会跑出对话框。

### 4.4 前端代码质量

- `App.tsx` 1208 行：**50 处 `useState` + 21 个 `useRef` + 18 个 `useEffect` + 129 行的 `handleFrame`**，一个组件承担「生命周期、协议、任务、结果、设置、语音、更新」七件事；`tasks` state 只写不读；项目目录双持久化；乐观 transcript 有两套实现（`optimisticUser` 与 `optimisticUserTranscriptItem`）。
- 渲染进程几乎不消费 `generated/protocol-v2.ts`（唯一 `import type` 是 `types.ts:1` 的 `RequestContext`），大量 `as unknown as` 手写断言——协议契约在前端基本靠自觉。
- `frontend/ocean_terminal`（1450 行的 hook + 708 行 App）确认孤儿；`frontend/packages` 大部分只被测试引用（见 §3.5）。
- e2e 回归网缺失：spec 在 `d496fcb` 删除后未恢复，`docs/desktop/workspace-interaction-contract.md:88-89` 引用的 `accessibility-contract.spec.ts`、`security-boundary.spec.ts` 都不存在；本机 vitest 又因 Node 版本跑不起来 → **交互体验目前没有任何自动化防护**。

### 4.5 便利度分维度评分

| 维度 | 评分 | 说明 |
|---|---:|---|
| 首次使用 / 空状态 | 5 | 欢迎页讲清了「做什么」，但入口卡片不可点 |
| 对话与流式 | 8 | 流式、停止、Markdown/KaTeX、斜杠命令都在；位置与跟随略糙 |
| 长任务可见性 | 7 | 专家拓扑/活动面板是亮点；但崩溃后卡住、无完成通知 |
| 失败恢复 | 4 | 无重试按钮、输入不回填、终端事件丢失不自愈 |
| 结果与图表 | 7 | 地图/联动图/交互图专业；缺导出、右栏常驻挤压对话 |
| 键盘与可达性 | 5 | 基础 aria 不错；无快捷键/命令面板、无 Tab 陷阱 |
| 中英文一致性 | 5 | 左栏/对话/设置双语，右栏/图表/报告英文 |
| 代码可维护性 | 5 | App.tsx 状态过载、协议类型未用、共享包死代码 |

### 4.6 建议（不触碰 agent 交互与学习逻辑）

1. **P0**：欢迎页卡片改成真按钮（或删掉入口暗示）；`exit`/超时清 `activeRequestId` 并接 `pending-requests`；重连后自动 `task.open`；未打开结果时不挂载 `SpatialWorkbench`（或懒挂载 MapLibre）。
2. **P1**：结果栏默认收起/可停靠，把 42vw 留给「打开结果后」；失败气泡加 Retry/Continue 并回填输入；把 `ocean-ui` 的 CommandPalette + 焦点管理器接进来，补 Cmd/Ctrl+K；右栏/图表/报告的中文补齐。
3. **P1**：恢复或正式删除 e2e（删就同步删脚本/快照/文档引用），CI 跑 `tsc + vitest`；把 `App.tsx` 的协议/任务/结果拆成 hooks，`tasks` 只写不读的 state 删掉。
4. **P2**：图表导出（SVG/PNG）；后台完成通知；切任务加「Keep Current / Cancel and Switch」确认；用 `generated/protocol-v2.ts` 收敛 `as unknown as`。

---

## 5. 共性根因（比单点问题更重要）

1. **文档/契约先行、落地滞后**：README、`docs/desktop/workspace-interaction-contract.md`、CHANGELOG 写得比代码超前（命令面板、e2e 文件、Coordinator 工具集、`.oceanmind`/`.oceanx`、60 次调用上限）。对内部是「设计意图」，对外部读者会变成错误信息。
2. **没有 CI 门禁**：仓库只有一个「签名发布」workflow。lint/type/测试/契约/e2e 都没有守门人，导致「配置了 strict」= 「事实没人跑」。
3. **大重构后的清理没做完**：TUI、`packages/ocean-ui`、e2e spec、旧视觉快照、release-metadata、根目录计划文档都停在「已废弃但还在」的状态。
4. **命名与边界漂移**：OceanX / OceanMind、`OCEAN_` / `OCEANX_` / `OCEANMIND_`、`oceanx.*` / `oceanmind.*`；`backend` 既当数据层又当传输层。这些不致命，但持续抬高每个新人的理解成本。

---

## 6. 建议路线图（按「不改 agent 交互、不改 skill/tool 学习」约束裁剪）

| 优先级 | 事项 | 是否触碰禁区 | 预估 |
|---|---|---|---|
| **P0** | `cli.py:279` NameError + CLI 测试 | 否 | 0.5 天 |
| **P0** | 欢迎页真按钮；崩溃/超时自愈（接 `pending-requests` + 重连 `task.open`） | 否 | 1–2 天 |
| **P0** | 未打开结果不挂载 MapLibre；结果栏默认收起 | 否 | 1 天 |
| **P0** | 删除死 TUI + 1.5MB 产物；修 README 3 处漂移；恢复或删除 e2e 残留 | 否 | 1 天 |
| **P1** | `store.py` 拆包（mixin 门面）；`router.py` 抽纯事件构造 + dispatch 表 | 否（纯搬移/等价改写） | 1–2 周 |
| **P1** | `py.typed` + mypy baseline + ruff 全量 + 新增 `ci.yml`（pytest/ruff/tsc/test-contract） | 否 | 2–3 天 |
| **P1** | 命令面板/焦点陷阱接线、Cmd+K、失败重试、中文补齐 | 否 | 3–5 天 |
| **P1** | 私有 deepagents API 的 import smoke + 逐个替换（P1→P4） | 否 | 1 周 |
| **P2** | import-linter 冻结依赖；补 3 类后端关键测试；图表导出；后台完成通知 | 否 | 2–3 周 |
| **P2（需你拍板）** | 仓库卫生（benchmarking LFS / release-metadata / docs/testing / 根文档） | 否 | 1–2 天 |
| **暂缓（禁区）** | 后台 Expert 时序重构、60 次预算计数修正、取消语义调整、interrupt/Command(resume) 替换 interaction | **是** | 只补测试/文档 |

---

## 7. 明细报告与复现

本报告的完整证据在以下三份报告中（均在 `.agent-review/`，未跟踪，可随时删）：

- `native-usage.md`（214 行）：原生 vs 自研总表、私有 API 全清单与碎裂风险、后台 Expert/checkpoint/预算/取消的机制分析、README 漂移。
- `hygiene.md`（334 行）：19 条按 S1/S2/S3 排序的问题表、`store.py`/`router.py` 逐文件拆分边界、import 图与静态环、测试缺口、仓库卫生。
- `frontend-ux.md`（211 行）：交互问题 → 用户影响 → 改法 → 成本表、App.tsx/main.ts 代码质量、前端遗留与 e2e 现状。

复现命令（本机 `oceanx` conda 环境）：

```bash
conda run -n oceanx python -m pytest -q --collect-only          # 840 tests
conda run -n oceanx python -m ruff check src/oceanx             # 112 findings
cd src && conda run -n oceanx python -m mypy --explicit-package-bases oceanx   # 893 errors
conda run -n oceanx python -m ruff check --select F821 src/oceanx  # cli.py:279 未定义名
cd frontend/ocean-desktop && node node_modules/typescript/bin/tsc -p tsconfig.json --noEmit  # 0 errors
git ls-files benchmarking | xargs du -ch | tail -1              # ~177M tracked
```

> 说明：`.agent-review/` 是本次评审新增的唯一内容，`git status` 其余部分干净；未修改任何产品代码、测试或配置。
