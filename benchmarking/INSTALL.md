# Server setup (Linux, once)

All commands run from the repository root on the Linux server.

```bash
conda create -n oceanx-bench python=3.11 -y
conda activate oceanx-bench
python -m pip install -r benchmarking/requirements.txt
conda install -c conda-forge bubblewrap libseccomp -y     # OceanX sandbox without sudo
command -v bwrap
```

The host must allow user namespaces (see the OceanX installation guide, "Linux system components").

## Models and run settings: one file

Copy the template and fill its one `DEEPSEEK_API_KEY` on the server. The real `.env` is ignored by git;
keep it out of data and result folders. No local key needs to be uploaded.

```bash
cp -n benchmarking/.env.example benchmarking/.env
chmod 600 benchmarking/.env
```

```dotenv
DEEPSEEK_API_KEY=<your DeepSeek key>
BENCH_MODEL=deepseek-flash
BENCH_MAX_TOKENS=32768
BENCH_OCEANX_API=openai
BENCH_OPENAI_BASE_URL=https://api.deepseek.com
BENCH_ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
```

- **One model/key:** OceanX Coordinator/Experts, the meta-agent/node labels, Claude Code (including
  subagents) and Finch all use `BENCH_MODEL` and the same `DEEPSEEK_API_KEY`. There is no per-role model
  override. Model metadata omits the key. `--config <path>` can select another explicit `.env` for a
  separate experiment; it cannot override one role inside a run.
- **Two wire formats, one service:** OceanX/Finch/meta default to DeepSeek's OpenAI-compatible endpoint;
  Claude Code uses its Anthropic-compatible endpoint. See the
  [official DeepSeek integration](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code/).
- **No inherited credentials:** the loader reads only the selected file and does not source it,
  interpolate shell variables, or inherit other API keys. No real `.env` is created by repository setup.
- **Evaluation:** the independent Codex rubric scoring is a separate manual judging step, not a model
  API invoked by these runners. Changing this `.env` does not reconfigure that judge.
- **Your everyday settings:** OceanX settings in `~/.oceanmind` are neither read nor changed.

The same `.env` also sets the data root, output root, experiment name, task suite/IDs,
timeout/resume, optional OceanX library, Claude executable/tools and Finch environment/limits.
Keep the run settings from `.env.example` when filling the key. With these configured,
the three runners need no arguments; see [RUNNING.md](RUNNING.md).

## Checks

```bash
python benchmarking/server/check_setup.py --agent oceanx
ocean doctor && ocean sandbox-self-check
python -m pytest benchmarking/tests -q
```

Accounts:
- **CMEMS downloads:** `copernicusmarine login`, once.
- **ERA5:** the anonymous Google mirror.
- **NOAA products:** anonymous HTTPS.
