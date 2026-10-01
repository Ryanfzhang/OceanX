#!/usr/bin/env python3
"""Fixed-manifest acquisition of the benchmark inputs, plus a check of owner-staged private data."""
import argparse
import copy
from contextlib import contextmanager, ExitStack
import json
from pathlib import Path

import download_data as erddap
import download_services as services
import ncei_oisst

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
MANIFEST = HERE / "data_manifest.json"
SUITES = {"Q": BENCH / "tasks", "E": BENCH / "evolution"}
EVALUATOR_ONLY = "_evaluator_only"


def task_folder(task_id):
    return SUITES[task_id[0]] / task_id


def load_manifest():
    """The manifest and the task files must describe the same catalogue."""
    manifest = json.loads(MANIFEST.read_text())
    groups = manifest["groups"]
    catalogue = {p.name for root in SUITES.values() for p in root.iterdir() if (p / "task_info.json").is_file()}
    if set(manifest["tasks"]) != catalogue:
        raise ValueError(f"Manifest tasks differ from the catalogue: {sorted(set(manifest['tasks']) ^ catalogue)}")
    for task, needed in manifest["tasks"].items():
        if not needed or any(group not in groups for group in needed):
            raise ValueError(f"Undefined input group: {task}")
        if any(groups[group].get("evaluator_only") for group in needed):
            raise ValueError(f"{task}: evaluator-only data must never be an agent input")
        info = json.loads((task_folder(task) / "task_info.json").read_text())
        if info["data_groups"] != needed or info["catalog_version"] != manifest["version"]:
            raise ValueError(f"Catalogue/manifest mismatch: {task}")
    for task, needed in manifest["evaluator_groups"].items():
        if any(not groups.get(group, {}).get("evaluator_only") for group in needed):
            raise ValueError(f"{task}: evaluator groups must be marked evaluator_only")
    return manifest


def group_plan(group, metadata=erddap.get_json):
    if group["adapter"] == "erddap":
        config = erddap.load_config(HERE / "download_config.json")
        job = copy.deepcopy(next(p for p in config["products"] if p["id"] == group["product"]))
        job.update({key: group[key] for key in ["variables", "data_type", "start", "end", "bbox"]})
        result = erddap.plan_product(job, metadata)
        if result["missing_periods"]:
            raise erddap.DownloadError(f"Provider is missing required periods: {result['missing_periods'][:12]}; no gap-filling or incomplete success")
        return result["chunks"]
    if group["adapter"] == "ncei":
        return ncei_oisst.plan(group)
    if group["adapter"] not in {"cmems", "era5"}:
        raise ValueError(f"{group['adapter']} groups are not downloaded")
    chunks = []
    surface = group.get("surface_variables", ["zos"])
    for variable in group["variables"]:
        # Surface fields have no depth axis, unlike 3-D hydrography.
        depth = group.get("depth") if variable not in surface else None
        selected = services.build_plan(group["adapter"], [variable], group["years"], group["months"],
                                       group["bbox"], group.get("dataset"), group.get("dataset_version"), depth)
        for chunk in selected:
            chunk["data_type"] = group["data_type"]
            chunk["expected_grid_step"] = group.get("grid_step", 1 / 12 if group["adapter"] == "cmems" else 0.25)
            chunk["request_sha256"] = erddap.fingerprint({k: v for k, v in chunk.items() if k not in {"request_sha256", "relative_path"}})
            label = "era5_hourly" if group["adapter"] == "era5" else (
                "cmems_monthly" if "_P1M" in group.get("dataset", "") else "cmems_daily")
            chunk["relative_path"] = erddap.archive_path({"id": label, "data_type": group["data_type"]}, variable, chunk["period"], chunk["request_sha256"])
        chunks.extend(selected)
    return chunks


def private_folder(root, group, folder):
    base = root / EVALUATOR_ONLY if group.get("evaluator_only") else root
    return base / group["data_type"] / folder


def check_private(group, root):
    """Owner-staged data: every variable/year folder holds a readable NetCDF file naming that variable."""
    import netCDF4
    missing, unreadable, files = [], [], 0
    for folder in group["folders"]:
        years = [None] if folder == "grid" else group["years"]
        for year in years:
            directory = private_folder(root, group, folder) / (str(year) if year else "")
            found = sorted(p for p in directory.glob("*.nc") if p.is_file() and p.stat().st_size) if directory.is_dir() else []
            if not found:
                missing.append(str(directory.relative_to(root)))
                continue
            files += len(found)
            if folder != "grid":
                try:
                    with netCDF4.Dataset(found[0]) as ds:
                        if folder not in ds.variables:
                            unreadable.append(f"{found[0].relative_to(root)}: no variable {folder}")
                except OSError as exc:
                    unreadable.append(f"{found[0].relative_to(root)}: {exc}")
    return {"complete": not missing and not unreadable, "files": files, "missing": missing,
            "unreadable": unreadable, "optional": bool(group.get("optional"))}


def verify_existing(group, chunks, root):
    """Never trust filenames alone. Recheck both request identity and file SHA256."""
    def no_network(url, destination, timeout):
        raise erddap.DownloadError(f"Missing file: {destination}")
    for chunk in chunks:
        erddap.transfer(chunk, root, runner=no_network)


def coverage(manifest, reports):
    ready = {key: bool(report.get("complete") and report.get("group_sha256") == erddap.fingerprint(manifest["groups"][key]))
             for key, report in reports.items() if key in manifest["groups"]}
    tasks = {}
    for task, needed in manifest["tasks"].items():
        oracle = manifest.get("evaluator_groups", {}).get(task, [])
        tasks[task] = {"numerical_inputs_complete": all(ready.get(g, False) for g in needed),
                       "missing_groups": [g for g in needed if not ready.get(g, False)],
                       "evaluator_inputs_complete": all(ready.get(g, False) for g in oracle),
                       "missing_evaluator_groups": [g for g in oracle if not ready.get(g, False)]}
    complete = sum(t["numerical_inputs_complete"] for t in tasks.values())
    return {"catalogue": manifest["version"], "all_numerical_inputs_complete": complete == len(tasks),
            "complete_tasks": complete, "tasks": tasks,
            "scope": "Numerical inputs only. This is not validated reference answers or scientific result correctness."}


def bindings(manifest):
    """Agent-visible data folders per task, relative to the data root. Evaluator-only groups never appear."""
    result = {}
    for task, needed in manifest["tasks"].items():
        paths = []
        for key in needed:
            group = manifest["groups"][key]
            paths += [f"{group['data_type']}/{folder}" for folder in group["folders"]]
        result[task] = {"datasets": list(dict.fromkeys(paths))}
    return result


@contextmanager
def phase_lock(root, phase):
    """Different download phases share the archive; verify/legacy tools exclude both."""
    import fcntl
    with ExitStack() as stack:
        # Network filesystems may implement flock via POSIX byte-range locks:
        # shared locks need a readable descriptor; exclusive locks need writable.
        archive = stack.enter_context((root / ".download.lock").open("a+"))
        try:
            mode = fcntl.LOCK_EX if phase == "verify" else fcntl.LOCK_SH
            fcntl.flock(archive, mode | fcntl.LOCK_NB)
            if phase != "verify":
                lock = stack.enter_context((root / f".download.{phase}.lock").open("a"))
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise erddap.DownloadError(
                f"Download lock busy for {phase}: same phase, verification, or a legacy downloader is running. "
                "Restart legacy downloads with the updated script before running phases together."
            ) from exc
        yield


def refresh_summary(control, manifest):
    """Serialize shared outputs and rebuild from current reports, never a stale snapshot."""
    import fcntl
    with (control / ".summary.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        reports = {}
        for key in manifest["groups"]:
            path = control / f"{key}.report.json"
            if path.exists():
                reports[key] = json.loads(path.read_text())
        result = coverage(manifest, reports)
        erddap.write_json(control / "coverage.json", result)
        erddap.write_json(control / "data_bindings.json", bindings(manifest))
        erddap.write_json(control / "masks.json", manifest["masks"])
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["public", "services", "private", "verify"])
    parser.add_argument("--output", type=Path, required=True, help="The data root shared by all phases")
    parser.add_argument("--execute", action="store_true", help="Download; otherwise show the fixed scope without network calls")
    parser.add_argument("--workers", type=services.positive_workers, default=2,
                        help="Concurrent CMEMS/ERA5 chunks (default: 2; 1 restores serial). Public/verify stay serial.")
    parser.add_argument("--groups", nargs="+",
                        help="Only these groups of the phase, e.g. P_TAS_PHY P_TAS_SURF P_TAS_BGC; default: all of them")
    args = parser.parse_args(argv)
    manifest = load_manifest()
    root = args.output.expanduser().resolve()
    if root == Path(root.anchor):
        raise ValueError("Choose a dedicated data directory")
    if args.phase == "verify":
        selected = {k: g for k, g in manifest["groups"].items() if g["phase"] != "private"}
    else:
        selected = {k: g for k, g in manifest["groups"].items() if g["phase"] == args.phase}
    if args.groups:
        if set(args.groups) - set(selected):
            raise ValueError(f"Not groups of the {args.phase} phase: {sorted(set(args.groups) - set(selected))}")
        selected = {key: selected[key] for key in args.groups}
    if not args.execute and args.phase not in {"verify", "private"}:
        for key, group in selected.items():
            print(key, json.dumps(group))
        print("Offline preview only. Add --execute. No data or credentials checked.")
        return 0
    root.mkdir(parents=True, exist_ok=True)
    with phase_lock(root, args.phase):
        control = erddap.safe_destination(root, "_download_all")
        control.mkdir(exist_ok=True)
        failed = False
        for key, group in selected.items():
            report = {"group_sha256": erddap.fingerprint(group), "complete": False, "completed_files": 0,
                      "workers": args.workers if args.phase == "services" else 1, "failed_files": []}
            report_path = control / f"{key}.report.json"
            plan_path = control / f"{key}.plan.json"
            print(f"{key}: checking ...", flush=True)
            if args.phase == "private":
                report.update(check_private(group, root))
                report["completed_files"] = report["files"]
                erddap.write_json(report_path, report)
                state = "complete" if report["complete"] else ("missing (optional)" if report["optional"] else "INCOMPLETE")
                print(f"{key}: {state}; {report['files']} files; missing {report['missing'][:5]}", flush=True)
                failed = failed or (not report["complete"] and not report["optional"])
                continue
            erddap.write_json(report_path, report)
            refresh_summary(control, manifest)
            try:
                if args.phase == "verify":
                    saved = json.loads(plan_path.read_text())
                    if saved["group_sha256"] != report["group_sha256"]:
                        raise ValueError("Saved request plan is from a different manifest")
                    chunks = saved["chunks"]
                    if not chunks or saved["plan_sha256"] != erddap.fingerprint(chunks):
                        raise ValueError("Saved request plan is empty or corrupted")
                else:
                    chunks = group_plan(group)
                    erddap.write_json(plan_path, {"group_sha256": report["group_sha256"], "plan_sha256": erddap.fingerprint(chunks), "chunks": chunks})
                report["expected_files"] = len(chunks)
                def record(result, report=report, key=key, chunks=chunks, report_path=report_path):
                    report["completed_files"] += 1
                    print(f"{key}: {report['completed_files']}/{len(chunks)} {result['path']}", flush=True)
                    erddap.write_json(report_path, report)
                if args.phase == "verify":
                    verify_existing(group, chunks, root)
                    report["completed_files"] = len(chunks)
                elif group["adapter"] == "ncei":
                    ncei_oisst.execute(chunks, root, record)
                elif group["adapter"] in {"cmems", "era5"}:
                    for result in services.execute_chunks(chunks, root, args.workers):
                        if "error_type" in result:
                            report["failed_files"].append(result)
                            erddap.write_json(report_path, report)
                            print(f"{key}: chunk FAILED ({result['error_type']}) {result['path']}", flush=True)
                        else:
                            record(result)
                    if report["failed_files"]:
                        raise erddap.DownloadError("Some service chunks failed; verified files retained")
                else:
                    for chunk in chunks:
                        record(erddap.transfer(chunk, root))
                report["complete"] = report["completed_files"] == report["expected_files"] and bool(chunks)
            except Exception as exc:
                # Provider exceptions can contain credential-bearing URLs. Do not persist them.
                report["error_type"] = type(exc).__name__
                if group["phase"] == "public":
                    report["error"] = str(exc)
                print(f"{key}: FAILED ({type(exc).__name__}). Check connectivity/account/product availability and rerun; verified files are retained.", flush=True)
                failed = True
            erddap.write_json(report_path, report)
            refresh_summary(control, manifest)
        result = refresh_summary(control, manifest)
        print(f"Numerical input coverage: {result['complete_tasks']}/{len(result['tasks'])} tasks. Report: {control / 'coverage.json'}")
        return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, erddap.DownloadError) as exc:
        raise SystemExit(f"ERROR: {exc}")
    except KeyboardInterrupt:
        raise SystemExit("Interrupted. Verified files retained; rerun the same command.")
