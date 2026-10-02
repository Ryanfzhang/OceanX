# Downloads

`data_manifest.json` is the single machine-readable list of the benchmark's data. `download_all.py` runs
it in four phases on the server:

| Phase | What | Network |
|---|---|---|
| `public` | NOAA OISST (NCEI originals, cropped) and MODIS chlorophyll (ERDDAP) | anonymous HTTPS |
| `services` | Copernicus Marine (GLORYS12 physics, the global biogeochemical reanalysis) and ERA5 (Google ARCO mirror) | CMEMS login |
| `private` | Checks the owner-staged CMOMS core folders and requested production/carbon diagnostics | none |
| `verify` | Re-checks every downloaded file's request identity and SHA-256 | none |

Catalogue v7 requires no native heat or oxygen budget groups. Q05 and Q11-Q13 reference calculations
use their core inputs and must still be frozen separately before judging.

Longitude validation promotes coordinates to float64 before wrapping, so valid float32 CMEMS grids
at 147-162 E pass the existing spacing tolerance. Missing or irregular grids still fail. To recover
the Tasman files rejected by earlier validation, retain the existing `.nc.part` files and run:

```bash
python -u benchmarking/download/download_all.py services --output "$DATA_ROOT" --execute --workers 2 \
  --groups P_TAS_PHY P_TAS_SURF
```

Each partial is fully validated, hashed and promoted before any provider request; valid partials do
not need another download. Saved requests and all other verified groups remain reusable.

```bash
python benchmarking/download/download_all.py public --output "$DATA_ROOT"              # preview only
python -u benchmarking/download/download_all.py public   --output "$DATA_ROOT" --execute
python -u benchmarking/download/download_all.py services --output "$DATA_ROOT" --execute --workers 2
python benchmarking/download/download_all.py private --output "$DATA_ROOT"
python benchmarking/download/download_all.py verify  --output "$DATA_ROOT"
```

`--groups` limits a phase to the named groups. For example, the second evolution set (Tasman Sea) alone:

```bash
python -u benchmarking/download/download_all.py services --output "$DATA_ROOT" --execute --workers 2 \
  --groups P_TAS_PHY P_TAS_SURF P_TAS_BGC
```

How the downloader behaves:
- **Layout:** one variable per file, `<data type>/<variable>/<year>/...`; native time sampling and values
  are kept.
- **Re-runs:** verified files are skipped; corrupt or foreign files are never overwritten; a failed group
  makes the phase return non-zero.
- **Existing plans:** an intact saved plan for the same group is reused. A fully downloaded ERDDAP group
  can therefore be checked and skipped without contacting the metadata server. Missing observations or
  a changed scope require a fresh provider plan. When extending a time range, existing ERDDAP observations
  keep their original paths even if provider URL indices shift, but only when product, release, grid and
  observation time match; receipt and SHA-256 checks still apply.
- **Progress:** each group reports `skipped_files` and `downloaded_files`, and prints whether its plan came
  from the saved archive or the current specification. Skipping still reads files to verify SHA-256; it
  does not mean instant completion or trusting old coverage reports.
- **Gaps:** a provider missing a requested month or day stops the group (no gap-filling).
- **Two terminals:** `public` and `services` can run at the same time; the same phase twice, or anything
  during `verify`, is refused by locks.
- **Reports:** `$DATA_ROOT/_download_all/coverage.json` (per task: agent inputs complete, answer-key inputs
  complete), `data_bindings.json` (agent folders per task) and per-group `*.report.json` / `*.plan.json`.

Pinned products:
- **CMEMS:** GLORYS12 `202311`; biogeochemical reanalysis `202406`. A retired version fails rather than switching silently.
- **ERA5:** read hour by hour from the public Google mirror, with resumable checkpoints (`*.part.google`);
  do not delete them.
- **OISST:** each day's global original file is fetched, cropped, and the temporary copy deleted.

The adapters are:
- `download_data.py` for ERDDAP and the shared archive helpers;
- `download_services.py` for CMEMS and ERA5;
- `era5_google.py` for the Google mirror reader;
- `ncei_oisst.py` for OISST.

The Gulf of Mexico and East China Sea groups (test suite) are unchanged from the 2026-09 catalogue,
so files downloaded then are verified and reused.

## Server checkout and existing archive

The owner's checkout on `macyang10` is `/home/mafzhang/code/OceanX`. Update that checkout with
`git pull --ff-only` before checking the catalogue; similarly named OceanMind directories may belong
to the older repository. The benchmark Python is `/home/mafzhang/miniconda3/envs/oceanx-bench/bin/python`
and the shared data root is `/import/home4/share/mafzhang`.

The latest 2026-10-02 v7 completion reports cover **41/54** numerical-input sets:
all public input groups are complete, including MODIS (216 files) and P_ECS (420 files).
The remaining 13 questions need CMOMS staging; Q14/Q16 also need requested diagnostics.
This is completion-report readiness, not new whole-archive hash verification or scientific grading.

Keep the current layout and control files intact. For the directory inventory and original CMOMS
staging options, see [SERVER_DATA.md](../SERVER_DATA.md). For partial-data selection and three-method
runs, see [RUNNING.md](../RUNNING.md). Those are the single operational entry points; do not use older
"missing public data" planning notes as the live download status.
