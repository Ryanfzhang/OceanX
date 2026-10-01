from __future__ import annotations

import xarray as xr

from oceanx.analysis_probe import inspect_source


def test_analysis_probe_builds_metadata_without_loading_scientific_result(tmp_path) -> None:
    path = tmp_path / "ocean.nc"
    xr.Dataset(
        {
            "temperature": (
                ("time", "depth", "latitude", "longitude"),
                [[[[27.0, 28.0], [26.0, 27.5]]]],
                {"units": "degC", "standard_name": "sea_water_temperature"},
            )
        },
        coords={
            "time": ("time", [0], {"axis": "T"}),
            "depth": ("depth", [10.0], {"axis": "Z", "units": "m", "positive": "down"}),
            "latitude": ("latitude", [24.0, 25.0], {"standard_name": "latitude"}),
            "longitude": ("longitude", [-91.0, -90.0], {"standard_name": "longitude"}),
        },
    ).to_netcdf(path)

    context = inspect_source(
        {
            "handle": "source_1",
            "kind": "dataset",
            "title": "Ocean fixture",
            "path": str(path),
            "format": "netcdf",
        }
    )

    assert context["inspection"] == "ready"
    assert context["dimensions"] == {
        "time": 1,
        "depth": 1,
        "latitude": 2,
        "longitude": 2,
    }
    assert context["data_variables"][0]["name"] == "temperature"
    assert {item["coordinate_role"] for item in context["coordinates"]} == {
        "time",
        "depth",
        "latitude",
        "longitude",
    }
    assert context["spatial_context"] == {
        "region_key": "dataset:-91.000000,24.000000,-90.000000,25.000000",
        "bounds": [-91.0, 24.0, -90.0, 25.0],
        "fit_policy": "region_change",
    }


def test_analysis_probe_inspects_a_dataset_collection_without_opening_the_root_as_zarr(
    tmp_path,
) -> None:
    root = tmp_path / "cmems"
    root.mkdir()
    for name, variable in (("temperature", "thetao"), ("salinity", "so")):
        xr.Dataset(
            {
                variable: (
                    ("time", "depth", "latitude", "longitude"),
                    [[[[27.0, 28.0], [26.0, 27.5]]]],
                    {"units": "degC" if variable == "thetao" else "1e-3"},
                )
            },
            coords={
                "time": ("time", [0], {"axis": "T"}),
                "depth": ("depth", [10.0], {"axis": "Z", "units": "m"}),
                "latitude": ("latitude", [24.0, 25.0], {"axis": "Y"}),
                "longitude": ("longitude", [-91.0, -90.0], {"axis": "X"}),
            },
        ).to_zarr(root / f"{name}.zarr", mode="w")

    context = inspect_source(
        {
            "handle": "source_1",
            "kind": "dataset",
            "title": "CMEMS collection",
            "path": str(root),
            "format": "directory",
        }
    )

    assert context["inspection"] == "ready"
    assert context["dataset_layout"] == "collection"
    assert context["member_count"] == 2
    assert {member["data_variables"][0]["name"] for member in context["members"]} == {
        "thetao",
        "so",
    }
    assert context["spatial_context"]["bounds"] == [-91.0, 24.0, -90.0, 25.0]


def test_a_linked_local_folder_or_file_is_described_only_when_it_holds_data(tmp_path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    xr.Dataset({"temp": ("time", [20.0, 21.0], {"units": "degC"})}).to_netcdf(data / "t_2025.nc")
    (data / "notes.txt").write_text("not data")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "readme.md").write_text("no arrays here")
    table = tmp_path / "stations.csv"
    table.write_text("station,temp\nA,20.5\n")

    def linked(path, format_hint):
        return inspect_source({"handle": "source_1", "kind": "project_context", "title": path.name,
                               "path": str(path), "format": format_hint})

    folder = linked(data, "directory")
    assert (folder["inspection"], folder["member_count"]) == ("ready", 1)
    assert folder["members"][0]["data_variables"][0]["name"] == "temp"
    assert linked(table, "csv")["data_variables"][1]["name"] == "temp"
    # A folder or file without arrays or tables is not a failed inspection.
    assert linked(docs, "directory") == {"handle": "source_1", "kind": "project_context",
                                         "title": "docs", "path": str(docs), "format": "directory",
                                         "inspection": "not_a_dataset"}
    assert linked(docs / "readme.md", "md")["inspection"] == "not_a_dataset"
