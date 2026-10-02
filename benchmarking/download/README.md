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

The owner's checkout on `macyang9` is `/home/mafzhang/code/OceanX`. Update that checkout with
`git pull --ff-only` before checking the catalogue; similarly named OceanMind directories may belong
to the older repository. The benchmark Python is `/home/mafzhang/miniconda3/envs/oceanx-bench/bin/python`
and the shared data root is `/import/home4/share/mafzhang`.

The 2026-10-01 check against catalogue `2026-10-01-v6` found:

| Group | Existing files / required files | Compatibility |
|---|---:|---|
| P_GULF | 252 / 252 | Exact current request plan |
| P_ECS | 420 / 420 | Exact current request plan |
| P_ERA5 | 560 / 560 | Exact current request plan |
| P_OISST | 30,680 / 30,680 | Exact current request plan |
| P_MODIS | 180 / 216 | Existing 2003–2017 scope matches; 2018–2020 is missing |
| P_ARAB_PHY / P_ARAB_BGC | 0 / 720 + 360 | Not staged |
| P_CCS_PHY / P_CCS_SURF / P_CCS_BGC | 0 / 720 + 336 + 1,008 | Not staged |
| P_TAS_PHY / P_TAS_SURF / P_TAS_BGC | 0 / 720 + 336 + 1,008 | Not staged |

Every listed existing file had a receipt, the saved plan hashes matched, and one file per existing
group passed the downloader's SHA-256 skip check. This was an inventory and sample check, not a new
full-archive hash verification. No scientific data were downloaded or replaced. CMOMS, requested
CMOMS_DIA fields and evaluator-only groups were absent from their prescribed folders in this data root;
that does not establish that the owner has no copies elsewhere. Old NOAA wind files are not inputs to
this catalogue and are left untouched.
