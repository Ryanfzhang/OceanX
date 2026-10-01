"""Large interactive arrays travel as granted resources, never protocol frames."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np
import pytest

from oceanx.backend.events import BackendClient
from oceanx.backend.host import OceanBackendHost
from oceanx.expert_deliverables import hydrate_ocean_view_netcdf
from oceanx.scientific_view import ScientificFigure


class _Recorder:
    def __init__(self) -> None:
        self.events = []

    async def send(self, event) -> None:
        self.events.append(event)

    def completed(self, request_id: str):
        return next(
            event for event in reversed(self.events)
            if event.type == "request.completed" and event.request_id == request_id
        )


def test_spatial_fields_require_and_preserve_explicit_valid_mask(
    tmp_path: Path,
) -> None:
    longitude = np.array([120.0, 121.0, 122.0])
    latitude = np.array([32.0, 31.0])
    classes = np.array([[0, 1, 1], [0, 2, 3]])
    valid = np.array([[False, True, True], [False, True, True]])

    unmasked = ScientificFigure(plot_kind="spatial_map", title="Comparison classes")
    with pytest.raises(ValueError, match="spatial maps require valid_mask"):
        unmasked.panel(x=longitude, y=latitude).field2d(
            classes,
            field_kind="categorical",
            category_labels={
                0: "Outside comparison",
                1: "Both",
                2: "Model",
                3: "Satellite",
            },
            variable="comparison_class",
            units="1",
        )

    unmasked_continuous = ScientificFigure(plot_kind="spatial_map", title="Retrieval count")
    with pytest.raises(ValueError, match="spatial maps require valid_mask"):
        unmasked_continuous.panel(x=longitude, y=latitude).field2d(
            classes,
            variable="valid_retrieval_days",
            units="days",
        )

    figure = ScientificFigure(plot_kind="spatial_map", title="Comparison classes")
    figure.panel(x=longitude, y=latitude).field2d(
        classes,
        valid_mask=valid,
        field_kind="categorical",
        category_labels={1: "Both", 2: "Model", 3: "Satellite"},
        variable="comparison_class",
        units="1",
    )
    output = figure.save(tmp_path / "comparison-classes.nc")
    hydrated = hydrate_ocean_view_netcdf(output)

    assert hydrated["values"] == [[None, 1.0, 1.0], [None, 2.0, 3.0]]
    assert [entry["value"] for entry in hydrated["categories"]] == [1.0, 2.0, 3.0]
    assert hydrated["rendering"] == {
        "kind": "categorical",
        "render": "cells",
        "interpolation": "nearest",
        "levels": 14,
    }


@pytest.mark.parametrize(
    ("render", "interpolation", "levels"),
    [
        ("filled_contour", "linear", 7),
        ("filled_contour", "nearest", [-0.5, 0.0, 0.5]),
        ("smooth", "linear", 14),
        ("cells", "nearest", 14),
    ],
)
def test_spatial_map_preserves_expert_rendering_contract(
    tmp_path: Path, render: str, interpolation: str, levels: int | list[float]
) -> None:
    longitude = np.array([-96.0, -95.0, -94.0])
    latitude = np.array([22.0, 21.0])
    values = np.array([[-0.5, 0.0, 0.5], [-0.25, 0.25, 0.75]])
    valid = np.ones_like(values, dtype=bool)
    figure = ScientificFigure(plot_kind="spatial_map", title="Temperature anomaly")
    figure.panel(x=longitude, y=latitude).field2d(
        values,
        valid_mask=valid,
        variable="temperature_anomaly",
        units="degC",
        render=render,
        interpolation=interpolation,
        levels=levels,
    )

    hydrated = hydrate_ocean_view_netcdf(
        figure.save(tmp_path / f"{render}-{interpolation}.nc")
    )

    assert hydrated["rendering"] == {
        "kind": "continuous",
        "render": render,
        "interpolation": interpolation,
        "levels": levels,
    }


@pytest.mark.asyncio
async def test_large_interactive_view_is_cached_behind_a_small_resource_grant(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    host = OceanBackendHost(workspace / ".oceanmind", write_frame=lambda _frame: None)
    recorder = _Recorder()
    client = BackendClient(
        transport="stdio", expected_client_kind="desktop", sender=recorder.send
    )
    try:
        await host.event_bus.register(client)
        await host.router.handle_payload(
            client,
            {
                "protocol_version": 2,
                "request_id": "req_transport_handshake",
                "type": "system.handshake",
                "payload": {
                    "client_kind": "desktop",
                    "client_version": "test",
                    "supported_protocol_versions": [2],
                },
            },
        )
        context = {
            "client_id": str(client.client_id),
            "session_id": str(client.session_id),
            "workspace_id": "ws_transport",
        }
        await host.router.handle_payload(
            client,
            {
                "protocol_version": 2,
                "request_id": "req_transport_workspace",
                "type": "workspace.open",
                "payload": {"path": str(workspace)},
                "context": context,
                "expected_workspace_revision": 0,
            },
        )
        task = host.store.create_research_task(
            workspace_id="ws_transport", title="Large field transport"
        )
        x = np.linspace(-98.0, -77.0, 400)
        y = np.linspace(0.0, 1_000.0, 400)
        field = np.add.outer(y / 1_000.0, x / 100.0)
        figure = ScientificFigure(plot_kind="section", title="Large section")
        figure.panel(x=x, y=y, y_reverse=True).field2d(field)
        view_path = figure.save(tmp_path / "large-section.nc")
        record = host.task_results.put(
            workspace_id="ws_transport",
            task_id=task.task_id,
            kind="interactive_view",
            title="Large section",
            content={
                "output_path": "large-section.nc",
                "data_file": "data.nc",
                "dataset_file": "data.nc",
                "render_status": "interactive",
                "view_kind": "section",
            },
            files={"data.nc": view_path},
        )
        request_id = "req_transport_view"
        await host.router.handle_payload(
            client,
            {
                "protocol_version": 2,
                "request_id": request_id,
                "type": "task_result.interactive_view.get",
                "payload": {"result_ref": record.ref.model_dump(mode="json")},
                "context": {**context, "task_id": task.task_id},
            },
        )

        result = recorder.completed(request_id).payload.result
        assert "data" not in result
        assert result["resource_token"].startswith("res_")
        assert result["mime_type"] == "application/json"
        assert len(json.dumps(result)) < 4_096
        resource_path = Path(unquote(urlparse(result["resource_uri"]).path))
        assert resource_path.is_file()
        assert workspace / ".oceanmind" / "cache" in resource_path.parents
        assert result["size_bytes"] == resource_path.stat().st_size
        assert result["size_bytes"] > 1_048_576
        hydrated = json.loads(resource_path.read_text(encoding="utf-8"))
        z_field = hydrated["panels"][0]["layers"][0]["z"]
        assert len(hydrated["data"][z_field]) == 160_000
    finally:
        await host.close()
