# Single-user server web entry

Run OceanX on a server, forward its loopback port with SSH, and use the existing
workbench in a browser. This entry is for one owner; multiple browser tabs can
connect to the same project without blocking each other.
It has no account system and no server file browser. The sidebar lists tasks
directly; the native workspace remains an internal storage detail. There is no
Review UI, and the web router subclass disables automatic library maintenance
and rejects manual learning requests. Desktop review and learning are unchanged.

## Build and start

Use the same Python environment as OceanX, with the dependencies in
`pyproject.toml` installed. Build with Node 22.12+ or Node 24:

```sh
cd frontend/ocean-web
npm ci
npm run build
cd ../..
mkdir -p /srv/oceanx-config
cp docs/web/web.example.toml /srv/oceanx-config/web.toml
chmod 600 /srv/oceanx-config/web.toml
# Set your API key in web.toml, or export the environment variable it names.
export DEEPSEEK_API_KEY='your-key'
python -m oceanx.web --config /srv/oceanx-config/web.toml \
  --workspace /srv/oceanx-project \
  --allow-source-root /srv/ocean-data \
  --allow-source-root /srv/papers \
  --port 8765
```

The source roots are server-side settings. They are not listed in the browser.
Use the actual mounted paths visible to the server process. Repeat
`--allow-source-root` for additional source locations.

## Model API configuration

`--config` is required. The server-owned TOML file is the single source of model
settings for this web instance; Desktop profiles are never used by the CLI.
Copy [web.example.toml](web.example.toml) and fill in your provider, exact model
ID, base URL, and either `api_key` or `api_key_env`. Supported providers are
`deepseek`, `openai` (including compatible APIs), and `anthropic`.

```toml
[model]
provider = "deepseek"
model = "deepseek-flash"
base_url = "https://api.deepseek.com"
api_key = "your-key"
```

`[model]` applies to both coordinator and experts. Optional `[models.coordinator]`
and `[models.expert]` tables override individual fields for a role. Output limit
`max_tokens` is shared by both roles (default 65536, native minimum 24576).
Omit `image_inputs` to retain native capability detection, or explicitly set it
to true/false for your model.
An environment credential must be exported in the service's environment, including
when started in tmux. Invalid configuration stops startup without quoting secrets.

Keep this file outside the repository, allowed source roots and task folders,
and restrict it to the service owner (`chmod 600`). The web entry writes private
native profiles under `<workspace>/.oceanx-web/model-config` and passes that
directory only to its own backend process. It reuses the native model adapters;
it never modifies `~/.oceanmind`, Desktop configuration or agent implementation.
The browser shows model IDs and configured status, never keys or endpoint URLs.
Restart the web service after editing the file; finish any active task first.

For long sessions, start the command inside a server-side tmux session. Closing
or refreshing the browser, or losing the SSH tunnel, leaves the server's native
research run connected and working. Stopping the web service stops its backend;
it does not promise recovery of an interrupted model run after a server restart.

From the local machine:

```sh
ssh -N -L 8765:127.0.0.1:8765 user@server
```

Open `http://127.0.0.1:8765`. To use a different local port, forward
`8766:127.0.0.1:8765` and open `http://127.0.0.1:8766`. Both listeners bind to loopback. No public bind
option is provided.

## Add data or a PDF

Create a task and use the existing attachment button. Enter the complete server
path to a file or directory. OceanX validates that exact path against the allowed
roots, then uses its existing read-only source import. It does not copy large
source files or offer directory listing, path search, or arbitrary file download.
PDF text extraction uses the existing PDF source support.

Only explicitly granted result files can be downloaded. Downloads verify the
native size and checksum and are bounded to 25 MiB per file. Closing and
reopening a result obtains a fresh grant when its short-lived grant expires.

## Map

The web build reads `VITE_CARTO_BASEMAPS_API_KEY` from its own
`frontend/ocean-web/.env.local`. Copy the existing Desktop CARTO setting there
before building; it is not automatically loaded from the Desktop directory.
The local configuration is ignored by Git. As in Desktop, this browser map key
is included in built assets and visible in tile requests; it is not a model API
credential. A changed key requires rebuilding the web frontend.

With a key, the map uses CARTO tiles. Without one, it uses the repository's
public-domain Natural Earth 1:110m land and coastline geometry. Local geography
also sits below the CARTO layer. Scientific fields and result features continue
to use the native overlays. Desktop's configuration and source are unchanged.

## Web-only retention

The backend subclass uses the original cache cleaner's protected-path and
file-pruning operations, with these defaults:

- Unarchived task intermediates: after 24 hours without task activity.
- Archived task intermediates: after 6 hours.
- Sweep: at startup and once per hour.

Override with `--cache-hours`, `--archived-cache-hours`, and `--sweep-minutes`.
Active requests, working workflows and running executions remain protected.
Bound source files and published result files are retained. Cleanup does not
remove task history or the entire project. Desktop retains its original policy.

Web state lives under `<workspace>/.oceanx-web`; tasks use the native `OceanX Tasks`
project folders. Use a dedicated web workspace rather than opening a Desktop
project concurrently. Neither the original Desktop backend source nor its
renderer is modified. The browser adapter implements the existing bridge; its
private server connection calls the native protocol, task runner, scientific
executor and result interfaces. The two retention classes inherit their native
counterparts.

## Validation

```sh
python -m pytest tests/test_oceanx/test_web_entry.py \
  tests/test_oceanx/test_web_config.py \
  tests/test_oceanx/test_web_native_integration.py \
  tests/test_oceanx/test_cache_cleanup.py \
  tests/test_oceanx/test_static_figure_delivery.py -q
cd frontend/ocean-web
npm run check
npm run build
```

The native integration test launches the real Agent Server with deterministic
test models and synthetic arrays. It checks source binding, task submission,
browser disconnection/reconnection, scientific figure delivery, result grants
and report reading without model-provider requests.
