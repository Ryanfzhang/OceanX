# Server data layout and CMOMS staging

Audit: 2026-10-02, `/import/home4/share/mafzhang`, catalogue `2026-10-02-v7`.
The server copy of this inventory is under
`/import/home4/share/mafzhang/_inventory/20261002T084959Z/` (`summary.json`, `README.txt`).
This is an inventory snapshot, not a fresh whole-archive hash verification. Completion
reports currently cover 41/54 numerical-input sets: 17/30 test tasks and all 24 evolution
tasks. Use `prepare_queries.py --available` for the live subset; see [RUNNING.md](RUNNING.md).

## Keep the archive paths stable

| Category | Directories | Treatment |
|---|---|---|
| Active public inputs | `CMEMS_Gulf`, `CMEMS_ECS`, `CMEMS_ARABIAN_*`, `CMEMS_CCS_*`, `CMEMS_TASMAN_*`, `ERA5`, `MODIS_Aqua`, `OISST` | Keep existing names. Download receipts and runner bindings depend on them. |
| Download control | `_download_all`, `.download*.lock` | Keep. They track request identities, file hashes and group completion. Lock-file existence alone does not mean a lock is held. |
| Legacy data | `NOAA_Blended_Wind` | Not used by the current catalogue; retain until its use by other projects is confirmed. |
| Historical outputs | `oceanmind-agent-runs`, `oceanmind-backend-8002.log`, `oceanmind-frontend-3002.log` | Existing analysis history, not benchmark inputs; do not delete or move without checking stored path references. |
| Old acquisition metadata | `_download_all.backup-20260909T125735Z` | Retain as recovery metadata; not current input bindings. |
| Current inventory | `_inventory/` | Human-readable status only; never bind the whole data root to an agent. |
| Private input staging | `CMOMS/<variable>/<year>/*.nc`, `CMOMS/grid/` | Stage only the required years; never mix evaluator references or results here. |
| Requested diagnostics | `CMOMS_DIA/P_Production`, `NO3_uptake`, `CO2_airsea`, `pCO2` | Keep Q14/Q16 excluded until received and checked. |

Put **new** run/evaluation folders outside this root, as in RUNNING.md. The audit found
a services downloader still active; no existing datasets, lock files or old outputs
were moved/deleted. Renaming data folders while downloading would break the saved plans.

P_ECS initially reported 216/420 files during the audit, then finished with 420/420
and no failed files. Q10/Q28/Q29 are now selectable. MODIS's report is complete
(216 files). The Arabian, California Current and Tasman groups also report complete.
No downloader process was confirmed in the final check (the matching SSH diagnostic
shell is not a downloader). The only remaining input groups are private CMOMS.

## Original CMOMS: do not copy the entire 2011-2022 archive

Source: `/import/home4/share/PRE_wavyocean`. The six requested variables are already
separate annual NetCDF files named `CMOMS_<variable>_Zlev_<year>.nc`. The benchmark
only needs 2011-2020 (60 files, about 2.65 TB of logical file sizes).

Both directories were on the same filesystem at audit time. **Hard links** are the
simple zero-extra-data-copy staging option, and unlike symlinks they work with the
current input validator. They add directory entries, not another 2.65 TB copy.
However, they share file contents and permissions: writing either path changes the
same file. They are **not** a backup or a read-only boundary. OceanX/Finch mount inputs
read-only; the current Claude runner has no equivalent OS boundary. Do not run
unrestricted Claude Bash against private hard-linked inputs. Never `chmod` the linked
files to “protect the copy”; that changes the original inode too.

The following owner-run staging command refuses conflicts, skips existing identical
links, limits the years/variables explicitly and never moves/deletes original files:

```bash
(
  set -euo pipefail
  cmoms_source=/import/home4/share/PRE_wavyocean
  cmoms_target=/import/home4/share/mafzhang/CMOMS
  for cmoms_var in temp salt u v oxygen chlorophyll; do
    for cmoms_year in 2011 2012 2013 2014 2015 2016 2017 2018 2019 2020; do
      cmoms_file=CMOMS_${cmoms_var}_Zlev_${cmoms_year}.nc
      cmoms_from=$cmoms_source/$cmoms_file
      cmoms_to=$cmoms_target/$cmoms_var/$cmoms_year/$cmoms_file
      test -f "$cmoms_from"
      if test -e "$cmoms_to" || test -L "$cmoms_to"; then
        test ! -L "$cmoms_to" && test "$cmoms_from" -ef "$cmoms_to" || exit 1
      else
        mkdir -p -m 700 "$cmoms_target/$cmoms_var/$cmoms_year"
        ln "$cmoms_from" "$cmoms_to"
      fi
    done
  done
)
```

No hard links have been created by this audit. Use a separate copy (or filesystem
reflink if supported) if independent mutability is required; do not silently fall
back to a multi-terabyte copy. Do not use symlinks: preparation and Finch intentionally
reject them. Existing parent-directory permissions should be reviewed separately;
do not recursively change the shared source's permissions.

## Grid/conventions are still required

Header samples have 1-D lon/lat, daily-length time axes and fixed-depth `z` coordinates.
The depth list includes `9999`, described as a bottom marker: it is **not** a normal
physical depth level. Sample headers do not establish the entire ten-year archive's
time continuity, wet-mask convention or velocity orientation.

There was no separate grid file in the original source directory. Obtain the real
grid/mask/bathymetry metadata and stage it in `CMOMS/grid/`, with a conventions README
as described in [DATA.md](DATA.md#staging-cmoms-owner). Do not add a dummy `.nc` just to
make the presence checker green. Coordinates alone are not verified bathymetry or
cell areas, and missing scientific metadata must not be invented.

After staging the real grid and checking conventions:

```bash
python benchmarking/download/download_all.py private \
  --output /import/home4/share/mafzhang --groups C_CORE
```

This records core staging readiness without declaring the requested diagnostic
groups complete. It checks folder/file/variable presence, not all scientific
conventions or a whole-archive hash. Keep CMOMS questions excluded until those
checks are satisfied. After the active downloader ends, use `--available` to create
a **new experiment's** query set; never extend a set that is already being compared.
