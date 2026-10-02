"""Unified downloader completeness and original-source subsetting; no live network or keys."""
import copy
import json
from pathlib import Path

import netCDF4
import numpy as np
import pytest


def _refresh_in_process(control, manifest, key):
    import download_all as module
    import download_data as data
    data.write_json(control / f"{key}.report.json", {
        "complete": True, "group_sha256": data.fingerprint(manifest["groups"][key]),
    })
    for _ in range(10):
        module.refresh_summary(control, manifest)

import download_all as all_data
import download_data as down
import ncei_oisst as ncei
from test_download_data import job, provider


def save_plan(path, group, chunks):
    down.write_json(path, {"group_sha256": down.fingerprint(group),
                           "plan_sha256": down.fingerprint(chunks), "chunks": chunks})


def archive_fixture(root, chunk):
    final = down.safe_destination(root, chunk["relative_path"])
    down.ensure_collection(final, chunk)
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(b"verified archive fixture")
    down.write_json(final.with_suffix(".receipt.json"), {
        "request_sha256": chunk["request_sha256"], "sha256": down.file_hash(final),
        "bytes": final.stat().st_size,
    })


def test_complete_public_group_skips_provider_metadata_and_counts_reused_files(tmp_path, monkeypatch):
    group = {"phase": "public", "adapter": "erddap", "data_type": "TEST",
             "folders": ["chlor_a"]}
    manifest = {"version": "test", "groups": {"p": group}, "tasks": {"Q01": ["p"]}, "masks": {}}
    chunks = down.plan_product(job(), provider())["chunks"]
    for chunk in chunks:
        archive_fixture(tmp_path, chunk)
    save_plan(tmp_path / "_download_all/p.plan.json", group, chunks)
    monkeypatch.setattr(all_data, "load_manifest", lambda: manifest)

    def offline(*args, **kwargs):
        pytest.fail("A complete saved group must not contact the provider")

    monkeypatch.setattr(all_data, "group_plan", offline)
    monkeypatch.setattr(down, "curl", offline)
    assert all_data.main(["public", "--output", str(tmp_path), "--execute"]) == 0
    report = json.loads((tmp_path / "_download_all/p.report.json").read_text())
    assert report["complete"] and report["plan_source"] == "saved"
    assert report["skipped_files"] == 3 and report["downloaded_files"] == 0


def test_missing_public_observation_refreshes_metadata_and_only_downloads_the_gap(tmp_path, monkeypatch):
    group = {"adapter": "erddap"}
    chunks = down.plan_product(job(), provider())["chunks"]
    archive_fixture(tmp_path, chunks[0])
    path = tmp_path / "plan.json"
    save_plan(path, group, chunks)
    refreshed = []
    monkeypatch.setattr(all_data, "group_plan", lambda g: refreshed.append(g) or chunks)
    planned, source = all_data.acquisition_plan(group, path, tmp_path)
    assert source == "current" and refreshed == [group]
    downloads = []

    def fetch(url, destination, timeout):
        downloads.append(url)
        destination.write_bytes(b"new download fixture")

    records = [down.transfer(c, tmp_path, runner=fetch, verifier=lambda *a: {"chlor_a": 1})
               for c in planned]
    assert len(downloads) == 2
    assert [r["state"] for r in records] == ["verified_existing", "downloaded", "downloaded"]


def test_erddap_extension_reuses_old_observations_even_if_provider_indices_shift(tmp_path, monkeypatch):
    chunks = down.plan_product(job(), provider())["chunks"]
    archive_fixture(tmp_path, chunks[0])
    path = tmp_path / "plan.json"
    old_group, new_group = {"adapter": "erddap", "end": "2011-01"}, {"adapter": "erddap", "end": "2011-03"}
    save_plan(path, old_group, chunks[:1])
    current = copy.deepcopy(chunks)
    current[0]["url"] += "changed-time-index"
    current[0]["request_sha256"] = "new-index-hash"
    current[0]["relative_path"] = chunks[0]["relative_path"].replace(chunks[0]["request_sha256"][:16], "new-index-hash")
    monkeypatch.setattr(all_data, "group_plan", lambda g: current)
    planned, source = all_data.acquisition_plan(new_group, path, tmp_path)
    assert source == "current" and planned == chunks
    assert down.transfer(planned[0], tmp_path)["state"] == "verified_existing"


@pytest.mark.parametrize("change", ["dataset", "version_label", "provider_processing_version", "expected", "relative_path"])
def test_erddap_reuse_never_substitutes_a_different_product_grid_time_or_archive(tmp_path, change):
    chunk = down.plan_product(job(), provider())["chunks"][0]
    archive_fixture(tmp_path, chunk)
    current = copy.deepcopy(chunk)
    current[change] = ({**chunk["expected"], "time": {"count": 1, "first": "2011-01-01", "last": "2011-01-01"}}
                       if change == "expected" else "different")
    assert all_data.reuse_erddap_chunks([current], {"chunks": [chunk]}, tmp_path) == [current]


def test_saved_plan_identity_and_integrity_are_checked(tmp_path):
    group = {"adapter": "cmems"}
    chunks = down.plan_product(job(), provider())["chunks"]
    path = tmp_path / "plan.json"
    save_plan(path, group, chunks)
    assert all_data.saved_plan(path, group)["chunks"] == chunks
    assert all_data.saved_plan(path, {"adapter": "ncei"}) is None
    saved = json.loads(path.read_text())
    saved["chunks"].pop()
    down.write_json(path, saved)
    with pytest.raises(ValueError, match="corrupted"):
        all_data.saved_plan(path, group)


def test_cached_corrupt_file_fails_without_redownload(tmp_path, monkeypatch):
    group = {"adapter": "erddap"}
    chunks = down.plan_product(job(), provider())["chunks"]
    for chunk in chunks:
        archive_fixture(tmp_path, chunk)
    path = tmp_path / "plan.json"
    save_plan(path, group, chunks)
    (tmp_path / chunks[0]["relative_path"]).write_bytes(b"corrupt")
    monkeypatch.setattr(all_data, "group_plan", lambda g: pytest.fail("must stay offline"))
    planned, source = all_data.acquisition_plan(group, path, tmp_path)
    assert source == "saved"
    with pytest.raises(down.DownloadError, match="mismatch"):
        down.transfer(planned[0], tmp_path)


def test_catalogue_groups_and_coverage():
    m = all_data.load_manifest()
    assert len(m["tasks"]) == 54 and len(m["groups"]) == 16
    assert {g["adapter"] for g in m["groups"].values()} == {"cmems", "era5", "erddap", "ncei", "private"}
    assert all(not m["groups"][g].get("evaluator_only") for groups in m["tasks"].values() for g in groups)
    assert m["evaluator_groups"] == {}
    assert not {"X_HEAT", "X_OXY"} & m["groups"].keys()
    assert not all_data.coverage(m, {})["all_numerical_inputs_complete"]
    reports = {key: {"complete": True, "group_sha256": down.fingerprint(g)} for key, g in m["groups"].items()}
    status = all_data.coverage(m, reports)
    assert status["all_numerical_inputs_complete"] and status["complete_tasks"] == 54
    assert status["tasks"]["Q11"]["evaluator_inputs_complete"]
    reports["P_GULF"]["complete"] = False
    status = all_data.coverage(m, reports)
    assert not status["tasks"]["Q09"]["numerical_inputs_complete"]
    assert status["tasks"]["Q01"]["numerical_inputs_complete"]
    reports["P_CCS_BGC"]["group_sha256"] = "old"
    assert not all_data.coverage(m, reports)["tasks"]["E03"]["numerical_inputs_complete"]
    status = all_data.coverage(m, reports)
    for task in ["Q05", "Q11", "Q12", "Q13"]:
        assert status["tasks"][task]["missing_evaluator_groups"] == []
        # No extra native-budget archive is needed. Reference freezing is separate.
        assert status["tasks"][task]["evaluator_inputs_complete"]


def test_evaluator_groups_are_never_agent_inputs(tmp_path, monkeypatch):
    m = json.loads(all_data.MANIFEST.read_text())
    hidden_variables = {folder for group in m["groups"].values() if group.get("evaluator_only")
                        for folder in group["folders"]}
    for binding in all_data.bindings(m).values():
        assert not any(p.startswith("_evaluator_only") or Path(p).name in hidden_variables
                       for p in binding["datasets"])
    m["groups"]["TEST_ORACLE"] = {"evaluator_only": True}
    m["tasks"]["Q11"] = m["tasks"]["Q11"] + ["TEST_ORACLE"]
    leaked = tmp_path / "data_manifest.json"
    leaked.write_text(json.dumps(m))
    monkeypatch.setattr(all_data, "MANIFEST", leaked)
    with pytest.raises(ValueError, match="evaluator-only|mismatch"):
        all_data.load_manifest()


@pytest.mark.parametrize("key,task,variables", [
    ("C_PRODUCTION", "Q14", ["P_Production", "NO3_uptake"]),
    ("C_CARBON", "Q16", ["CO2_airsea", "pCO2"]),
])
def test_requested_diagnostics_only_bind_and_block_their_question(tmp_path, key, task, variables):
    m = all_data.load_manifest()
    group = m["groups"][key]
    assert group["adapter"] == "private" and group["availability"] == "requested"
    assert group["years"] == list(range(2011, 2021))
    report = all_data.check_private(group, tmp_path)
    assert not report["complete"]
    assert report["missing"] == [f"CMOMS_DIA/{v}/{year}" for v in variables for year in range(2011, 2021)]
    paths = {f"CMOMS_DIA/{v}" for v in variables}
    bindings = all_data.bindings(m)
    assert paths <= set(bindings[task]["datasets"])
    assert all(not paths & set(binding["datasets"]) for t, binding in bindings.items() if t != task)
    reports = {k: {"complete": True, "group_sha256": down.fingerprint(g)} for k, g in m["groups"].items()}
    reports[key]["complete"] = False
    status = all_data.coverage(m, reports)
    assert status["complete_tasks"] == 53
    assert status["tasks"][task]["missing_groups"] == [key]
    assert all(state["numerical_inputs_complete"] for t, state in status["tasks"].items() if t != task)


def test_arabian_sea_groups_plan_correctly():
    m = all_data.load_manifest()
    phy = all_data.group_plan(m["groups"]["P_ARAB_PHY"])
    assert len(phy) == 10 * 12 * 6 and all(c["bbox"] == [47, 70, 4, 26] for c in phy)
    assert all(c["relative_path"].startswith("CMEMS_ARABIAN_MONTHLY/") for c in phy)
    bgc = all_data.group_plan(m["groups"]["P_ARAB_BGC"])
    assert len(bgc) == 10 * 12 * 3 and all(c["expected_grid_step"] == 0.25 for c in bgc)
    assert "P_WIND" not in m["groups"]


def test_evolution_groups_plan_correctly():
    m = all_data.load_manifest()
    phy = all_data.group_plan(m["groups"]["P_CCS_PHY"])
    assert len(phy) == 10 * 12 * 6 and all(c["expected_samples"] == 1 for c in phy)
    assert all(("maximum_depth" in c["request"]) == (c["variables"][0] not in {"zos", "mlotst"}) for c in phy)
    assert all(c["relative_path"].startswith("CMEMS_CCS_MONTHLY/") and "/cmems_monthly_" in c["relative_path"] for c in phy)
    surface = all_data.group_plan(m["groups"]["P_CCS_SURF"])
    assert len(surface) == 28 * 12 and all(c["request"]["maximum_depth"] == 1 for c in surface)
    assert all("/cmems_daily_" in c["relative_path"] for c in surface)
    bgc = all_data.group_plan(m["groups"]["P_CCS_BGC"])
    assert len(bgc) == 28 * 12 * 3 and all(c["expected_grid_step"] == 0.25 for c in bgc)
    assert {c["request"]["dataset_id"] for c in bgc} == {"cmems_mod_glo_bgc_my_0.25deg_P1M-m"}


def test_second_evolution_set_groups_plan_correctly():
    m = all_data.load_manifest()
    box = [147, 162, -46, -26]
    phy = all_data.group_plan(m["groups"]["P_TAS_PHY"])
    assert len(phy) == 10 * 12 * 6 and all(c["bbox"] == box and c["expected_samples"] == 1 for c in phy)
    assert all(c["relative_path"].startswith("CMEMS_TASMAN_MONTHLY/") for c in phy)
    request = phy[0]["request"]
    assert [request[k] for k in ("minimum_longitude", "maximum_longitude", "minimum_latitude",
                                 "maximum_latitude")] == box
    surface = all_data.group_plan(m["groups"]["P_TAS_SURF"])
    assert len(surface) == 28 * 12 and all(c["request"]["maximum_depth"] == 1 for c in surface)
    assert all(c["relative_path"].startswith("CMEMS_TASMAN_SURFACE_DAILY/thetao/") for c in surface)
    bgc = all_data.group_plan(m["groups"]["P_TAS_BGC"])
    assert len(bgc) == 28 * 12 * 3 and all(c["expected_grid_step"] == 0.25 for c in bgc)
    assert m["masks"]["tasman_analysis"] == box


def test_groups_option_downloads_only_the_named_groups(tmp_path, monkeypatch):
    groups = {name: {"phase": phase, "adapter": adapter, "data_type": name.upper(), "folders": ["thetao"]}
              for name, phase, adapter in (("a", "services", "cmems"), ("b", "services", "cmems"),
                                           ("p", "public", "erddap"))}
    m = {"version": "test", "groups": groups, "tasks": {"E13": ["a"], "E01": ["b"]}, "masks": {}}
    monkeypatch.setattr(all_data, "load_manifest", lambda: m)
    monkeypatch.setattr(all_data, "group_plan", lambda g: [{"relative_path": g["data_type"] + "/fixture.nc"}])
    monkeypatch.setattr(down, "transfer", lambda chunk, root, **kw: {"path": str(root / chunk["relative_path"])})
    monkeypatch.setattr(all_data.services, "transfer", down.transfer)
    assert all_data.main(["services", "--output", str(tmp_path), "--execute", "--groups", "a"]) == 0
    control = tmp_path / "_download_all"
    assert (control / "a.report.json").exists() and not (control / "b.report.json").exists()
    tasks = json.loads((control / "coverage.json").read_text())["tasks"]
    assert tasks["E13"]["numerical_inputs_complete"] and not tasks["E01"]["numerical_inputs_complete"]
    with pytest.raises(ValueError, match="Not groups of the services phase"):
        all_data.main(["services", "--output", str(tmp_path), "--execute", "--groups", "p"])


def test_private_check_requires_every_variable_year_and_name(tmp_path):
    group = {"data_type": "CMOMS", "folders": ["temp", "grid"], "years": [2011, 2012]}
    assert all_data.check_private(group, tmp_path)["missing"] == ["CMOMS/temp/2011", "CMOMS/temp/2012", "CMOMS/grid"]
    for year in (2011, 2012):
        path = tmp_path / "CMOMS" / "temp" / str(year) / "temp.nc"
        path.parent.mkdir(parents=True)
        with netCDF4.Dataset(path, "w") as ds:
            ds.createDimension("t", 1)
            ds.createVariable("temp" if year == 2011 else "salt", "f4", ("t",))
    (tmp_path / "CMOMS" / "grid").mkdir()
    (tmp_path / "CMOMS" / "grid" / "grid.nc").write_bytes(b"x")
    report = all_data.check_private(group, tmp_path)
    assert not report["complete"] and report["unreadable"] == ["CMOMS/temp/2012/temp.nc: no variable temp"]
    oracle = {"data_type": "CMOMS_DIA", "folders": ["temp_rate"], "years": [2011], "evaluator_only": True, "optional": True}
    assert all_data.check_private(oracle, tmp_path)["missing"] == ["_evaluator_only/CMOMS_DIA/temp_rate/2011"]


def test_service_depth_halo_baselines_and_no_duplicate_bindings():
    m = all_data.load_manifest()
    gulf = all_data.group_plan(m["groups"]["P_GULF"])
    assert len(gulf) == 7 * 12 * 3
    assert len({c["relative_path"] for c in gulf}) == len(gulf)
    assert all(c["relative_path"].startswith("CMEMS_Gulf/") for c in gulf)
    assert all(("maximum_depth" not in c["request"]) == (c["variables"] == ["zos"]) for c in gulf)
    ecs = all_data.group_plan(m["groups"]["P_ECS"])
    assert {int(c["period"][:4]) for c in ecs} == {*range(1993, 2012), 2023}
    assert {int(c["period"][5:]) for c in ecs} == set(range(5, 12))
    assert all(c["bbox"] == [119, 129, 24, 35] for c in ecs)
    for b in all_data.bindings(m).values():
        assert len(b["datasets"]) == len(set(b["datasets"]))
        assert all(len(Path(p).parts) == 2 for p in b["datasets"])


def test_ncei_plan_all_days_and_shared_download(tmp_path, monkeypatch):
    group = copy.deepcopy(all_data.load_manifest()["groups"]["P_OISST"])
    group.update(start="2020-02-28", end="2020-03-01", bbox=[120, 120.5, 25, 25.5])
    chunks = ncei.plan(group)
    assert len(chunks) == 6 and chunks[2]["period"] == "2020-02-29"
    assert "202002/oisst-avhrr-v02r01.20200229.nc" in chunks[2]["url"]
    native = tmp_path / "native.nc"
    with netCDF4.Dataset(native, "w") as ds:
        for name, vals in [("time", [0]), ("zlev", [0]), ("lat", [24.875, 25.125, 25.375, 25.625]), ("lon", [119.875, 120.125, 120.375, 120.625])]:
            ds.createDimension(name, len(vals))
            v = ds.createVariable(name, "f8", (name,))
            v[:] = vals
            v.units = "days since 2020-02-28 12:00:00" if name == "time" else "degrees"
        for name in ["sst", "ice"]:
            v = ds.createVariable(name, "i2", ("time", "zlev", "lat", "lon"), fill_value=-999)
            v.units = "degree_C" if name == "sst" else "%"
            v.scale_factor = 0.01
            v.add_offset = 0.0
            v[:] = np.full((1, 1, 4, 4), 25.3)
    archive = tmp_path / "archive"
    archive.mkdir()
    calls = []
    def fetch(url, destination, timeout):
        calls.append(url)
        destination.write_bytes(native.read_bytes())
    monkeypatch.setattr(ncei, "curl", fetch)
    records = []
    ncei.execute(chunks[:2], archive, records.append)
    assert len(calls) == 1 and len(records) == 2
    for chunk in chunks[:2]:
        path = archive / chunk["relative_path"]
        assert ncei.verify(path, chunk) == {chunk["variables"][0]: 4}
        with netCDF4.Dataset(path) as ds:
            v = ds.variables[chunk["variables"][0]]
            assert np.allclose(v[:], 25.3)
            v.set_auto_maskandscale(False)
            assert np.all(v[:] == 2530)  # packed data not accidentally scaled twice
    ncei.execute(chunks[:2], archive, records.append)
    assert len(calls) == 1
    assert all_data.verify_existing(group, chunks[:2], archive) is None
    (archive / chunks[0]["relative_path"]).write_bytes(b"corrupt")
    with pytest.raises(down.DownloadError):
        all_data.verify_existing(group, chunks[:2], archive)


def test_failed_group_is_not_complete_or_secret_logged(tmp_path, monkeypatch):
    m = {"version": "test", "groups": {"g": {"phase": "services", "adapter": "cmems", "data_type": "CMEMS", "folders": ["thetao"]}}, "tasks": {"Q13": ["g"]}, "masks": {}}
    monkeypatch.setattr(all_data, "load_manifest", lambda: m)
    def fail(group):
        raise RuntimeError("secret=NEVER-LOG-THIS")
    monkeypatch.setattr(all_data, "group_plan", fail)
    assert all_data.main(["services", "--output", str(tmp_path), "--execute"]) == 1
    report = (tmp_path / "_download_all/g.report.json").read_text()
    assert "NEVER-LOG" not in report
    assert not json.loads((tmp_path / "_download_all/coverage.json").read_text())["all_numerical_inputs_complete"]


def test_two_phases_accumulate_coverage_and_verify_detects_missing(tmp_path, monkeypatch):
    groups = {
        "p": {"phase": "public", "adapter": "erddap", "data_type": "MODIS_Aqua", "folders": ["chlorophyll"]},
        "s": {"phase": "services", "adapter": "cmems", "data_type": "CMEMS", "folders": ["thetao"]},
    }
    m = {"version": "test", "groups": groups, "tasks": {"Q21": ["p"], "Q24": ["p", "s"]}, "masks": {}}
    monkeypatch.setattr(all_data, "load_manifest", lambda: m)
    monkeypatch.setattr(all_data, "group_plan", lambda g: [{"relative_path": g["data_type"] + "/fixture.nc"}])
    monkeypatch.setattr(down, "transfer", lambda chunk, root, **kw: {"path": str(root / chunk["relative_path"])})
    monkeypatch.setattr(all_data.services, "transfer", down.transfer)
    assert all_data.main(["public", "--output", str(tmp_path), "--execute"]) == 0
    path = tmp_path / "_download_all/coverage.json"
    assert not json.loads(path.read_text())["all_numerical_inputs_complete"]

    assert all_data.main(["services", "--output", str(tmp_path), "--execute"]) == 0
    assert json.loads(path.read_text())["all_numerical_inputs_complete"]
    def missing(group, chunks, root):
        raise down.DownloadError("Missing fixture")
    monkeypatch.setattr(all_data, "verify_existing", missing)
    assert all_data.main(["verify", "--output", str(tmp_path)]) == 1
    assert not json.loads(path.read_text())["all_numerical_inputs_complete"]


def test_parallel_service_resume_and_failure_preserve_other_files(tmp_path):
    chunks = all_data.group_plan(all_data.load_manifest()["groups"]["P_ERA5"])[:3]
    for chunk in chunks:
        final = down.safe_destination(tmp_path, chunk["relative_path"])
        down.ensure_collection(final, chunk)
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(b"preserved verified download fixture")
        down.write_json(final.with_suffix(".receipt.json"), {
            "request_sha256": chunk["request_sha256"], "sha256": down.file_hash(final),
        })
    records = list(all_data.services.execute_chunks(chunks, tmp_path, workers=2))
    assert len(records) == 3
    assert all(item["state"] == "verified_existing" for item in records)
    damaged = tmp_path / chunks[0]["relative_path"]
    damaged.write_bytes(b"corrupt")
    records = list(all_data.services.execute_chunks(chunks, tmp_path, workers=2))
    assert sum("error_type" in item for item in records) == 1
    assert sum(item.get("state") == "verified_existing" for item in records) == 2
    assert damaged.read_bytes() == b"corrupt"  # No replacement or network redownload.


def test_service_workers_and_duplicate_destinations_are_validated(tmp_path):
    with pytest.raises(SystemExit):
        all_data.main(["services", "--output", str(tmp_path), "--workers", "0"])
    with pytest.raises(down.DownloadError, match="Duplicate"):
        list(all_data.services.execute_chunks([{"relative_path": "same.nc"}] * 2, tmp_path))


def test_phase_locks_allow_different_phases_but_exclude_duplicates_and_verify(tmp_path):
    import fcntl
    with all_data.phase_lock(tmp_path, "public"):
        with all_data.phase_lock(tmp_path, "services"):
            for phase in ["public", "services", "verify"]:
                with pytest.raises(down.DownloadError, match="lock busy"):
                    with all_data.phase_lock(tmp_path, phase):
                        pytest.fail("conflicting phase admitted")
            with (tmp_path / '.download.lock').open('a') as old:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(old, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with all_data.phase_lock(tmp_path, "verify"):
        with pytest.raises(down.DownloadError):
            with all_data.phase_lock(tmp_path, "public"):
                pytest.fail("download during verification")
    with (tmp_path / '.download.lock').open('a') as old:
        fcntl.flock(old, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(down.DownloadError):
            with all_data.phase_lock(tmp_path, "services"):
                pytest.fail("download during legacy writer")


def test_shared_archive_lock_uses_read_write_descriptor(tmp_path, monkeypatch):
    import fcntl
    import os
    original = fcntl.flock
    def network_flock(file, operation):
        if operation & fcntl.LOCK_SH:
            mode = fcntl.fcntl(file.fileno(), fcntl.F_GETFL) & os.O_ACCMODE
            assert mode == os.O_RDWR  # Required for shared/exclusive locking on NFS.
        return original(file, operation)
    monkeypatch.setattr(fcntl, 'flock', network_flock)
    with all_data.phase_lock(tmp_path, 'public'):
        pass


def test_concurrent_summary_writers_retain_both_phase_results(tmp_path):
    from multiprocessing import get_context
    manifest = all_data.load_manifest()
    keys = ['P_MODIS', 'P_GULF']
    ctx = get_context('spawn')
    processes = [ctx.Process(target=_refresh_in_process, args=(tmp_path, manifest, key)) for key in keys]
    for process in processes:
        process.start()
    for process in processes:
        process.join(20)
        if process.is_alive():
            process.terminate()
            process.join()
            pytest.fail('summary writers hung')
        assert process.exitcode == 0
    result = json.loads((tmp_path / 'coverage.json').read_text())
    assert result['tasks']['Q23']['numerical_inputs_complete']      # P_GULF only
    assert not result['tasks']['Q10']['numerical_inputs_complete']  # needs P_OISST, P_ECS, P_ERA5
    assert not result['tasks']['Q22']['numerical_inputs_complete']  # also needs C_CORE
