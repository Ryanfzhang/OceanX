"""Publish user-facing results directly from Expert-owned code executions."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from oceanx.task_results import TaskResultError, TaskResultRecord, TaskResultStore

MAX_RENDERED_SCIENTIFIC_VALUES = 500_000


class ExpertDeliverableError(RuntimeError):
    """An Expert result cannot be safely materialized as a user-facing deliverable."""


class InvalidResultObjectsError(ExpertDeliverableError):
    """A declared plotted object is invalid and cannot be published silently."""


def interactive_view_cache(
    *,
    record: TaskResultRecord,
    results: TaskResultStore,
    hydrated_payload: dict[str, Any] | None = None,
) -> tuple[Path, bytes]:
    """Return one immutable renderer cache outside the user-facing task files.

    The Expert already hydrates and validates a scientific manifest before it
    becomes a result. Passing that payload here avoids repeating NetCDF I/O
    when the user first opens the view. Cache misses hydrate the current NetCDF.
    """

    data_file = record.content.get("data_file")
    if not isinstance(data_file, str):
        raise ExpertDeliverableError("Interactive result manifest is missing")
    manifest_path = results.file_path(ref=record.ref, relative_path=data_file)
    if manifest_path.suffix.lower() != ".nc":
        raise ExpertDeliverableError("Only current self-describing NetCDF results are supported")
    dataset_file = record.content.get("dataset_file")
    manifest_record = next((item for item in record.files if item.path == data_file), None)
    dataset_record = next(
        (
            item
            for item in record.files
            if isinstance(dataset_file, str) and item.path == dataset_file
        ),
        None,
    )
    identity = hashlib.sha256(
        "\x1f".join(
            (
                "interactive-view-cache/v2",
                record.ref.key,
                manifest_record.sha256 if manifest_record is not None else "",
                dataset_record.sha256 if dataset_record is not None else "",
            )
        ).encode("utf-8")
    ).hexdigest()
    cache_root = results.task_workspaces.paths.cache / "interactive-views"
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path = cache_root / f"{identity}.json"
    if not cache_path.exists():
        payload = hydrated_payload
        if payload is None:
            payload = hydrate_ocean_view_netcdf(manifest_path)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > 25 * 1024 * 1024:
            raise ExpertDeliverableError("Interactive result exceeds the renderer resource limit")
        temporary = cache_path.with_name(f".{cache_path.name}.{uuid4().hex}.tmp")
        temporary.write_bytes(encoded)
        os.chmod(temporary, 0o600)
        os.replace(temporary, cache_path)
    raw = cache_path.read_bytes()
    if len(raw) > 25 * 1024 * 1024:
        raise ExpertDeliverableError("Interactive result exceeds the renderer resource limit")
    return cache_path, raw


def _validate_feature_contract(payload: dict[str, Any], *, spatial: bool = False) -> None:
    from oceanx.scientific_view import validate_result_features

    try:
        features = validate_result_features(payload.get("features", []))
        panels = {panel.get("id") for panel in payload.get("panels", []) if isinstance(panel, dict)}
        for feature in features:
            if not spatial and feature.get("panel_id") not in panels:
                raise ValueError("Feature must identify an existing panel")
            if spatial:

                def check_position(value: Any) -> None:
                    if len(value) == 2 and isinstance(value[0], (int, float)):
                        if not (-180 <= value[0] <= 180 and -90 <= value[1] <= 90):
                            raise ValueError(
                                "Map features require longitude [-180,180] and latitude [-90,90]"
                            )
                    else:
                        for child in value:
                            check_position(child)

                check_position(feature["geometry"]["coordinates"])
    except (ValueError, TypeError) as exc:
        raise InvalidResultObjectsError(f"Invalid result objects: {exc}") from exc


def hydrate_scientific_manifest(payload: Any, dataset_path: Path) -> dict[str, Any]:
    """Resolve one small figure manifest against its immutable NetCDF arrays.

    The persisted result keeps scientific arrays in NetCDF.  Hydration is only
    a viewer boundary: it returns the bounded row-major values expected by the
    renderer without creating another result file or asking an Expert to
    transcribe shapes into JSON.
    """

    if not isinstance(payload, dict) or payload.get("schema_version") not in {
        "ocean-scientific-figure/v4",
    }:
        raise ExpertDeliverableError("Scientific figure manifest is incompatible")
    _validate_feature_contract(payload)
    descriptors = payload.get("data")
    if not isinstance(descriptors, dict) or not descriptors:
        raise ExpertDeliverableError("Scientific figure manifest requires NetCDF variables")
    for panel in payload.get("panels", ()):
        if not isinstance(panel, dict):
            continue
        for layer in panel.get("layers", ()):
            if not isinstance(layer, dict) or layer.get("type") not in {
                "heatmap",
                "field2d",
            }:
                continue
            try:
                x_spec = descriptors[layer["x"]]
                y_spec = descriptors[layer["y"]]
                z_spec = descriptors[layer["z"]]
                expected_shape = [y_spec["shape"][0], x_spec["shape"][0]]
                expected_dims = [y_spec["dims"][0], x_spec["dims"][0]]
            except (KeyError, IndexError, TypeError) as exc:
                raise ExpertDeliverableError(
                    "Scientific figure field2d references invalid NetCDF dimensions"
                ) from exc
            if z_spec.get("shape") != expected_shape or z_spec.get("dims") != expected_dims:
                raise ExpertDeliverableError("Scientific figure field2d must declare z as (y, x)")
    try:
        import numpy as np
        import xarray as xr
    except ImportError as exc:
        raise ExpertDeliverableError(
            "Scientific figure hydration requires the installed Ocean runtime"
        ) from exc
    try:
        source = xr.open_dataset(dataset_path, decode_cf=True, mask_and_scale=True)
    except Exception as exc:
        raise ExpertDeliverableError("Scientific figure NetCDF data is unreadable") from exc
    try:
        resolved: dict[str, list[Any]] = {}
        total = 0
        for field, descriptor in descriptors.items():
            if (
                not isinstance(field, str)
                or not isinstance(descriptor, dict)
                or descriptor.get("variable") != field
            ):
                raise ExpertDeliverableError("Scientific figure variable descriptor is invalid")
            variable = source.get(field)
            if variable is None:
                raise ExpertDeliverableError(
                    f"Scientific figure NetCDF is missing variable {field!r}"
                )
            declared_dims = descriptor.get("dims")
            declared_shape = descriptor.get("shape")
            if list(variable.dims) != declared_dims or list(variable.shape) != declared_shape:
                raise ExpertDeliverableError(
                    f"Scientific figure variable {field!r} does not match its declared dims and shape"
                )
            values = np.asarray(variable.values).reshape(-1)
            total += int(values.size)
            # The renderer receives these arrays through a granted cache file,
            # not through the 1 MiB Protocol V2 event frame.  Keep a real bound
            # for browser memory while allowing publication-scale regular grids
            # (for example a 600 x 660 T-S density field).
            if total > MAX_RENDERED_SCIENTIFIC_VALUES:
                raise ExpertDeliverableError(
                    "Scientific figure exceeds the rendered point allowance"
                )
            if np.issubdtype(values.dtype, np.datetime64):
                resolved[field] = [
                    None if np.isnat(value) else str(np.datetime_as_string(value, unit="ms"))
                    for value in values
                ]
            elif np.issubdtype(values.dtype, np.number):
                resolved[field] = [float(value) if np.isfinite(value) else None for value in values]
            else:
                resolved[field] = [
                    None if value is None else str(value) for value in values.tolist()
                ]
        hydrated = dict(payload)
        hydrated["data"] = resolved
        panels: list[Any] = []
        for panel in hydrated.get("panels", ()):
            if not isinstance(panel, dict):
                panels.append(panel)
                continue
            layers: list[Any] = []
            for layer in panel.get("layers", ()):
                if not isinstance(layer, dict) or layer.get("type") != "contour":
                    layers.append(layer)
                    continue
                path_data = layer.get("path_data")
                if not isinstance(path_data, dict):
                    layers.append(layer)
                    continue
                try:
                    x_values = resolved[path_data["x"]]
                    y_values = resolved[path_data["y"]]
                    starts = resolved[path_data["start"]]
                    counts = resolved[path_data["count"]]
                    levels = resolved[path_data["level"]]
                    labels = resolved[path_data["label"]]
                except (KeyError, TypeError) as exc:
                    raise ExpertDeliverableError("Contour path data is incomplete") from exc
                paths: list[dict[str, Any]] = []
                for start, count, level, label in zip(starts, counts, levels, labels):
                    offset = int(start)
                    length = int(count)
                    path = {
                        "level": float(level),
                        "points": [
                            [float(x), float(y)]
                            for x, y in zip(
                                x_values[offset : offset + length],
                                y_values[offset : offset + length],
                            )
                        ],
                    }
                    if label:
                        path["label"] = str(label)
                    paths.append(path)
                layers.append(
                    {key: value for key, value in layer.items() if key != "path_data"}
                    | {"paths": paths}
                )
            panels.append({**panel, "layers": layers})
        hydrated["panels"] = panels
        return hydrated
    finally:
        source.close()


def hydrate_spatial_manifest(payload: Any, dataset_path: Path) -> dict[str, Any]:
    """Resolve a compact spatial manifest against its regular-grid NetCDF field."""

    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "ocean-interactive-spatial/v2"
    ):
        raise ExpertDeliverableError("Spatial view manifest is incompatible")
    _validate_feature_contract(payload, spatial=True)
    variable_name = payload.get("variable")
    longitude_name = payload.get("longitude_coordinate")
    latitude_name = payload.get("latitude_coordinate")
    if not all(
        isinstance(name, str) and name for name in (variable_name, longitude_name, latitude_name)
    ):
        raise ExpertDeliverableError("Spatial view manifest coordinates are invalid")
    try:
        import numpy as np
        import xarray as xr

        source = xr.open_dataset(dataset_path, decode_cf=True, mask_and_scale=True)
    except Exception as exc:
        raise ExpertDeliverableError("Spatial view NetCDF data is unreadable") from exc
    try:
        if (
            variable_name not in source
            or longitude_name not in source.coords
            or latitude_name not in source.coords
        ):
            raise ExpertDeliverableError("Spatial view NetCDF variables are incomplete")
        field = source[variable_name].transpose(latitude_name, longitude_name)
        values = np.asarray(field.values, dtype=float)
        if list(values.shape) != payload.get("shape"):
            raise ExpertDeliverableError("Spatial view field does not match its declared shape")
        if values.size > MAX_RENDERED_SCIENTIFIC_VALUES:
            raise ExpertDeliverableError("Spatial view exceeds the rendered cell allowance")
        hydrated = dict(payload)
        hydrated.update(
            {
                "schema_version": "ocean-interactive-spatial/v1",
                "longitude": [float(value) for value in source.coords[longitude_name].values],
                "latitude": [float(value) for value in source.coords[latitude_name].values],
                "values": [
                    [float(value) if np.isfinite(value) else None for value in row]
                    for row in values
                ],
            }
        )
        return hydrated
    finally:
        source.close()


def hydrate_ocean_view_netcdf(dataset_path: Path) -> dict[str, Any]:
    """Load the renderer contract and arrays from one self-describing NetCDF."""

    try:
        import xarray as xr

        source = xr.open_dataset(dataset_path, decode_cf=False, mask_and_scale=False)
    except Exception as exc:
        raise ExpertDeliverableError("Interactive view NetCDF is unreadable") from exc
    try:
        if source.attrs.get("ocean_view_schema") != "ocean-view-netcdf/v1":
            raise ExpertDeliverableError("NetCDF does not declare an OceanX view")
        raw = source.attrs.get("ocean_view")
        if not isinstance(raw, str):
            raise ExpertDeliverableError("NetCDF is missing its OceanX view contract")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ExpertDeliverableError("NetCDF OceanX view contract is invalid") from exc
    finally:
        source.close()
    schema = payload.get("schema_version") if isinstance(payload, dict) else None
    if schema == "ocean-scientific-figure/v4":
        return hydrate_scientific_manifest(payload, dataset_path)
    if schema == "ocean-interactive-spatial/v2":
        return hydrate_spatial_manifest(payload, dataset_path)
    raise ExpertDeliverableError("NetCDF OceanX view contract is unsupported")


__all__ = [
    "ExpertDeliverableError",
    "InvalidResultObjectsError",
    "hydrate_ocean_view_netcdf",
    "hydrate_scientific_manifest",
    "hydrate_spatial_manifest",
    "interactive_view_cache",
]
