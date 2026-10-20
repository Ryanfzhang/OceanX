# 后端代码整洁度与可维护性审计（只读）

- 审计对象：`/Users/ryanzhang/Code/OceanMind-v2` @ `89a456a`（工作区干净）
- 范围：`src/oceanx`（105 个 Python 文件、34,615 行）、`tests/`、构建/仓库卫生
- 约束：**未修改任何产品代码/测试/配置**；本文件是唯一写入。所有建议均不改变智能体交互逻辑与 skill/tool 学习逻辑。
- 方法：`ast` 脚本统计规模/函数长度/import 图/环；`ruff`、`mypy strict`、`pytest --collect-only`；定向 grep 与抽样阅读。复现命令见文末。

---

## 一、结论先行（≤10 行）

1. 代码质量整体高于体积给人的印象：**router 不写 SQL、store 不拼 HTTP**，无裸 `except:`，**运行时 import 环为 0**（6 个静态环全部靠 `TYPE_CHECKING`/函数内延迟 import 打破）。
2. 但**分层是名义上的**：`backend` 不是底层——10 个 core 模块反向 import `backend.store`，`backend.router` 顶层 import 了 26 个 `oceanx.*` 模块，`artifacts/service.py` 反向依赖 `backend.store`，包间没有可执行的依赖规则。
3. 两个**真正的上帝类**必须拆：`store.py`（4165 行 / 87 个公共方法 + 53 个私有方法 / 26 张表 / 168 条 SQL）、`router.py`（3890 行 / 86 个方法 / 35 分支 `isinstance` 分派 / 270 行单方法）。
4. **类型门禁是假的**：`pyproject.toml` 写了 `strict = true`，但没有 `make typecheck`、没有 CI mypy；实测 976 errors / 89 files（修正包解析后 893 / 65）。`make lint` 只覆盖 10 个目标，全量 ruff 112 处。
5. 有 1 个确定的运行时 bug：`ocean export` 命令引用未定义名字 `RequestStore`（`src/oceanx/cli.py:279`），且无测试覆盖。
6. 仓库卫生是当前最“贵”的非代码问题：`benchmarking` 737 个文件 177MB 入库（git pack 168MB），`release-metadata` 10 份 0.1.0 快照入库而包版本已是 0.1.5。
7. 遗留 TUI：`frontend/ocean_terminal`（13 文件）+ 1.4MB 已构建产物 `_ocean_terminal/dist/ocean-terminal.mjs` 仍在库中，但**无任何构建/运行引用**，CHANGELOG 自己写着“Removed … its terminal frontend”。
8. 用户点名怀疑的重复实现**经核对都不是重复**（protocol models/desktop_contract、task_results/artifacts、native_skills/skills、lessons/policy、agent/gateway），**不建议合并**，理由见 §4。
9. 环境变量、全局状态、错误处理比预期干净：27 个 env 名但仅 20 个文件读取、无 mutable default、无类级可变默认值；`Any` 与长行属风格偏好，不建议当任务做。
10. 建议顺序：**P0 修 cli bug + 拆 store/router（纯机械，保门面）→ P1 立 lint/type/契约门禁 → P2 收仓库卫生**；每步都不触碰 agent 行为。

## 二、问题表（按严重度排序）

> S1=确定的功能/正确性问题；S2=显著可维护性债务，应尽快处理；S3=清理项，可排队做。

| 级别 | # | 问题 | 证据 | 低风险改法 |
|---|---|---|---|---|
| S1 | 1 | `ocean export` 命令运行时 `NameError` | `src/oceanx/cli.py:279` 使用 `RequestStore`，但文件顶部无导入；`ruff --select F821` 唯一命中；`tests/test_oceanx/test_cli.py` 无 export 用例 | 加一行 `from oceanx.backend.store import RequestStore`；补一个 `CliRunner` 冒烟测试（`--artifact` 解析 + export 成功/非法 ref）。不动任何其他逻辑 |
| S2 | 2 | `store.py` 上帝仓储：4165 行、87 公共方法、53 私有方法、26 张表、168 条 SQL | `src/oceanx/backend/store.py:412`（`RequestStore` 起）；表引用统计见 §3.1 | 按聚合拆成 `backend/store/` 包：错误/记录/连接、requests、tasks、interactions、artifacts、disclosure、usage、code_executions、tool_calls、rows；`RequestStore` 用 mixin 组合保持**公共导入路径与调用点不变**（13 个模块 import 它）。纯搬移+门面，行为零变化 |
| S2 | 3 | `router.py` 上帝路由：3890 行 / 86 方法；`_dispatch` 是 35 段 `isinstance` 链；`_execute_agent_request` 270 行 | `src/oceanx/backend/router.py:617`（`_dispatch`，723 行末抛 fallback）、`:2329`（270 行）、`:352`（`handle` 185 行） | 三步走：①先抽**纯事件构造**（`:3644-3890`，10 方法/182 行）到 `router/projection.py`；②`_dispatch` 改 `dict[type, handler]` 表驱动（行为等价）；③按域拆 handler 模块（artifacts/datasets/tasks/session/lifecycle），router 只留状态与 `handle()`。`_execute_agent_request` 最后动，动前先补 characterization test |
| S2 | 4 | 分层方向不成立 + 包内双向依赖 | 10 个 core 文件 import `backend.store`（`context.py`、`tools.py`、`datasets.py`、`exports.py`、`expert_execution.py`、`task_workspace.py`、`workspace.py`、`local_sources.py`、`cache_cleanup.py`、`cli.py`）；`src/oceanx/artifacts/service.py:12` 反向依赖 `backend.store`；`src/oceanx/backend/router.py` 顶层 import 26 个 `oceanx.*`；6 个静态环（§2.2） | 先加 `import-linter` 的**现状快照契约**（只禁止新增反向边），再把 `store` 里非请求域的数据访问提成 `oceanx/storage/`? 更稳妥：把 `store/` 拆分（#2）后，规定“`backend` 只依赖 `storage` + `protocol`，core 只依赖 `storage`”，用 CI 阻止回退。不要一次性大搬迁 |
| S2 | 5 | `mypy strict` 名义开启、实际不可用 | `pyproject.toml:105-107`（`strict = true`）；`Makefile:20` 的 `typecheck` 是前端 `npm run check`，全仓无 mypy 目标、无 CI（`.github/workflows/` 仅 `desktop-signed-release.yml`）；缺 `src/oceanx/py.typed`，导致 293 条 `import-untyped` | ①加 `src/oceanx/py.typed`；②Makefile 增加 `mypy: MYPYPATH=src $(PYTHON) -m mypy -p oceanx`；③用 `--generate-baseline`/`[[tool.mypy.overrides]]` 先冻结现有错误数（893），只要求“不新增”；④不要在 PR 里宣布 strict 通过。注：修正解析后仍有 893 errors / 65 files，逐步收紧是月级工作 |
| S2 | 6 | 后端关键路径缺直接测试，且无覆盖率门禁 | 87 个 store 公共方法中，`commit_artifact_intent`（`:1651`，167 行事务）、`prepare_artifact_intent`（`:1537`）、`commit_active_ref`（`:2630`）、`rebuild_impact_projections`（`:2881`）、`set_artifact_lifecycle`（`:2889`）、`record_resource_usage`（`:2502`）、`start_code_execution`（`:2696`）、`commit_disclosure_policy`（`:1433`）在 `tests/` 中**零字符串引用**；`_dispatch` 的 unknown-type/未握手/能力拒绝分支无直接用例 | 优先补 3 类测试：①artifact intent→commit 幂等/冲突；②dispatch 的拒绝路径（未认证、capability、未知类型）；③store 事务回滚。只加测试，不改实现 |
| S2 | 7 | 仓库被实验证据撑大：`benchmarking` 177MB / 737 文件入库 | `git ls-files benchmarking` 177MB，其中 `benchmarking/reviews` 176MB（含单文件 2.4MB `run-measures.json`、1.5MB review HTML）；`git count-objects -vH` pack 168.54MB | 把 `benchmarking/reviews/**` 的产物（HTML/PNG/大 JSON）迁到 Git LFS 或发布附件；代码与 fixtures 保留。需要产品决策，但**只影响仓库，不影响运行** |
| S2 | 8 | 发布证据以快照形式入库且已过期 | `release-metadata/` 10 个目录（`macos-x64-0.1.0*`）、30 文件 / 4.6MB；而 `pyproject.toml:7` 版本是 `0.1.5`；仅 `.github/workflows/desktop-signed-release.yml:83` 与 `docs/release/desktop-release-manifest.md:64` 引用输出目录 | 保留最近一份作样例即可；其余作为 CI artifact。低风险：`git rm -r` 旧目录 + 在 `release-metadata/README.md` 说明生成方式 |
| S2 | 9 | 已声明删除的 TUI 仍在库中并被构建产物带进 sidecar | `frontend/ocean_terminal/` 13 个 tracked 文件（仅 `plan_frontend.md:655` 提到“retained TUI”）；`src/oceanx/_ocean_terminal/dist/ocean-terminal.mjs` 1.4MB，`src/` 内 0 引用（`grep -rn _ocean_terminal src scripts` 无命中）；`CHANGELOG.md:14-18` 写 “Removed … its terminal frontend”；`.gitignore:5-8` 专门为它开例外；`release-metadata/macos-x64-0.1.0/checksums.json:3219` 证明它被打进 sidecar | 二选一：①删除 `frontend/ocean_terminal` + `src/oceanx/_ocean_terminal` 并去掉 `.gitignore` 例外；②若要保留，补 CI 构建校验并说明用途。删除不触碰运行时（无 import） |
| S3 | 10 | Lint 门禁只覆盖 8.5% 的文件 | `Makefile:3-15` `RUFF_TARGETS` 仅 8 个文件 + `src/oceanx/sandbox` + 1 个测试；该范围实测 `All checks passed!`；全量 `ruff check src/oceanx` 112 处（6 个未使用 import、1 个 F821、69 ANN401 等） | 把 `RUFF_TARGETS` 换成 `src/oceanx tests scripts`，先 `ruff check --fix`（66 处可自动修）再加 CI。未使用 import 具体：`backend/store.py:7`(`re`)、`:48`(`TaskResultRef`)、`expert_execution.py:9`(`re`)、`:11`(`zipfile`)、`research/graphs.py:29`(`ToolRegistry`)、`expert_deliverables.py:12`(`TaskResultError`) |
| S3 | 11 | 环境变量无集中定义，两套前缀并存 | 27 个名字分散在 20 个文件；`OCEAN_` 22 个、`OCEANX_` 9 个（如 `OCEANX_EXPERT_CALL_LIMIT` vs `OCEAN_SANDBOX_PYTHON`）；仅 7 个模块把 env 名做成常量（`research/toolbook.py:50,62`、`acceptance.py:18`、`policy.py:24`、`review.py:28`、`graphs.py:357`、`figure_delivery.py:14`） | 新增 `src/oceanx/config.py` 只做**读取封装 + 默认值 + 类型转换**，现有调用点逐文件迁移；不要一次改名（会破坏桌面 sidecar 环境注入） |
| S3 | 12 | 导入期读 env，导致测试只能 monkeypatch 模块常量 | `research/graphs.py:71,92-93` 在 import 时求值 `EXPERT_MODEL_CALL_LIMIT`/`MAX_PARALLEL_*`；`tests/test_oceanx/test_expert_call_budget_notice.py:90-92` 只能 `monkeypatch.setattr(graphs, name, value)`；`test_saved_data_index.py:437` 同样 | 改为函数内读取（`_expert_call_limit()` 只在建 graph 时调用），保留同名模块常量别名以兼容测试；纯读取时机变化，不改策略 |
| S3 | 13 | 进程级可变全局状态 | `research/graphs.py:126-127` `_EXPERT_SLOTS`/`_SEARCH_EXPERT_SLOTS`（`:136,:147` 用 `global` 写，按 event loop 重建）；`research/services.py:17` `_active_host` 单例（`research/app.py:21,29` 生命周期内赋值/清空）；`router.py:281-299` 实例级 14 个 dict/set 状态 | 现状有 loop 校验，风险可控。若整理：把两个 slot 池收进 `research/budgets.py` 的 `Slots` 类（纯搬移），`_active_host` 保留；不要引入 DI 框架 |
| S3 | 14 | `assert` 用于运行时不变式，`-O` 下会消失 | `backend/store.py:990,1040,2737,2781`；`backend/router.py:1176`；`batch.py:167,176,189`；`sandbox/execution.py:719-720`；`toolbook.py:160` | 把“数据一致性断言”改为显式 `raise RequestStoreError(...)`；把“子进程管道非空”这类改 `if ... is None: raise`。数量少，逐个改即可 |
| S3 | 15 | 一处 fire-and-forget task 未保留引用 | `backend/router.py:1517-1521`（`_schedule_research_consolidation` 里 `create_task(run())` 结果丢弃；同文件 `:1541` 和 `:2054` 都有 `_library_updates`/`_agent_tasks` 跟踪） | 加 `self._background_maintenance: set[asyncio.Task]` + done_callback discard（复制 `:1541-1543` 现有写法） |
| S3 | 16 | 根目录规划文档与现状矛盾且互相取代 | `next_plan.md` 677 行，`next_plan.md:3` 自称“本文档取代此前 `next_plan.md` 的 Adaptive Team Runtime 方案”；`plan_frontend.md` 1293 行仍描述已删除的多智能体面板/TUI（`:655`）；仅 `refine.md` 被 `README.md:139` 引用 | 把工程规范迁到 `docs/adr/`，历史计划移 `docs/history/` 或删除；保留并被 README 引用的 `refine.md` |
| S3 | 17 | `docs/testing/` 32 个一次性运行记录 | 目录 304K，例：`campeche-round60-20260913-1425-check.md`、`coordinator-clean-handoff-20260914.md`；部分文件引用**别的 checkout 的绝对路径**（`coordinator-dependency-evaluation-20260914.md:92` 指向 `/Users/ryanzhang/Code/OceanX-v2/...`）；仓库内无代码引用它们 | 移出仓库或归档到 `docs/history/runs/`；一次性记录不应进 PR |
| S3 | 18 | 开发者环境有三套互不一致的说法 | `INSTALL.md:8-9`（conda `oceanx`）、`Makefile:1`（`PYTHON ?= .venv/bin/python`）、`.github/PULL_REQUEST_TEMPLATE.md:8-9`（`uv run`）；`uv.lock` 被 `.gitignore` 忽略 | 统一到 conda `oceanx`：`Makefile` 改 `PYTHON ?= conda run -n oceanx python` 或文档化 `make PYTHON=...`；PR 模板改 `make test`/`make lint` |
| S3 | 19 | 生成物与代码无 CI 新鲜度校验 | 生成器 `src/oceanx/protocol/v2/schema.py:150-159` 写 `protocol/v2/schema/*.json` 与 `frontend/packages/ocean-client/src/generated/protocol-v2.ts`；`Makefile:26-28` 的 `test-contract` 不在任何 CI。当前实测三份产物与代码**完全一致**（无 drift） | 在 CI 加 `make test-contract && git diff --exit-code`；放在现有 release workflow 之外的新 `ci.yml` |

---

## 三、量化

### 3.1 文件规模（backend/research/sandbox + 全仓 Top）

`src` 共 **105 个 `.py` / 34,615 行**；`tests` 74 个测试文件 / 16,633 行（测试/源码行比 0.48）。

| 行数 | 文件 | 备注 |
|---:|---|---|
| 4165 | `src/oceanx/backend/store.py` | 1 类，140 方法，26 表 |
| 3890 | `src/oceanx/backend/router.py` | 1 类，86 方法 |
| 1540 | `src/oceanx/scientific_view.py` | 沙箱内公开 SDK（见 §3.3） |
| 1363 | `src/oceanx/sandbox/execution.py` | 平台沙箱，内聚 |
| 1350 | `src/oceanx/expert_execution.py` | 沙箱引导+数据上下文 |
| 1337 | `src/oceanx/research/graphs.py` | LangGraph 装配（行为敏感） |
| 1323 | `src/oceanx/protocol/v2/models.py` | 135 个 wire 类型，单文件契约 |
| 966 | `src/oceanx/research/lessons.py` | 学习工作流（行为敏感） |
| 708 / 700 / 542 | `research/tree.py` / `toolbook.py` / `referee.py` | |
| 655 / 617 / 598 | `task_results.py` / `figure_reproduction.py` / `tools.py` | |
| 225 / 171 / 107 | `backend/host.py` / `backend/events.py` / `backend/auth.py` | backend 其他文件均 <230 行 |

`backend + research + sandbox` 合计 18,279 行，占 `src` 的 52.8%。

### 3.2 函数长度 Top 20（AST 统计，共 1273 个函数；≥100 行者 35 个）

| 行数 | 位置 | 名字 |
|---:|---|---|
| 270 | `backend/router.py:2329` | `_execute_agent_request` |
| 247 | `context.py:114` | `build` |
| 215 | `expert_execution.py:964` | `_run_started_python` |
| 208 | `expert_execution.py:744` | `run_python` |
| 185 | `backend/router.py:352` | `handle` |
| 181 | `deep_runtime.py:166` | `submit_message` |
| 178 | `research/tree.py:261` | `apply_changes` |
| 176 | `backend/router.py:1889` | `_session_submit` |
| 171 | `expert_execution.py:409` | `get_task_dataset_context` |
| 167 | `backend/store.py:1651` | `commit_artifact_intent` |
| 156 | `task_results.py:91` | `put` |
| 149 | `scientific_view.py:1339` | `_save_spatial_map` |
| 148 | `backend/router.py:1033` | `_dataset_import` |
| 145 | `backend/router.py:2646` | `_emit_agent_stream_event` |
| 143 | `research/graphs.py:845` | `build` |
| 142 | `expert_deliverables.py:115` | `hydrate_scientific_manifest` |
| 137 | `tools.py:202` | `execute` |
| 137 | `backend/router.py:2938` | `_native_team_snapshot_payload` |
| 135 | `scientific_view.py:1012` | `add_feature` |
| 128 | `scientific_view.py:566` | `field2d` |

“每文件 ≥2 个 ≥100 行函数”的文件：`router.py`(7)、`expert_execution.py`(3)、`store.py`(3)、`task_results.py`(3)、`scientific_view.py`(3)、`graphs.py`(2)、`sandbox/execution.py`(2)。

### 3.3 Import 方向（224 条包内 import 边 / 105 模块，均值 2.13 条/模块）

被依赖最多（in-degree）：`artifacts.models` 18、**`backend.store` 13**、`storage` 11、`protocol.v2.models` 10、`figure_delivery` 7、`sandbox.execution` 7、`task_results` 7、`research.tree_store` 7、`research.tree` 7。

分层矩阵（importer → imported，非自环）：

```
artifacts -> backend 1      backend -> artifacts 7
artifacts -> protocol 1     backend -> protocol 5
core      -> backend 10     backend -> research 8
core      -> artifacts 14   backend -> team 3
core      -> sandbox 12     research -> backend 2
core      -> research 5     research -> sandbox 2
core      -> protocol 3     research -> team 1
protocol  -> artifacts 1
```

结论：`backend` 既被 core 依赖、又依赖 core，是“数据层 + 传输层”混在一起的**隐式共享内核**，不是分层边界。

### 3.2' 静态环（脚本排除 `TYPE_CHECKING` 与函数内 import 后，**运行时环 = 0**）

1. `backend.store → protocol.v2.models → task_results → task_workspace → backend.store`（`task_results.py:30` 的 TYPE_CHECKING 打断）
2. `sandbox.execution ↔ sandbox.windows_broker`（`windows_broker.py:23` TYPE_CHECKING 打断）
3. `sandbox.execution ↔ sandbox.linux`（`execution.py:508` 函数内 import）
4. `research.tree ↔ research.tree_view`（`tree.py:654` 函数内 import）
5. `expert_execution → research.review → lessons → runtime → tools → expert_execution`（函数内 import）
6. `native_backend ↔ research.graphs`（函数内 import）

即：**没有导入即崩的循环**，但 6 个环说明依赖方向靠“延迟 import 技巧”维持，重构时容易踩坏。

---

## 四、分层检查

| 检查项 | 结论 | 证据 |
|---|---|---|
| router 直接写 SQL？ | **否** | `backend/router.py` 无 `sqlite3` import、无 `.execute(`/SQL 语句；仅 `:1458` 拼了个 `research_tree.sqlite3` 文件名 |
| store 直接拼 HTTP/WS？ | **否** | `backend/store.py` 中 `httpx/websocket/aiohttp/socket` 命中 0；只依赖 `sqlite3` + `schema.sql`（`store.py:447`） |
| 协议层反向依赖业务层？ | **部分** | `protocol/v2/models.py:23-31` 直接 import `artifacts.models` 的 5 个领域模型与 `task_results.TaskResultRef`；`protocol` 不是叶子。可接受（wire 类型就是领域投影），但意味着“改领域模型会改协议” |
| 领域服务依赖 backend？ | **是** | `artifacts/service.py:12` `from oceanx.backend.store import ArtifactCommit, ArtifactCommitIntent, RequestStore` |
| 适配层反向依赖业务？ | **是（合理但需声明）** | `research/app.py:19,31` 在 lifespan/函数内 import `backend.host`/`backend.events`，属 WebSocket 适配，可保留 |
| core 依赖 backend？ | **是** | 见 §2 问题表 #4 的 10 个文件清单；最典型 `context.py`/`tools.py`/`task_workspace.py` 直接拿 `RequestStore` 做持久化 |
| 事务/线程安全 | **正确** | `store.py:420-427` 单连接 + `check_same_thread=False` + `RLock`，`_transaction()`（`:475-485`）用 `BEGIN IMMEDIATE` 串行化；SQL 全参数化（唯一 f-string 是表名白名单 `:914`） |
| 后台任务 | **基本正确** | `router.py:1541`、`:2054` 保留了 task 引用；仅 `:1521` 丢弃引用（S3 #15） |

**判定**：分层问题不是“越权访问”型（router 不碰 SQL、store 不碰网络），而是**包边界没有被定义/执行**。最低成本收益是 `import-linter` 冻结现状 + 把 `store` 拆成真正的数据层（§5）。

---

## 五、超大类拆分判断（具体边界）

### 5.1 `store.py` —— 应该拆，而且可低风险拆

聚类（按现有方法边界统计）：

| 建议模块 | 现有行区间 | 规模 | 内容 |
|---|---|---:|---|
| `store/base.py` | 52–500 | ~450 | 9 个异常/记录 dataclass、`_utc_now/_canonical_json`、`__init__`、`_initialize`、`_transaction`、`canonical_hash` |
| `store/requests.py` | 502–618 | 117 | `reserve/mark_in_progress/get_request/get_event/record_domain_event/commit_terminal` |
| `store/workspaces.py` | 619–738 | 120 | `commit_session_open/commit_workspace_open/workspace_snapshot` |
| `store/tasks.py` | 739–1249 | 510 | 研究任务 CRUD、workflow、transcript、task_snapshot、`begin_task_request` |
| `store/interactions.py` | 1249–1432 | 183 | `create_interaction/commit_interaction_response/commit_task_terminal` |
| `store/disclosure.py` | 1433–1519 + 2283–2502 | ~300 | 披露策略提交/读取/审计 |
| `store/artifacts.py` | 1519–2282 | 764 | 版本号、intent、167 行 commit、summary/link/version/file/ref 查询 |
| `store/artifact_views.py` | 2859–3170 | 311 | get/projection/impact/lifecycle/coordinator result/recover |
| `store/usage.py` | 2502–2583 | 81 | 资源用量 |
| `store/active_refs.py` | 2583–2696 | 113 | 活跃引用 |
| `store/code_executions.py` | 2696–2859 | 163 | 代码执行记录 |
| `store/tool_calls.py` | 3170–3280 | 110 | 工具调用记录 |
| `store/rows.py` | 3280–4165 | 886 | 40 个私有 row-mapper/校验 helper（被多模块共享，先别拆散） |
| `store/__init__.py` | — | — | `class RequestStore(RequestsMixin, TasksMixin, ...)` 门面 + 现有 `__all__`（`store.py:4137-4163`） |

低风险要点：
- 保持 `from oceanx.backend.store import RequestStore, ...` 可用（**13 个模块 + 8 个测试文件**依赖它），mixin 组合即可，无需改任何调用点。
- `schema.sql` 目前靠 `Path(__file__).with_name("schema.sql")`（`store.py:447`），拆包后把它放 `store/schema.sql` 并同步该路径；`scripts/` 与构建脚本均未引用该路径（已 grep 确认）。
- 拆分是纯搬移；现有 `tests/test_oceanx/test_request_store.py`（601 行 / 12 用例）是安全网，但建议先补 #6 的 3 个关键事务测试。

### 5.2 `router.py` —— 应该拆，分三步，不要一次动

| 建议模块 | 现有行区间 | 规模 | 内容 |
|---|---|---:|---|
| `router/core.py` | 238–617 | ~380 | 状态字段（281–299）+ `handle_payload`（302）+ `interrupt/shutdown`（324–351）+ `handle`（352） |
| `router/dispatch.py` | 617–724 | 107 | 35 个 `isinstance` → `{RequestType: handler_name}` 表 |
| `router/artifacts.py` | 725–1032 | 308 | 7 个 artifact handler |
| `router/datasets.py` | 1033–1405 + 1649–1836 | 559 | dataset/paper/local-source/portable-export + 源文件路径校验 |
| `router/library.py` | 1444–1572 | 128 | 研究库维护/更新/标记 |
| `router/session.py` | 1889–2600 + 2832–2903 | ~780 | submit、交互问答、agent session、`_execute_agent_request`、取消 |
| `router/projection.py` | 2600–2903 + 2938–3113 | ~500 | stream 事件、task workflow 更新、team snapshot |
| `router/tasks.py` | 3198–3533 | 335 | 任务创建/列表/改名/归档/删除/快照/transcript/output |
| `router/lifecycle.py` | 3114–3198 + 3533–3708 | ~260 | session/workspace open、request status/cancel/shutdown、失败事件 |
| `router/events.py` | 3708–3890 | 182 | 纯事件构造（accepted/completed/failed/interrupted/recovered/fields） |

判定：
- **最先做**：`router/events.py`（纯函数、零 I/O、10 个方法 182 行）——风险最低。
- **第二步**：`_dispatch` 表驱动。等价改写，`raise RequestStoreError(f"No handler for request type …")`（`:723`）保留为 default。
- **最后**：`_execute_agent_request`（270 行）与 `_session_submit`（176 行）——这两个直接编排 agent 运行，属于用户明令“不改交互逻辑”的区域，只在补完 characterization test 后做**纯搬移**。

### 5.3 不建议拆的超大类（“拆了反而更差”）

| 文件 | 判定 | 理由 |
|---|---|---|
| `scientific_view.py` (1540) | **不动** | 它是沙箱内公开 API：`expert_execution.py:110-113` 把 `scientific_view.py/figure_preview.py/figure_reproduction.py/palettes.py` 原样复制进沙箱 `oceanx/` 包并生成 `from .scientific_view import ScientificFigure, ScientificPanel`；拆分/改名会破坏被模型生成的科研脚本的 `from oceanx.scientific_view import ...`。虽 3 个 ≥100 行函数，但属同一 DSL 的 Panel/Figure 两类，内聚 |
| `protocol/v2/models.py` (1323, 135 类) | **不动** | 单文件 wire 契约是刻意设计（模块 docstring 明说“sole protocol type source”）；拆文件会影响 Pydantic `$defs` 合并、JSON Schema 与生成 TS（`schema.py:120-159`）。表驱动、低耦合，拆开只剩成本 |
| `research/graphs.py` (1337) | **不动** | LangGraph 装配 + 中间件 + 策略 prompt；`tests/` 大量 monkeypatch 其模块符号（`test_saved_data_index.py:138-147`、`test_native_subagents.py:86-87`）。任何结构改动都触及 agent 行为，违背约束。最多把 `:55-94` 的预算常量抽到 `research/budgets.py`（纯搬移，且必须保留 `graphs.X` 别名） |
| `research/lessons.py` (966) | **不动** | 单一确定性工作流 + 很长的“为什么这样做”说明；拆分会让 `skill_regions` 写入逻辑跨文件。价值低、风险中 |
| `sandbox/execution.py` (1363) / `expert_execution.py` (1350) | **暂不动** | 平台抽象（policy/capabilities/limiter）与沙箱引导各自内聚；`_run_started_python`/`run_python` 长但线性。可选的唯一低风险抽出是 `get_task_dataset_context`（171 行），收益不足以现在做 |
| `artifacts/models.py` (558) / `task_results.py` (655) | **不动** | 表驱动 Pydantic 模型 / 结果目录，职责单一 |

---

## 六、重复与死代码（含“经核对不是重复”）

### 6.1 用户点名的相似实现：**均非重复，不要合并**

| 组合 | 判定 | 证据 |
|---|---|---|
| `protocol/v2/models.py` vs `desktop_contract.py` | 不是重复 | `desktop_contract.py` 仅 52 行兼容性身份常量（schema 版本、连接清单），`models.py:23` 主动 import 它；两者是“契约常量 ← 传输模型”关系 |
| `task_results.py` vs `artifacts/` | 不是重复 | `task_results` 是任务级输出文件视图（含 `TaskResultStore`，`backend/host.py:24`、`router.py:169` 使用）；`artifacts` 是工作区 artifact 版本/投影/影响图。只共享 `TaskResultRef` 一个标识类型（`store.py:48` 还把它 import 了但**未使用**，可删） |
| `native_skills.py` vs `skills.py` | 不是重复 | `native_skills.py:1-6` docstring 明确：前者是“content-addressed bundled snapshots，不是第二套注册表”；它 import `skills.py` 做发现/元数据 |
| `research/lessons.py` vs `research/policy.py` | 不是重复 | `policy.py:1-9` 明确“learned Coordinator advice lives in lessons (lessons.py)”；policy 只选 frontier/hypotheses/guidance |
| `agent.py` vs `research/gateway.py` | 不是重复 | `agent.py` 是运行时工厂（`build_default_ocean_agent_runtime`，函数内 import `gateway`）；`gateway.py` 是 Agent Server SSE 投影。二者是“构造 vs 流式订阅” |
| `research/review.py` vs `reviews.py` | 不是重复 | review = 项目学习库门面；reviews = 外部 critic/reviewer 输入。文件名接近但职责不同 |

### 6.2 真死/遗留代码

| 资产 | 证据 | 处置 |
|---|---|---|
| `frontend/ocean_terminal/`（13 文件）+ `src/oceanx/_ocean_terminal/dist/ocean-terminal.mjs`（1.4MB） | 除 `plan_frontend.md:655` 外 0 引用；`grep -rn '_ocean_terminal\|ocean-terminal' src scripts frontend/ocean-desktop/scripts` 无命中；`CHANGELOG.md:14-18` 声明已删除；`.gitignore:5-8` 开了入库例外；`release-metadata/.../checksums.json:3219` 显示它被 sidecar 打包 | 删除（或若需保留 TUI 则补构建/使用文档） |
| 未使用 import（6 处） | `backend/store.py:7,48`；`expert_execution.py:9,11`；`research/graphs.py:29`；`expert_deliverables.py:12` | `ruff --fix` |
| `src/oceanx/runs/`、`src/oceanx/evals/` | 本地只剩 `__pycache__`，无 tracked 文件；`__pycache__` 里还有 `exploration_legacy/multi_agent/reporting/...` 等已删模块的 `.pyc` | 本地删缓存即可；不影响仓库 |
| 一次性文档 | `docs/testing/` 32 项；根目录 3 份计划文档（见 #16/#17） | 移出或归档 |

> 说明：`refcount` 中 0 静态引用的模块（`native_text.py`、`analysis_probe.py`、`outcomes.py`、`execution_manifest.py` 等）**不是死代码**：它们通过 `Path(__file__).with_name(...)` 复制进沙箱（`expert_execution.py:90,476,607`）、`from oceanx import native_text`（`native_backend.py:35`）或函数内 import 使用。只按文件名判断会误删。

---

## 七、配置与全局状态

- 环境变量：**27 个名字，20 个文件读取**，前缀两套（`OCEAN_` 22 / `OCEANX_` 9），无集中配置模块。7 个把名字做成常量（见 #11），其余内联（如 `research/app.py:21,36,43,49`、`sandbox/execution.py:410-470`、`scientific_view.py:103-152`）。
- 导入即副作用：**没有**建目录/起线程/连库这类副作用（脚本核查 module-level 调用后确认）。唯一“导入即读 env”是 `research/graphs.py:71,92-93`（S3 #12）。
- 运行期会改环境变量：`research/server.py:20-23` 启动时写 `OCEAN_STATE_DIRECTORY`、`BG_JOB_TIMEOUT_SECS`；`research/paired_runs.py:43,54` 临时改 `OCEANX_RESEARCH_POLICY` 供子进程继承（有 finally 还原）。这两处是启动器协议，建议保留但加注释/集中在 `research/cli.py`。
- 全局可变状态：`_EXPERT_SLOTS`/`_SEARCH_EXPERT_SLOTS`（`graphs.py:126-127`）、`_active_host`（`services.py:17`）、`router` 实例的 14 个 dict/set（`router.py:281-299`）。ContextVar 使用正确（`delegation.py:87`、`metering.py:11`）。
- 无 mutable 默认参数、无类级可变默认值；`lru_cache` 仅 5 处且都有界。

---

## 八、错误处理与类型

### 8.1 错误处理：基本合格，不建议大改

- 裸 `except:` **0**；宽泛 `except Exception` 49 处，其中 17 处带解释性 `# noqa: BLE001`（如 `router.py:1518,1536,1563`、`referee.py:220`、`deep_runtime.py:344`），且多数 `_LOGGER.exception(...)` 保留堆栈。
- 异常包装有 `from exc`（如 `router.py:897,956,968`）；`_run_terminal_commit_hook`/`_sync_task_workspace`（`router.py:3652-3666`）刻意“不让投影失败反向污染已提交请求”，有注释解释——**这不是吞错**。
- 真问题只有 assert 做运行时校验（S3 #14）与 `# noqa` 腐化（`router.py:1518`、`graphs.py:1308` 的 `BLE001` 已不再触发，`model_config.py:141` 的 `S110`、`cli.py:305` 的 `E402` 同理 → `ruff --fix` 可清）。

### 8.2 类型：配置了 strict，但没有执行

```
$ conda run -n oceanx python -m mypy src/oceanx | tail -1
Found 976 errors in 89 files (checked 105 source files)     # 其中 293 条是 import-untyped
$ MYPYPATH=src conda run -n oceanx python -m mypy -p oceanx | tail -1
Found 893 errors in 65 files (checked 136 source files)     # 正确包解析后的真实基线
```

Top 错误码（修正解析后）：`no-untyped-def` 218、`type-arg` 185、`no-untyped-call` 143、`union-attr` 116、`arg-type` 64、`attr-defined` 39、`assignment` 34、`no-any-return` 29。

- `pyproject.toml:105-107` 的 `strict = true` 目前**没有任何执行入口**：`Makefile:20-21` 的 `typecheck` 是 `cd frontend/ocean-desktop && npm run check`；无 CI。
- 缺 `src/oceanx/py.typed`，导致 mypy 把自家包当“已安装无类型包”，凭空多出 293 条噪声。
- `Optional[...]` **0 处**（已统一 PEP 604，`list[...]` 等内建泛型为主），这点做得好。
- `Any` 406 处 / `ANN401` 69 处，集中在 `scientific_view.py`(76)、`store.py`(56)、`analysis_probe.py`(22)——动态渲染/JSON 边界，**属风格偏好**，不建议为了数量做一次性替换。

---

## 九、测试

- `pytest -q --collect-only`：**840 个用例，74 个测试文件，16,633 行**，3.2s 收集完成，无收集错误。
- 结构对应：`tests/test_sandbox` ↔ `src/oceanx/sandbox`、`tests/test_scripts` ↔ `scripts/` 对应良好；`tests/test_oceanx` 平铺 66 个文件覆盖 backend/research/artifacts 等，可接受但定位 ownership 较慢。
- 脆弱性检查（未跑全量，按静态扫描）：
  - **无真实网络/真实模型调用**：测试里的 `https://` 基本是 `.invalid`/`example`，HTTP 由 `httpx.MockTransport` 等注入（`test_model_recovery.py:69`、`test_jina_reader.py:31`）；
  - `asyncio.sleep(60)` 等长等待都被缩短（`test_saved_data_index.py:433-438` 把超时 patch 成 `0.05`）；
  - 真实子进程/超时参数存在但可控（`test_native_execute_timeout.py:18` 的 `timeout=1800` 只是入参；`test_research_tools.py:149` 用 `timeout=120` 跑本地脚本）。
  - conftest 已设置 `OCEAN_SANDBOX_PYTHON=sys.executable`（`tests/conftest.py:14-19`），隔离性较好。
- 缺口（见 #6）：后端 87+86 个公共方法只有约 40 个后端聚焦用例；`commit_artifact_intent` 等事务路径零直接引用；`_dispatch` 拒绝分支未测；无 `pytest-cov` 门禁（dev extras 里有 `pytest-cov`，但没有配置/命令）。

---

## 十、仓库卫生

| 项 | 现状 | 建议 |
|---|---|---|
| `benchmarking/` | 737 tracked / **177MB**（reviews 176MB），git pack 总量 168.54MB | 大产物走 LFS/附件；`benchmarking/tests`(332K)、`server`(172K)、`tasks`(492K) 保留 |
| `release-metadata/` | 10 个 `macos-x64-0.1.0*` 快照、30 文件 4.6MB；版本已 0.1.5 | 只留最新一份样例，其余 CI artifact |
| `docs/testing/` | 32 个一次性运行记录 304K | 移出仓库 |
| 根文档 | `next_plan.md` 677 行、`plan_frontend.md` 1293 行、`refine.md` 117 行 | 前两者归档/删；`refine.md` 仍被 README 引用，保留 |
| 构建产物忽略 | `dist/`、`output/`、`frontend/ocean-desktop/.sidecar-build/`、`frontend/ocean-desktop/sidecar/`、`native/windows-sandbox-broker/target/`（`.gitignore:5,61-62,66,78-79`）**均已正确忽略**；本地 `output/` 1.1G、`native/.../target` 332M 未入库 | 无需动作 |
| 例外入库的产物 | `src/oceanx/_ocean_terminal/dist/ocean-terminal.mjs`（`.gitignore:5-8` 特批） | 见 #9 |
| 生成契约 | `protocol/v2/schema/*.json`、`frontend/packages/ocean-client/src/generated/protocol-v2.ts` 入库，当前与代码**一致** | 保留入库 + CI `git diff --exit-code` 防漂移（#19） |

---

## 十一、真问题 vs 风格偏好

**不建议花时间（风格偏好，勿计入工作量）**
- `E501` 长行 697 处：项目只配 `line-length=100`，ruff 0.16 默认规则并不启用 E501；现状大量 100+ 行是刻意长的 prompt/说明文本。
- `TRY003`（714，`raise ValueError("...")` 不带异常类）与 `B008`（26，typer `Option(...)` 默认值）是框架用法/风格。
- `Any` 406 处、超长 docstring、中文注释：动态 JSON/agent 边界的合理选择。
- 事件/状态字符串字面量（`"completed"` 等）：协议层已有 `Literal` 与 `TERMINAL_*` frozenset（`store.py:92-94`），再加 Enum 收益低。

**必须修/值得修**：问题表 S1–S3 全部；其中 #1 是唯一“用户会撞到的 bug”。

---

## 十二、建议落地顺序（每步都不改 agent 行为）

1. **P0（1 天）**：#1 修 `cli.py:279` + 补 CLI 测试；#10 `ruff --fix` + 扩 `RUFF_TARGETS`。
2. **P1（1–2 周，可并行）**：#2 `store` 拆包（mixin 门面）；#3 第一步抽 `router/events.py` + `_dispatch` 表驱动；#5 加 `py.typed` + mypy baseline；#19 加契约 CI。
3. **P2（按需）**：#6 补 3 类关键测试；#4 import-linter 冻结依赖；#3 第三步 handler 拆分（先 characterization test）。
4. **P3（仓库决策）**：#7/#8/#9/#16/#17 —— 需要产品/发布负责人拍板，纯仓库影响。

---

## 附录：可复现命令

本次审计用的是两个临时 `ast` 脚本（文件规模/函数长度；import 图与环），核心逻辑为：遍历 `src/oceanx/**/*.py`，解析 `ast.FunctionDef/AsyncFunctionDef` 求 `end_lineno-lineno+1`；解析 `Import/ImportFrom`（含相对 import），按包聚类成边并做 DFS 找环，分别排除/保留 `TYPE_CHECKING` 与函数内 import 以区分运行时环与静态环。其余命令：

```bash
# lint / 类型
conda run -n oceanx python -m ruff check src/oceanx --statistics          # 112 处
conda run -n oceanx python -m mypy src/oceanx | tail -1                   # 976 / 89 files
MYPYPATH=src conda run -n oceanx python -m mypy -p oceanx | tail -1       # 893 / 65 files
# 测试
conda run -n oceanx python -m pytest -q --collect-only | tail -1          # 840 tests
# 契约新鲜度（不写文件即可对比：generate_typescript/request_schema/event_schema 与库内产物逐字符比较）
# 仓库体量
git ls-files benchmarking | xargs du -ch | tail -1 ; git count-objects -vH
```
