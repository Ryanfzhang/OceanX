# 协同约定清理与验证 — 2026-09-14

## 实施范围

本轮处理此前复核的五组问题，保留 DeepAgents 原生异步调度、LangGraph Server 会话、审核机制、Python 内核、现有配额与错误保护。没有新增模型填写字段、科学内容分类器或“首轮只能一个专家”的限制。

1. **问题与阶段**：替换 Coordinator 依赖段，明确依赖决定先后，不把依赖阶段自动合成一个大任务；下一问题取决于当前答案时，先委派当前问题。Expert 仍可自行完成所需辅助统计、数据检查及图件。
2. **原子问题**：创建执行轮次时绑定实际委派内容。删除每次作者启动都用最后一条 HumanMessage 覆盖 task_goal 的路径及其存储写入方法。审核修正复用原记录；Coordinator 的新 follow-up 创建新轮次并保留同一 Expert 会话/内核。
3. **通信说明**：用同名 middleware 替换原生异步 middleware 实例，仅调整工具描述和现有 description 字段的说明。原生启动、查询、更新、取消、task ID、状态与检查点处理不变；没有修改 site-packages 或全局工具常量。删除“报告任务 ID 后停止、只等用户追问”的研究流程冲突。统一由 ocean_deliver 接收作者正文与产物路径，后台保存规范 report.md 并返回路径。
4. **审核通知**：不再在所有作者保存结果后统一宣布 review pending。只有满足原审核条件、审核 graph 构造成功并即将运行时才通知；直接交付角色只发终态通知。审核构造失败进入原 unresolved 路径，不伪装为已开始或已通过审核。
5. **Skill 来源**：运行图不再读数据库 active 演化版本作为覆盖层。原生 Skill 库仅由当前内置角色文件及其支持资源生成，以内容指纹选择不可变快照。旧未版本化目录不再直接命中；内置删除或修改会得到新的库。旧库和演化记录没有删除。研究方向 Skill 移除逐个候选解释、判别观测、贡献预算的流程性段落，保留证据缺口、科学价值和合理的新颖性边界。

运行约定升为 agent-server-v11，Desktop gateway 的 Coordinator thread 命名空间使用同一版本常量，防止新版继续重放旧约定的检查点。保留历史研究文件；没有自动取消外部既有运行。新版本需重新启动/构建相应服务才能生效，桌面应用未重新打包。

Skill 精简遵循 skill-creator 的原则：保留会改变科学判断的内容，不把某次失败再写成一套通用分析步骤。仍通过 DeepAgents 原生 SkillsMiddleware 按需加载。

## 回归验证

- 汇总 **152 passed**，含原生工具绑定、服务端派发/续跑、取消/失败通知、持久与隔离内核、审核修正和报告交付；一条既有 xarray/NumPy 弃用警告。
- 新增真实绑定工具检查：原生五个异步工具无重复注册；start_async_task 仍只有 description、subagent_type 两个字段；安装包原始默认说明不受本应用覆盖影响。
- 新增问题绑定检查：同一次运行的审核修正不改原子问题；新 run 的 follow-up 绑定新问题、job_key 保持。
- 新增 Agent Server code_repair 场景：每轮第一次审核要求修正、第二次通过；两轮均验证 reviewer 始终拿到真正的原子问题。无审核场景不再发 pending；正常代码审核和修正场景分别产生预期次数的 pending。
- 新增 Skill 更新/删除检查：旧快照保留但不进入新发现目录；当前内容变化后新路径生效；数据库演化记录保留但不进入运行库。
- Skill frontmatter 校验、相关 Python 编译、git diff --check 通过。
- 集成测试使用本机服务和确定性假模型，不消耗真实 API。首次新增 repair 用例的假模型错误地用最后一条修正消息选择回复分支，修正 fixture 后重新汇总测试全部通过。

## 真实 Coordinator 首轮测试

同一 Campeche 原题复测两次，再执行明确独立的“数据季节结构＋已发表文献解释”对照。模型均为 deepseek-v4-pro，数据为已授权的 /Users/ryanzhang/Code/CMEMS_oceanmind。每轮独立任务，首次委派执行前停止；**Expert 启动数全部为 0**。三个测试正常结束。

| 运行 | 首批委派 | 墙钟秒 | 模型调用 | 输入 tokens | 输出 tokens | 输入内 cache_read | 模型调用秒合计 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| original-1 | 物理＋文献 | 96.73 | 12 | 140,292 | 8,075 | 127,232 | 85.67 |
| original-2 | 物理 | 77.00 | 11 | 122,132 | 6,884 | 110,208 | 69.77 |
| independent-control | 物理＋文献 | 49.15 | 7 | 82,913 | 4,818 | 72,832 | 47.06 |

总输入 345,337、输出 19,777，合计 365,114 tokens；cache_read 310,272 包含在输入里，不能重复相加或按未缓存输入等价计费。三轮运行墙钟合计 222.89 秒，不含所有服务间启动/退出开销。模型调用时间包含服务和网络等待，不等于纯生成时间；不是费用账单。

### 实际行为

- **original-1**：物理做异常/暖季现象刻画，文献独立查既有机制。研究树把机制归因置于 B1 之后。本轮物理委派明确使用 ocean_deliver，不再要求手写 report.md 或包装 report_path；未把所有形成/维持归因一起交给物理。
- **original-2**：只派物理先刻画目标现象，树把机制问题留待 B1 回答后决定。没有附加报告文件交接要求。
- **independent-control**：物理与文献正确并行，文献不依赖新的计算结果；保留用户先选文献再读全文的要求。

### 限制，不能包装成“全部行为已解决”

两次原题相较此前五次中常见的整题打包，观察到更明确的阶段分离；但样本小、改动多，不能量化因果或泛化收益。

**分项清单仍存在。** original-1 枚举了刻画维度、掩膜处理及年内基线，original-2 也预先提到后续热收支/输运与残差框架。它们并非纯粹一句子问题；不能声称 Coordinator 已稳定把所有方法选择交给 Expert。文献对照中的候选字段部分来自选文献接口的既有数据需求，不能只按列表数量判定失败。

本测试没有运行 Expert 或获得其科学结果，故不能评价真实研究交付质量、完整耗时，也不能证明树在收到证据后能有效更新。审核和会话连续性由确定性服务集成测试验证，不是上述真实模型首轮测试的结论。

本轮公开输出仍提到默认 shell Python 的库问题和解释器寻找过程。记录这些运行事实但未将它们混入本轮五项修复或宣称环境问题已解决。以下公开原文中的数据摘要、数值和科学归因没有经过审核，不代表本报告认可。

## 公开消息与委派原文

以下仅保存公开 assistant content 与委派工具参数，不含 reasoning_content 等私有推理。

### original-1

#### 公开说明

I now understand the dataset. Let me record my research plan and launch the first round of analysis.

**Dataset summary (my inspection):**
- GLORYS12-derived daily fields, domain **98.5–77°W, 16.5–32°N**, 50 depth levels (0.49–5728 m), covering the full Gulf of Mexico incl. the Bay of Campeche.
- One full year: **2025-04-01 → 2026-03-31** (365 days, split into `*_2025.nc` = Apr–Dec and `*_2026.nc` = Jan–Mar).
- Variables: `temp`, `salt`, `u`, `v` (+ `oxygen`, `chlorophyll`).
- Surface temperature in the Campeche box (18–22°N, 97–90°W) peaks ~30.6°C (Sep) and is coldest ~24.1°C (Feb) — a clear seasonal cycle. ~40–50% of near-coast/shallow grid cells are masked (Campeche Bank), so shelf diagnostics are limited.

**Research tree (ordinary progress note):**

```
ROOT: What mechanisms drive formation & persistence of seasonal warm anomalies
      in the Bay of Campeche (Apr2025–Mar2026 GLORYS12)?

├─ B1 [characterization] Where/when/how deep is the seasonal warm anomaly, and
│    how does it relate to stratification & currents?  → Ocean Process Expert
├─ B2 [mechanism priors] What mechanisms are proposed in literature for
│    Campeche/southern-GoM seasonal warming?          → Literature Expert
└─ B3 [attribution — depends on B1] Which mechanisms are consistent with the
     data (temperature tendency / heat-budget decomposition)?  → follow-up
```

Key caveat I'll carry forward: with only **one year**, "anomaly" must be a *within-year* contrast (warm-season vs cool-season, or deviation from the annual mean), not an interannual anomaly relative to a multi-year climatology — the data cannot separate seasonal cycle from year-to-year anomalies.

Launching B1 and B2 in parallel (they're independent):

#### 委派 1：ocean_process_expert

SUBQUESTION (Branch B1): Characterize the seasonal warm anomaly in the Bay of Campeche during the one-year GLORYS12 record (2025-04-01 to 2026-03-31). Where and when does upper-ocean warming occur, how deep does it extend, what is its magnitude and spatial pattern, and how does it relate to stratification (salinity) and to the horizontal/vertical circulation structure?

WHY IT MATTERS: This defines the target (region, season, depth) that a subsequent mechanism-attribution step must explain, and constrains which mechanisms (surface heat flux vs. advection/eddies vs. stratification/reduced mixing) are plausible.

DATA (read-only): /Users/ryanzhang/Code/CMEMS_oceanmind/
- CMEMS_temp_Zlev_2025.nc (2025-04-01..12-31, 275 daily) + CMEMS_temp_Zlev_2026.nc (2026-01-01..03-31, 90 daily) -> concatenate for the full year.
- Also CMEMS_salt_Zlev_{2025,2026}.nc, CMEMS_u_Zlev_{2025,2026}.nc, CMEMS_v_Zlev_{2025,2026}.nc (same times).
- Domain lon -98.5..-77.0, lat 16.5..32.0, depth 0.49..5728 m (50 z-levels). Variables are potential temperature (thetao), salinity, u, v.
- NOTE: substantial NaN masking near the coast and over the shallow Campeche Bank (~40-50% of surface cells invalid at 16.5-18.5N); handle masks explicitly and do not interpolate over land/shelf where data are absent.

IMPORTANT CONSTRAINTS:
- This is ONE year only (Apr2025-Mar2026). There is no multi-year climatology, so you must define the "seasonal warm anomaly" as a WITHIN-YEAR contrast (e.g., warm season minus cool season, or deviation from the annual mean). State your definition explicitly and its limits (seasonal cycle cannot be separated from interannual anomaly with one year).
- No surface flux/wind/radiation forcing fields are present in this dataset (only T, S, u, v, plus oxygen/chlorophyll). Do not assume surface flux values; treat surface forcing as unobserved here.
- Python environment: use /Users/ryanzhang/miniconda3/envs/oceanx/bin/python3 (has xarray/numpy/scipy/matplotlib); the bare `python3` on PATH lacks xarray.

Please deliver report-ready text and any saved figure/diagnostic artifact paths via ocean_deliver. Report your anomaly definition, the quantitative characterization (timing, depth, magnitude, spatial pattern), the stratification and circulation context, and explicit limitations/uncertainties.

#### 委派 2：literature_reproduction_expert

SUBQUESTION (Branch B2): What mechanisms have been proposed in the published literature to explain seasonal warming / warm anomalies in the Bay of Campeche and the southern Gulf of Mexico? 

Specifically, gather and assess the evidence base for the candidate mechanisms: (1) local surface air-sea heat flux (seasonal net warming), (2) advection by the Loop Current and its shed warm-core eddies / coastal currents (Yucatan Current, Campeche Bank), (3) stratification effects including river runoff/low salinity caps and shallow mixed layers, and (4) wind-driven mixing/upwelling suppression. For each, note the proposed mechanism, the observational/model evidence, and any statements about formation vs. persistence of warm anomalies.

WHY IT MATTERS: This provides the physically-grounded candidate mechanisms and prior expectations that the one-year GLORYS12 dataset analysis (currently being characterized in parallel) will be tested against. It also flags which mechanisms CANNOT be addressed with state-variable-only data (no surface flux forcing).

CONTEXT: The analysis dataset is a one-year GLORYS12-derived reanalysis (Apr2025-Mar2026) over the Gulf of Mexico with T, S, u, v only (no surface fluxes). Bay of Campeche is roughly 18-22N, 97-90W, including the shallow Campeche Bank and deeper western basin.

Please deliver report-ready text with concrete citations (authors, year, venue, DOI/URL where available) and, where you only have abstract/public-excerpt access, be explicit that your assessment is based on that scope, not full text. If a shortlist of candidate full texts would materially strengthen the mechanism attribution, surface it with paper details so the Coordinator can request user selection.



### original-2

#### 公开说明

I've mapped the dataset. Here's what's available and my research plan.

**Dataset inventory (CMEMS_oceanmind / GLORYS12 reanalysis):**
- Daily fields on a 0.25° × 0.25° grid, 50 depth levels (0.49 m → 5727 m)
- Domain: 16.5–32°N, 98.5–77°W (Gulf of Mexico, incl. Bay of Campeche, Loop Current region, Florida/Yucatan channels)
- Variables: **temperature, salinity, u, v, oxygen, chlorophyll**
- Time: **1 Apr 2025 – 31 Mar 2026** (365 days, split across `*_2025.nc` and `*_2026.nc` files) — this is the "one-year" period
- Note: **no atmospheric forcing or surface heat-flux fields** in the files, so air–sea flux can only be inferred as a heat-budget residual.

A key limitation to flag up front: with a single year there is no multi-year climatology, so a "seasonal warm anomaly" must be defined against an in-year reference (e.g., the annual mean or the within-year seasonal cycle), not a true interannual anomaly.

**Research tree:**
- **Root:** What mechanisms drive the formation and persistence of seasonal warm anomalies in the Bay of Campeche (one-year GLORYS12)?
  - **B1 — Characterization (foundational):** What is the observed seasonal warm anomaly — its definition, timing, magnitude, spatial extent, vertical/heat-content structure, and persistence? *(no evidence yet)*
  - **B2 — Mechanism (depends on B1):** Which processes account for formation vs. persistence — horizontal advection (Loop Current/eddies) vs. residual forcing (surface flux + vertical processes)? *(blocked until B1 is answered)*

I'll delegate B1 first, since the mechanism attribution needs a concrete target phenomenon. Dispatching now.

#### 委派 1：ocean_process_expert

SUBQUESTION (Round 1, characterization): Characterize the seasonal warm anomaly in the Bay of Campeche in the provided one-year GLORYS12 reanalysis dataset. What is its sensible definition, and what are its timing (formation vs. peak vs. decay), magnitude, spatial extent, vertical/heat-content structure, and persistence over the period?

WHY IT MATTERS: This establishes the target phenomenon that a follow-up mechanism diagnosis (heat budget: horizontal advection vs. residual surface/vertical forcing; Loop Current and eddy influence) must explain. Without a concrete characterization, mechanism attribution is ambiguous.

DATA (read-only source): directory /Users/ryanzhang/Code/CMEMS_oceanmind contains daily GLORYS12 fields on a 0.25°x0.25° grid, 50 depth levels (0.49 m to 5727 m), domain 16.5-32N, 98.5-77W. Variables: temp, salt, u, v, oxygen, chlorophyll. Time coverage: 1 Apr 2025 - 31 Dec 2025 (CMEMS_*_Zlev_2025.nc) and 1 Jan 2026 - 31 Mar 2026 (CMEMS_*_Zlev_2026.nc), i.e. one full year (365 daily time steps). The Bay of Campeche is the southwestern Gulf of Mexico shelf (roughly 18-21N, 97-90W); define the region box yourself as physically appropriate.

KEY CONSTRAINT / LIMITATION: single year, so there is no multi-year climatology; define "anomaly" against an in-year reference (e.g., annual mean or within-year seasonal cycle) and state that reference explicitly. No atmospheric forcing fields are provided.

A configured scientific Python environment with xarray and netCDF4 is at /Users/ryanzhang/miniconda3/envs/ocean/bin/python (also 'oceanx' env). Please choose your own diagnostics, statistics and figures. Report the characterized anomaly with its evidence and uncertainty, and note what the mechanism diagnosis will need.



### independent-control

#### 公开说明

The dataset is a CMEMS Z-level collection (temperature, salinity, u/v, oxygen, chlorophyll) with files labeled for both 2025 and 2026 — the user described a "one-year" record, so the Expert must pin down actual time coverage. The local shell's Python is broken, which is fine: routine data inspection and analysis belong to the analyzing Expert, who has a working scientific environment.

Two independent questions → two parallel delegations, since the literature survey must stay distinct from (and not depend on) the new analysis.

#### 委派 1：ocean_process_expert

Subquestion: What is the seasonal temperature structure in the Bay of Campeche (southern Gulf of Mexico) in the supplied CMEMS dataset?

Why it matters: This answers the first half of the user's request and must remain strictly distinct from the literature survey, establishing the observed seasonal temperature structure (timing, amplitude, surface vs. vertical structure, horizontal pattern within the Bay of Campeche).

Data (read-only): /Users/ryanzhang/Code/CMEMS_oceanmind — CMEMS netCDF files on Z-levels for temperature, salinity, u/v velocity, oxygen, chlorophyll. The directory contains files labeled for both 2025 and 2026 (e.g. CMEMS_temp_Zlev_2025.nc, CMEMS_temp_Zlev_2026.nc). The user described this as a "one-year dataset", so please establish the actual temporal coverage from the files (start/end times, number of time steps) and state it explicitly. If two years are present, either use the coverage consistent with a one-year description or report the full coverage clearly; do not silently pick a window.

Deliverables: report-ready text describing the seasonal temperature structure in the Bay of Campeche, with any saved figure paths. Clearly separate measured/derived quantities from interpretation, state the product type (e.g. reanalysis/analysis vs. in situ), note spatial/depth/seasonal aggregation and any uncertainty, and flag limitations. Do not prescribe or require the literature; this is data-only.

#### 委派 2：literature_reproduction_expert

Subquestion: What explanations for the seasonal warmth of the Bay of Campeche (southern Gulf of Mexico) have published studies reported?

Why it matters: This is the separate literature survey for the user's request and must stay distinct from the dataset analysis; it concerns published findings only and does not depend on any new analysis.

Constraints:
- Do NOT download additional datasets.
- Return candidate papers BEFORE reading full text. Produce a curated shortlist of candidate papers with substantive details for each: paper_id, title, authors/venue/year (citation when known), URL when known, a one-phrase topic, the deepest evidence scope actually inspected (metadata_only / abstract / public_excerpt), an evidence_summary based only on that scope, and a validation_target tying each paper to the seasonal-warmth question for the Bay of Campeche region.
- Attribute each reported explanation to the paper(s) that reported it, and do not conflate a search snippet with full-text conclusions.

Deliver: (a) a short narrative of the published explanations you found, attributed to papers, and (b) the candidate shortlist in a form I can present to the user for selection before any full-text download. Note explicitly which candidate would best support which aspect of the seasonal-warmth question.


## 原始证据

运行根目录：output/coordinator-clean-handoff-20260914/。每轮 result.json 记录停止边界；state/workspace.sqlite3 的 model_call_observations 提供逐调用用量。原始调试日志未作为公开科学报告附录。
