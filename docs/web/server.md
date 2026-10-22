# Single-user server web entry

Run OceanX on a server, forward its loopback port with SSH, and use the existing
workbench in a browser. This entry is for one owner; multiple browser tabs can
connect to the same project without blocking each other.
It has no account system and no server file browser.

## Build and start

Use the same Python environment as OceanX, with the dependencies in
`pyproject.toml` installed. Build with Node 22.12+ or Node 24:

```sh
cd frontend/ocean-web
npm ci
npm run build
cd ../..
python -m oceanx.web --workspace /srv/oceanx-project \
  --allow-source-root /srv/ocean-data \
  --allow-source-root /srv/papers \
  --port 8765
```

The source roots are server-side settings. They are not listed in the browser.
Use the actual mounted paths visible to the server process. Repeat
`--allow-source-root` for additional source locations.

Configure the native model profiles on the server before starting. The web entry
reads the existing OceanX model configuration; it does not copy credentials into
the frontend or change model settings. To isolate its configuration as well,
set `OCEANMIND_CONFIG_DIR` to a web-specific directory containing the native
`settings.json` and `credentials.json`. Model configuration uses the existing
`python -m oceanx.cli configure-models` interface.

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
