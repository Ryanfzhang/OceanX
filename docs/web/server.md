# Single-user server web entry

Run directly from the Git checkout and forward its loopback port with SSH.
There is one user-edited configuration file: **`web.toml` in the repository root**.
It controls model APIs, port, workspace, source roots, map and cleanup. The file
is ignored by Git; only the example is committed. Desktop settings and agent
implementation are unchanged.

The sidebar lists tasks directly. There is no account system, filesystem browser,
Review UI or automatic library learning. Multiple browser tabs share the owner's
existing native task backend.

## Install, configure and run

Use an activated Python environment with the repository's `pyproject.toml`
dependencies installed. Use Node 22.12+ or Node 24 to build the frontend:

```sh
# From the repository root:
cp web.example.toml web.toml
chmod 600 web.toml
# Edit web.toml: API credentials, actual workspace and existing source roots.
npm --prefix frontend/ocean-web ci
npm --prefix frontend/ocean-web run build
bash scripts/run_web.sh
```

The launcher always imports Python source from this checkout. It starts
`python -m oceanx.web`, which reads `./web.toml`. To use another config location:

```sh
bash scripts/run_web.sh --config /srv/oceanx/web.toml
```

All relative paths inside the TOML file are resolved relative to that file.
The default frontend is the checkout's `frontend/ocean-web/dist`. There is no
separate release copy to synchronize. An optional local `.web-python-deps`
directory can hold isolated dependencies if the server's shared Python
environment must remain untouched; it contains no user configuration.

A minimal configuration is:

```toml
[server]
workspace = "/srv/oceanx-workspace"
source_roots = ["/srv/ocean-data", "/srv/papers"]
port = 8765

[model]
provider = "deepseek"
model = "deepseek-flash"
base_url = "https://api.deepseek.com"
api_key = "your-key"

[map]
carto_api_key = "your-browser-map-key"

[cleanup]
cache_hours = 24
archived_cache_hours = 6
sweep_minutes = 60
```

Copy the [complete example](../../web.example.toml) for additional settings.
`[model]` applies to coordinator and experts. Optional `[models.coordinator]`
and `[models.expert]` tables override individual fields. Providers are `deepseek`,
`openai` (including compatible APIs), and `anthropic`. Instead of `api_key`, use
`api_key_env` to name an exported environment variable. Output limit `max_tokens`
is shared by both roles (default 65536, native minimum 24576). Omit `image_inputs`
to retain native capability detection, or explicitly set it to true/false.

The config file should not be inside a source root or task folder. Model keys
stay on the server. Private native profiles under `<workspace>/.oceanx-web/model-config`
are generated automatically from `web.toml` on startup; **do not edit them**.
They let the web entry reuse the existing native adapters without modifying
`~/.oceanmind` or Desktop. Restart the web service after changing configuration,
finishing any active task first. Invalid settings stop startup without quoting keys.

## Access and long sessions

Start `bash scripts/run_web.sh` inside tmux with the Python environment activated.
From your local machine:

```sh
ssh -N -L 8766:127.0.0.1:8765 user@server
```

Open `http://127.0.0.1:8766`. Closing a tab or losing the tunnel leaves the native
research run working. Stopping the service stops its backend; restart recovery
of an interrupted model run is not guaranteed. There is no public bind option.

## Logs and task data

`server.workspace` is where tasks, reports and state are kept; existing workspaces
can remain outside the checkout. `server.log_dir` sets the log directory. If
omitted, logs go to `<workspace>/.oceanx-web`:

- `web-console.log`: web gateway startup and access logs, also shown in the terminal.
- `web-agent-server.log`: native task backend logs, appended across restarts.

Changing the code location does not require moving the task data or these logs.
Model API keys and internal filesystem paths are not sent in browser config.
The map key is a browser key, described below.

## Add data or a PDF

Create or select a task and click the attachment button. Enter the complete
server path to a file or directory. OceanX validates the path against source roots
and reuses read-only source import. A successful validation returns the canonical
form of that specific user-entered path to the attachment bridge; it never lists
other server paths. There is no directory listing, search or
copy of large files. PDF text extraction uses native PDF support.

Only explicitly granted result files can be downloaded. Downloads verify native
size/checksum and are bounded to 25 MiB per file. Reopening a result renews a grant.

## Map

`map.carto_api_key` in **the same `web.toml`** controls the map at runtime.
No web `.env.local` or frontend rebuild is needed to change it. The server returns
only this browser map key to the frontend; as in Desktop, it is visible in tile
requests. Model API credentials are never returned. Empty uses the repository's
local Natural Earth 1:110m geography; local geography also sits under CARTO tiles.
Scientific overlays and Desktop map configuration are unchanged.

## Cleanup

The web subclass reuses the native cleaner with shorter retention, set under
`[cleanup]`. Active requests, working workflows, running executions, bound sources
and published results are protected. Only managed intermediates are pruned;
task history and the entire workspace are not removed. Desktop policy is unchanged.

## Validation

```sh
python -m pytest tests/test_oceanx/test_web_entry.py \
  tests/test_oceanx/test_web_config.py \
  tests/test_oceanx/test_web_native_integration.py \
  tests/test_oceanx/test_cache_cleanup.py \
  tests/test_oceanx/test_static_figure_delivery.py -q
npm --prefix frontend/ocean-web run check
npm --prefix frontend/ocean-web run build
```

The native integration test launches the real Agent Server with deterministic
test models and synthetic arrays. No provider calls are made.
