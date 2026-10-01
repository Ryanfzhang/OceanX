# Downloads

`data_manifest.json` is the single machine-readable list of the benchmark's data. `download_all.py` runs
it in four phases on the server:

| Phase | What | Network |
|---|---|---|
| `public` | NOAA OISST (NCEI originals, cropped) and MODIS chlorophyll (ERDDAP) | anonymous HTTPS |
| `services` | Copernicus Marine (GLORYS12 physics, the global biogeochemical reanalysis) and ERA5 (Google ARCO mirror) | CMEMS login |
| `private` | Checks the owner-staged CMOMS folders, the requested diagnostics and the evaluator-only budget files | none |
| `verify` | Re-checks every downloaded file's request identity and SHA-256 | none |

```bash
python benchmarking/download/download_all.py public --output "$DATA_ROOT"              # preview only
python -u benchmarking/download/download_all.py public   --output "$DATA_ROOT" --execute
python -u benchmarking/download/download_all.py services --output "$DATA_ROOT" --execute --workers 2
python benchmarking/download/download_all.py private --output "$DATA_ROOT"
python benchmarking/download/download_all.py verify  --output "$DATA_ROOT"
```

How the downloader behaves:
- **Layout:** one variable per file, `<data type>/<variable>/<year>/...`; native time sampling and values
  are kept.
- **Re-runs:** verified files are skipped; corrupt or foreign files are never overwritten; a failed group
  makes the phase return non-zero.
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
