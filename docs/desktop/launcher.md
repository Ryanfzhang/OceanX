# Desktop: one launcher and one configuration

From a source checkout, use `scripts/run_desktop.sh` and `desktop.toml`.
The script calls `npm start`: its sidecar check, Electron,
project catalog, model helpers, agents, cleanup and task execution are unchanged.
A frontend build runs only when source/dependencies changed, outputs are missing
or modified, or no build stamp exists. Configuration changes do not invalidate it.

## First setup

Activate the existing `oceanx` conda environment (Python and Node 24), install the
repository requirements, and install the frontend dependencies once:

```sh
conda activate oceanx
npm --prefix frontend/ocean-desktop ci
cp desktop.example.toml desktop.toml
chmod 600 desktop.toml
```

Fill in `desktop.toml` using your own model API credentials and CARTO browser
map key. The example is committed; the filled-in file is ignored by Git.
`[model]` sets both coordinator and experts. Optional `[models.coordinator]` and
`[models.expert]` override individual fields using the same schema as `web.toml`.
Use either `api_key` or `api_key_env`. Relative paths start at the config file.

## Normal launch

Close any previously running Desktop instance, then from the repository root:

```sh
conda activate oceanx
bash scripts/run_desktop.sh
```

The script reads `desktop.toml`, passes only the browser map key to the Electron main process at runtime, and uses the active Python environment for the native backend and
scientific runtime. `desktop.sandbox_python` optionally selects a different
scientific Python. The launcher does not read `web.toml` or web task state.

Generated native model profiles live under `desktop.runtime_dir` (default
`.oceanx/desktop-launch` relative to the config). They are implementation files,
not another user-edited configuration. Existing `~/.oceanmind` settings and
credentials are preserved. No model probes or requests are made during config
preparation. Your projects, task data and project catalog remain native.

When using this launcher, `desktop.toml` is authoritative at every startup.
API changes made through the original settings dialog affect the generated
profiles for that session; put persistent changes in `desktop.toml` before the
next script launch. Native appearance, language and other UI preferences keep
their original behavior. The map key travels through a narrow preload API at runtime. It is not baked
into frontend assets. No frontend `.env.local` is needed; old files no longer
control the map. Both web and Desktop use the same map style provider. An empty
key, or launching the app without a runtime map key, uses bundled Natural Earth
geography rather than making unauthenticated CARTO tile requests.

For configuration validation without opening the app or writing runtime state:

```sh
bash scripts/run_desktop.sh --check
```

`--config /path/to/desktop.toml` selects a different file. The normal entry remains
the same script. `npm start`, development commands and installed desktop packages
remain available for their original uses. Apps launched without a runtime CARTO
key use the bundled offline map.
