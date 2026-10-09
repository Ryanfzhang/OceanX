# 怎么跑：OceanX、Claude Code、Finch

都在 Linux 服务器上、仓库根目录、`oceanx-bench` 环境里执行，不用 Docker。第一次先按
[INSTALL.md](INSTALL.md) 装好环境，Finch 另见 [finch/README.md](finch/README.md)。结果怎么评、各方法的运行
设置和对比时的限制，见 [EVALUATION.md](EVALUATION.md)。

## 0. 配置

```bash
cp -n benchmarking/.env.example benchmarking/.env
chmod 600 benchmarking/.env
```

编辑 `.env`（不要 `source` 它）。模板里有三个 runner 需要的全部设置，常改的是这些：

| 设置 | 含义 |
|---|---|
| `DEEPSEEK_API_KEY`、`BENCH_MODEL` | 三个方法和离线的学习步骤共用一个模型和一个 key；桌面端自己的设置不受影响 |
| `BENCH_DATA_ROOT` | 数据根目录，里面要有下载好的数据和 `_download_all/` |
| `BENCH_OUTPUT_ROOT` | 结果根目录，必须和数据、代码仓库分开 |
| `BENCH_EXPERIMENT` | 结果文件夹的名字。代码、设置、数据变了都可以不换 |
| `BENCH_SUITE`、`BENCH_EVOLUTION_SET` | `test`（Q01–Q30）或 `evolution`（E01–E24）；进化题可选 `A` 或 `B` |
| `BENCH_TASKS` | `available`：每次启动时数据齐全的题，缺数据的题会打印出来并跳过。`all`：全部，缺数据就停。也可以写题号，如 `Q07,Q08` |
| `BENCH_RESUME` | `true`：跳过已完成的题，其余的跑。`false`：选中的题全部重跑 |
| `BENCH_TIMEOUT_SECONDS` | 每题的时限，默认 10800 秒。它也是 OceanX 的研究预算：用掉 75% 后不再派新任务，开始写最终报告 |
| `BENCH_OCEANX_EXPERT_CALL_LIMIT` | 每个 Expert 一次任务可用的模型调用数（10–60）。要比较的几组必须相同 |
| `BENCH_OCEANX_LIBRARY` | 学到的库的路径。留空就是未进化 |

- **每个 runner 可以有自己的设置文件。** 默认都读 `benchmarking/.env`；旁边有 `.env.oceanx`、`.env.claude`、
  `.env.finch` 时各读各的。`--config <文件>` 优先于它们。每个 runner 启动时第一行会打印它读的是哪个文件。
- **运行中不要改正在用的设置文件。** OceanX 的服务进程和 Finch 的 worker 在每道题开始时会再读一次模型设置。
- **命令行能临时改的**只有 `--arm`（方法目录名）、`--library`（库）、`--no-resume` 和 `--config`。题目、
  套件、实验名在设置文件里改。显式给 `--queries` 时必须同时给 `--output`，题目就来自那个文件。
- Finch 的控制进程在 `oceanx-bench` 里启动，`BENCH_FINCH_PYTHON` 指向它自己的 Python 3.12 环境。
  `BENCH_FINCH_EXECUTION_TIMEOUT`（默认 1200 秒）限制的是每次整本 notebook 重跑。
- `run_oceanx.py` 在第一次模型调用之前会先启动一次沙箱内核做自检，失败就不跑。

结果的位置（方法目录名来自 `BENCH_OCEANX_ARM`、`BENCH_CLAUDE_ARM`、`BENCH_FINCH_ARM`）：

```text
BENCH_OUTPUT_ROOT/BENCH_EXPERIMENT/runs/
  OceanX/<题号>/attempt-*/      每次尝试一个文件夹，从不覆盖
  OceanX/results.jsonl          每次尝试结束追加一行
  OceanX/launches.jsonl         每次启动追加一行：时间、commit、设置、题目
  OceanX/arm.json               第一次启动时写入
  Claude/...    Finch/...       同上
```

下面的例子用这两个变量，换成你设置文件里的值：

```bash
ROOT=/import/home3/share/oceanx-bench     # BENCH_OUTPUT_ROOT
EXP=benchmarking_oceanx_test              # .env.oceanx 里的 BENCH_EXPERIMENT
```

## 1. 三个方法跑测试题（未进化）

设置文件里 `BENCH_SUITE=test`，`BENCH_OCEANX_LIBRARY=` 留空。在 `tmux` 里开三个终端，各跑一条：

```bash
python benchmarking/server/run_oceanx.py
python benchmarking/server/run_claude.py
python benchmarking/server/run_finch.py
```

每个方法按顺序一题一题跑。

## 2. 继续、补跑、重跑

同一条命令再跑一次就是继续：已完成的题跳过；失败、超时、没跑过的题新建 attempt；旧的不删。

| 要做的事 | 做法 |
|---|---|
| 中断后继续，重试失败的题 | 再跑同一条命令 |
| 数据补齐后，跑之前跳过的题 | 设置文件里 `BENCH_TASKS=available`，再跑同一条命令 |
| 重跑已经完成的某几题 | 设置文件里 `BENCH_TASKS=Q25,Q27`，命令后加 `--no-resume`；跑完把 `BENCH_TASKS` 改回去 |
| 用现在的代码把未进化的 OceanX 整组重跑 | `python benchmarking/server/run_oceanx.py --arm OceanX-L0`，结果写到新目录 `runs/OceanX-L0/` |
| 更新代码或改了设置之后接着跑 | 实验名不用换，照常跑 |

`--no-resume`（或 `BENCH_RESUME=false`）会把选中的题**全部**重跑，所以先确认 `BENCH_TASKS`。评审取每题
最新的一次 attempt。

## 3. 进化：跑进化题，学习一次，冻结成库

库只能从进化题学，所以进化题用单独的实验名，不和测试题的结果放在一起。

**① 跑进化题（set A，E01 到 E12，不带库）**

```bash
(umask 077; grep -vE '^BENCH_(EXPERIMENT|SUITE|EVOLUTION_SET|TASKS|RESUME|OCEANX_LIBRARY)=' \
  benchmarking/.env.oceanx > benchmarking/.env.evolution)
cat >> benchmarking/.env.evolution <<'EOF'
BENCH_EXPERIMENT=evolution
BENCH_SUITE=evolution
BENCH_EVOLUTION_SET=A
BENCH_TASKS=available
BENCH_RESUME=true
BENCH_OCEANX_LIBRARY=
EOF
python benchmarking/server/run_oceanx.py --config benchmarking/.env.evolution --arm E1
```

- `umask 077` 让新文件只有自己能读：里面有 key。
- 启动时应打印 `Questions (12): E01, E02, ...`。不是这样就先停下，检查 `.env.evolution`。

**② 学习一次，冻结成库 L1**

```bash
EVO=$ROOT/evolution
find "$EVO/runs" -name research_tree.sqlite3 \
  -exec python benchmarking/server/research_cli.py judge-labels --tree {} \;
python benchmarking/server/research_cli.py consolidate --project "$EVO" --review --retention-days 3650 \
  | tee "$EVO/review.json"
python benchmarking/server/research_cli.py library --project "$EVO" > "$EVO/library.json"
python benchmarking/server/research_cli.py snapshot --project "$EVO" --output "$ROOT/library/L1"
```

- 三步依次是：让模型给每棵研究树打标签；读这些记录学习一次（经验和工具）；把学到的冻结成库。
- 学习那一步会先让模型把每道题的最终答案单独读一遍（只给题目和答案），列出题目要的哪些没给、哪些结论
  超出了证据，再和研究树记录一起交给元代理。12 道题大约多花 15 分钟；`review.json` 里的 `referee` 一项
  是读了几道、哪几道没读成。
- 一次学习的提示词装不下所有题目的记录时（12 题里装了 10 题），`review.json` 里 `lessons.tasks_left`
  会大于 0。再执行一遍同样的 `consolidate --review` 命令，它会先读没读过的那几题。
- 工具：这里一道题里反复写的代码就可以提成工具（`research_cli.py` 设了 `OCEANX_TOOL_MIN_SUPPORT=1`）；
  日常使用的 OceanX 要两道题。`review.json` 的 `tools` 一项里，`created` 是装上的工具，`rejected` 是被拒的
  和原因。
- 这几条用 `benchmarking/.env` 里的模型和 key。
- `--retention-days 3650` 不能省。默认是 30 天，更早的研究树记录会被移出 attempt 目录。
- `--project` 只指向进化实验的目录，不要指向放测试题结果的目录。
- `review.json` 是这次改了什么。`library.json` 是库里现在的每条经验和每个工具；冻结之前先看一眼，
  里面没有经验、也没有学到的工具时，后面就没有可比的东西。
- 库是两个文件。`lessons.json` 是经验，运行时写进各个 skill 预留的区域。`tools.json` 是工具：学到的函数和
  每个函数的调用次数，长期没人调用的函数会从列表里拿掉。
- 觉得某条经验或某个工具不对，可以在冻结之前去掉它：
  `python benchmarking/server/research_cli.py mark --project "$EVO" --kind lesson --id L003 --wrong --reviewer owner`。
- 第一次做之前，建议先用 3 道题把 ①② 走一遍，确认能学出东西，再跑 12 题：把 `.env.evolution` 里的两行
  改成 `BENCH_EXPERIMENT=evolution-pilot` 和 `BENCH_TASKS=E01,E05,E08`，`EVO` 也相应换成
  `$ROOT/evolution-pilot`。试跑的库不要用于正式的对比。

**③ 第二轮（可选）：set B 带 L1 跑，学出 L2**

把 `.env.evolution` 里的 `BENCH_EVOLUTION_SET` 改成 `B`，然后：

```bash
python benchmarking/server/run_oceanx.py --config benchmarking/.env.evolution --arm E2 --library "$ROOT/library/L1"
```

再执行一遍 ② 的命令，最后一条的输出改成 `"$ROOT/library/L2"`。

## 4. 进化后的 OceanX 跑测试题

```bash
python benchmarking/server/run_oceanx.py --arm OceanX-L1 --library "$ROOT/library/L1"
```

题目和其余设置来自 `.env.oceanx`，和未进化那组相同。结果写到同一个实验的 `runs/OceanX-L1/`，
`runs/OceanX/` 不动。L2 同理：`--arm OceanX-L2 --library "$ROOT/library/L2"`。

## 5. 跑完检查和对比

```bash
RUNS=$ROOT/$EXP/runs
python benchmarking/evaluation/evaluate.py library-check --runs "$RUNS/OceanX-L1"
python benchmarking/evaluation/evaluate.py process --runs "$RUNS/OceanX" "$RUNS/OceanX-L1" --out "$ROOT/$EXP/process"
python benchmarking/server/read_answers.py --runs "$RUNS/OceanX" "$RUNS/OceanX-L1" --out "$ROOT/$EXP/readings"
```

- `library-check`：带库的 attempt 运行前后库没有变，`changed_or_unfinished` 应该是空的。
- `process`：过程指标，包括调用了多少次辅助函数、引用了几条经验、代码失败的比例。
- `read_answers.py`：让模型只看题目和最终答案，数每份答案里题目要的有几项没给、有几条结论超出了证据。
  各组用同一份清单（存在 `readings/asked/`），以后新跑的组加进 `--runs` 再跑一遍即可，读过的不会重读。
  它有模型调用（每份答案约 2.5 万 token），不是评分；约三分之一的标记是误报，结论要靠人工核对几条。
- 确认一组带没带库：
  - 方法目录的 `arm.json` 里，`library` 是 `null` 还是一个快照；
  - 带库的 attempt 目录里有 `arm_library.json`；
  - `launches.jsonl` 每行记着那次启动的 commit、设置和题目。
- OceanX 每批跑完会自动把结果整理到 `runs/<方法>/collected/collection-*`，从里面的 `index.md` 看起。
- 评分由 Codex 做，流程见 [EVALUATION.md](EVALUATION.md)。

## 6. 容易出错的地方

- **进化不会影响未进化的运行。** 每个 attempt 从空状态开始；只有给了 `--library`（或设置了
  `BENCH_OCEANX_LIBRARY`）才会把库拷进去；benchmark 运行中不学习，也不更新工具。所以未进化的那几条命令
  不带 `--library`，`.env.oceanx` 里 `BENCH_OCEANX_LIBRARY=` 保持为空。
- **要比较的几组用同一版代码和同一套设置。** runner 不拦，只在 `launches.jsonl` 里记。现有的未进化结果如果
  是旧代码跑的，就用第 2 节的 `--arm OceanX-L0` 重跑一组做对照。结果要分开保存时（比如第二次重复），换一个
  `BENCH_EXPERIMENT`。
- **运行中不要更新代码。**
- **一个方法目录同一时间只能有一个 runner。** 第二个会报 `Another runner is writing`。
- **每题只跑一次时，几分的差别分不清是库的作用还是运行波动。**
- CMOMS 数据和由它算出的任何东西都不离开服务器。
