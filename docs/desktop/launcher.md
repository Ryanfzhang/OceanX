# Desktop: one launcher and one configuration

From a source checkout, use `scripts/run_desktop.sh` and `desktop.toml`.
The script calls the existing `npm start`: its sidecar check, build, Electron,
project catalog, model helpers, agents, cleanup and task execution are unchanged.

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

The script reads `desktop.toml`, passes the map key to the original frontend
build, and uses the active Python environment for the native backend and
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
their original behavior. A map key from `desktop.toml` overrides the legacy
frontend `.env.local` during the build, so it need not be edited separately.

For configuration validation without opening the app or writing runtime state:

```sh
bash scripts/run_desktop.sh --check
```

`--config /path/to/desktop.toml` selects a different file. The normal entry remains
the same script. `npm start`, development commands and installed desktop packages
remain available for their original uses; no installed package behavior changes.
