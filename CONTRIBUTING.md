# Contributing to OceanMind

OceanMind is a local-first multi-agent workbench for ocean-science research.

## Development setup

Create the `oceanx` conda environment as described in [INSTALL.md](INSTALL.md), then:

```bash
conda activate oceanx
cd frontend/ocean-desktop
npm ci
```

## Validation

```bash
make test
make lint

cd frontend/ocean-desktop
npm run check
npm test
npm run build
```

For changes to packaging, also build the Python wheel and Desktop sidecar:

```bash
python -m hatchling build -t wheel
python scripts/check_ocean_wheel_contents.py

cd frontend/ocean-desktop
npm run build:sidecar
```

## Pull requests

- Keep changes scoped and preserve existing task history and local research data.
- Add focused tests for behavioral changes.
- Keep scientific claims tied to inspectable evidence and reproducible outputs.
- Update the changelog for user-visible changes.
