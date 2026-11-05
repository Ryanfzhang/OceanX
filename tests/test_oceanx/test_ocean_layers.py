"""Every agent's Python imports ocean_layers (src/oceanx/ocean_layers.py), and the physics skill, under
Vorticity budgets and streamfunctions, has it compute a layer's circulation with them. A run of 2026-11-03
zero-filled land before differencing and summed only where a layer held water; a run of 2026-11-05 had the
functions in its instructions as code and wrote its own, with a mask for each layer, which reversed the sign
of the middle and deep layers. The functions are checked here, with the line integral that checks them by
Stokes' theorem; the skill's call is run as written, and an agent's Python imports the module."""
import re
import sys
from pathlib import Path

import numpy as np
import pytest

from oceanx import ocean_layers
from oceanx.native_skills import _sections
from oceanx.ocean_layers import (
    R,
    circulation,
    layer_circulations,
    layer_transport,
    level_edges,
    vorticity,
)
from oceanx.skills import load_ocean_skill

LAT = np.linspace(2.0, 24.0, 45)
LON = np.linspace(104.0, 122.0, 37)
LAYERS = [(0.0, 750.0), (750.0, 1500.0), (1500.0, np.inf)]


def _basin():
    """A basin with coasts, two islands, a deep middle and a cut through open sea, and its land."""
    rng = np.random.default_rng(0)
    lam, phi = np.meshgrid(np.deg2rad(LON), np.deg2rad(LAT))
    z = np.array([5.0, 30, 100, 300, 600, 900, 1300, 1700, 2200, 3000, 4000])
    floor = 100 + 3900 * np.exp(-((lam - lam.mean()) ** 2 + (phi - phi.mean()) ** 2) / (2 * 0.1**2))
    land = np.zeros(lam.shape, bool)
    land[:, :4] = land[-5:, 22:] = land[9:12, 26:29] = True
    land[20, 17] = True  # an island of one cell
    u, v = rng.normal(size=(2, len(z), *lam.shape)) * 0.1
    for field in (u, v):
        field[z[:, None, None] > floor] = np.nan
        field[:, land] = np.nan
    region = np.ones(lam.shape, bool)
    region[:, 33:] = False
    return {"z": z, "u": u, "v": v, "lat": LAT, "lon": LON, "region": region, "floor": floor}, land


def _boundary_circulation(U, V, lat, lon, used, R):
    """The line integral of (U, V), counterclockwise along the edge of the cells used, each face taking the
    mean of the two cells beside it; by Stokes' theorem it equals the circulation to rounding."""
    phi, lam = np.deg2rad(lat), np.deg2rad(lon)
    inside, Uc = np.asarray(used, dtype=float), U * np.cos(phi)[:, None]
    east = inside[..., :, :-1] - inside[..., :, 1:]  # 1 on the edge where the used cell has the lower index
    north = inside[..., 1:, :] - inside[..., :-1, :]
    dy = R * np.abs(np.gradient(phi))[:, None] * np.sign(lam[-1] - lam[0])
    dx = R * np.abs(np.gradient(lam)) * np.sign(phi[-1] - phi[0])
    along_x = np.where(east != 0, east * (V[..., :, :-1] + V[..., :, 1:]) / 2 * dy, 0.0)
    along_y = np.where(north != 0, north * (Uc[..., :-1, :] + Uc[..., 1:, :]) / 2 * dx, 0.0)
    return along_x.sum(axis=(-2, -1)) + along_y.sum(axis=(-2, -1))


def _layer(inputs, top, bottom):
    edges = level_edges(inputs["z"])
    U, V = layer_transport(inputs["u"], edges, top, bottom), layer_transport(inputs["v"], edges, top, bottom)
    return U, V, vorticity(U, V, LAT, LON)


def test_every_layer_uses_the_same_cells_and_area_and_the_line_integral_agrees():
    inputs, land = _basin()
    gammas, area = layer_circulations(inputs["u"], inputs["v"], inputs["z"], LAT, LON, inputs["region"], LAYERS)
    shared = None
    for (top, bottom), gamma in zip(LAYERS, gammas, strict=True):
        U, V, zeta = _layer(inputs, top, bottom)
        used = inputs["region"] & np.isfinite(zeta)
        shared = used if shared is None else shared
        assert (used == shared).all() and circulation(zeta, LAT, LON, used)[1] == area
        assert np.isfinite(gamma) and gamma != 0
        assert np.isclose(_boundary_circulation(U, V, LAT, LON, used, R), gamma, rtol=1e-9)
    # Absent water is zero transport, so only land and missing data decide the cells.
    U, _, zeta = _layer(inputs, 1500.0, np.inf)
    shallow = ~land & (U == 0)
    assert shallow.sum() > 100 and np.isnan(U[land]).all()
    # The cells beside land have no centred difference and drop out, the one-cell island's neighbours too.
    beside = np.zeros_like(land)
    beside[1:] |= land[:-1]
    beside[:-1] |= land[1:]
    beside[:, 1:] |= land[:, :-1]
    beside[:, :-1] |= land[:, 1:]
    assert np.isnan(zeta[land | beside]).all()
    assert not shared[[20, 19, 21, 20, 20], [17, 17, 17, 16, 18]].any()


def test_a_mask_for_each_layer_measures_another_circulation():
    # What the run of 2026-11-05 computed: the deep layer's transport NaN wherever the sea floor lies above
    # it, then its circulation over the cells left, divided by their area. Its edge runs along the slope,
    # so both the circulation and the area differ from those on the basin's one domain.
    inputs, _ = _basin()
    gammas, area = layer_circulations(inputs["u"], inputs["v"], inputs["z"], LAT, LON, inputs["region"], LAYERS)
    U, V, _ = _layer(inputs, 1500.0, np.inf)
    present = inputs["floor"] > 1500.0
    own = vorticity(np.where(present, U, np.nan), np.where(present, V, np.nan), LAT, LON)
    gamma, own_area = circulation(own, LAT, LON, inputs["region"] & np.isfinite(own))
    assert own_area < 0.8 * area
    assert not np.isclose(gamma / own_area, gammas[2] / area, rtol=0.1)


def test_the_operator_is_exact_on_linear_fields_and_a_cyclonic_gyre_is_positive():
    lam, phi = np.meshgrid(np.deg2rad(LON), np.deg2rad(LAT))
    inner = (slice(1, -1), slice(1, -1))
    zeta = vorticity(np.zeros_like(lam), 3.0 * lam, LAT, LON)
    assert np.allclose(zeta[inner], 3.0 / (R * np.cos(phi[inner])), rtol=1e-12)
    zeta = vorticity(5.0 * phi / np.cos(phi), np.zeros_like(lam), LAT, LON)
    assert np.allclose(zeta[inner], -5.0 / (R * np.cos(phi[inner])), rtol=1e-12)
    x, y = (lam - lam.mean()) * R * np.cos(phi.mean()), (phi - phi.mean()) * R
    psi = -1e8 * np.exp(-(x**2 + y**2) / (2 * 3e5**2))  # counterclockwise round its minimum
    U = -np.gradient(psi, axis=0) / np.gradient(y, axis=0)
    V = np.gradient(psi, axis=1) / np.gradient(x, axis=1)
    zeta = vorticity(U, V, LAT, LON)
    gamma, _ = circulation(zeta, LAT, LON, np.isfinite(zeta))
    assert gamma > 0


def test_the_grid_may_run_either_way_and_carry_a_time_axis():
    inputs, _ = _basin()
    U, V, zeta = _layer(inputs, 0.0, 750.0)
    region = inputs["region"]
    gamma, area = circulation(zeta, LAT, LON, region & np.isfinite(zeta))
    for rows, cols in ((slice(None, None, -1), slice(None)), (slice(None), slice(None, None, -1)),
                       (slice(None, None, -1), slice(None, None, -1))):
        lat, lon = LAT[rows], LON[cols]
        flipped = vorticity(U[rows, cols], V[rows, cols], lat, lon)
        used = region[rows, cols] & np.isfinite(flipped)
        assert np.allclose(circulation(flipped, lat, lon, used), (gamma, area), rtol=1e-12)
        assert np.isclose(_boundary_circulation(U[rows, cols], V[rows, cols], lat, lon, used, R), gamma, rtol=1e-9)
    u2, v2 = np.stack([inputs["u"], 2 * inputs["u"]]), np.stack([inputs["v"], 2 * inputs["v"]])
    gammas, area2 = layer_circulations(u2, v2, inputs["z"], LAT, LON, region, LAYERS[:1])
    assert np.allclose(gammas[0], [gamma, 2 * gamma], rtol=1e-12) and np.allclose(area2, area)


def test_a_level_enters_a_layer_with_its_part_inside_it():
    assert np.allclose(level_edges([5.0, 15.0, 30.0]), [0.0, 10.0, 22.5, 37.5])
    z_edges = np.array([0.0, 10, 20, 40, 60])
    u = np.ones((4, 1, 3))
    u[2:, 0, 1] = np.nan  # sea floor at 20 m
    u[:, 0, 2] = np.nan   # land
    assert np.allclose(layer_transport(u, z_edges, 15.0, 50.0)[0, :2], [35.0, 5.0])
    assert layer_transport(u, z_edges, 25.0, np.inf)[0, 1] == 0.0  # water, none in the layer
    assert np.isnan(layer_transport(u, z_edges, 0.0, np.inf)[0, 2])


def test_the_skill_calls_the_module_and_shows_no_code_of_its_own_to_copy(monkeypatch):
    section = _sections(load_ocean_skill("ocean-physical-consistency-review")[0])[
        "Vorticity budgets and streamfunctions"]
    (code,) = re.findall(r"```python\n(.*?)```", section, re.DOTALL)
    assert "def " not in code
    inputs, _ = _basin()
    monkeypatch.setitem(sys.modules, "ocean_layers", ocean_layers)  # as an agent's Python imports it
    namespace = {**inputs, "layers": LAYERS}
    exec(code, namespace)  # noqa: S102 - the skill's own call
    gammas, area = layer_circulations(inputs["u"], inputs["v"], inputs["z"], LAT, LON, inputs["region"], LAYERS)
    assert np.allclose(namespace["gammas"], gammas) and namespace["area"] == area


@pytest.mark.asyncio
async def test_an_agents_python_imports_the_module(tmp_path: Path, monkeypatch):
    """Through the real sandbox, the kernel and a script a shell command starts both import it."""
    from oceanx.backend.host import OceanBackendHost
    from oceanx.sandbox import get_sandbox_execution_capabilities
    from tests.test_oceanx.test_research_library_router import _open_project

    capabilities = get_sandbox_execution_capabilities()
    if not capabilities.available:
        pytest.skip(capabilities.reason or "sandbox backend is unavailable")
    monkeypatch.setenv("OCEAN_SANDBOX_PYTHON", sys.executable)
    host = OceanBackendHost(tmp_path / "state", write_frame=lambda _frame: None)
    try:
        client, recorder, context = await _open_project(host, tmp_path, "ws_layers")
        await host.router.handle_payload(client, {
            "protocol_version": 2, "request_id": "req_task", "type": "task.create",
            "payload": {"title": "layers"}, "context": context})
        task_id = recorder.result("req_task")["task"]["task_id"]
        run = {"workspace_id": "ws_layers", "task_id": task_id, "agent_thread_id": "single-agent-x",
               "server_run_id": "run"}
        service = host.expert_code_execution
        code = "import ocean_layers\nprint(ocean_layers.layer_circulations.__name__, ocean_layers.__file__)\n"
        kernel = await service.run_python(**run, purpose="Import", code=code)
        assert kernel.state == "succeeded", kernel.as_payload()
        assert "layer_circulations" in kernel.stdout and "ocean-lib" in kernel.stdout
        (Path(kernel.work_root) / "scratch" / "layers.py").write_text(code, encoding="utf-8")
        shell = await service.run_shell(**run, command="python layers.py")
        assert shell.state == "succeeded", shell.as_payload()
        assert "layer_circulations" in shell.stdout
    finally:
        await host.close()
