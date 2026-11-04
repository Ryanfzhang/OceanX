"""The physics skill shows a layer's circulation as code, under Vorticity budgets and streamfunctions, and
agents copy it, so it is run here as written. A run of 2026-11-03 zero-filled land before differencing and
summed only where a layer held water, with the section's prose in its prompt. The line integral that checks
the example by Stokes' theorem lives here: the run of 2026-11-04 copied it from the skill and, weighted by f,
took it for a flux term, which needs the normal component."""
import re

import numpy as np

from oceanx.native_skills import _sections
from oceanx.skills import load_ocean_skill

LAT = np.linspace(2.0, 24.0, 45)
LON = np.linspace(104.0, 122.0, 37)


def _basin(top, bottom):
    """Inputs of the example: a basin with coasts, two islands, a deep middle and a cut through open sea."""
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
    return {"z": z, "u": u, "v": v, "top": top, "bottom": bottom, "lat": LAT, "lon": LON, "region": region}, land


def _boundary_circulation(U, V, lat, lon, used, R):
    """The line integral of (U, V), counterclockwise along the edge of the cells used, each face taking the
    mean of the two cells beside it; by Stokes' theorem it equals the example's circulation to rounding."""
    phi, lam = np.deg2rad(lat), np.deg2rad(lon)
    inside, Uc = np.asarray(used, dtype=float), U * np.cos(phi)[:, None]
    east = inside[..., :, :-1] - inside[..., :, 1:]  # 1 on the edge where the used cell has the lower index
    north = inside[..., 1:, :] - inside[..., :-1, :]
    dy = R * np.abs(np.gradient(phi))[:, None] * np.sign(lam[-1] - lam[0])
    dx = R * np.abs(np.gradient(lam)) * np.sign(phi[-1] - phi[0])
    along_x = np.where(east != 0, east * (V[..., :, :-1] + V[..., :, 1:]) / 2 * dy, 0.0)
    along_y = np.where(north != 0, north * (Uc[..., :-1, :] + Uc[..., 1:, :]) / 2 * dx, 0.0)
    return along_x.sum(axis=(-2, -1)) + along_y.sum(axis=(-2, -1))


def _example(inputs):
    """The example run on ``inputs``; what it defines and computes."""
    section = _sections(load_ocean_skill("ocean-physical-consistency-review")[0])[
        "Vorticity budgets and streamfunctions"]
    (code,) = re.findall(r"```python\n(.*?)```", section, re.DOTALL)
    namespace = dict(inputs)
    exec(code, namespace)  # noqa: S102 - the skill's own example
    return namespace


def test_the_example_runs_and_every_layer_uses_the_same_cells():
    (upper, land), (deep, _) = _basin(0.0, 750.0), _basin(1500.0, np.inf)
    upper, deep = _example(upper), _example(deep)
    for layer in (upper, deep):
        check = _boundary_circulation(layer["U"], layer["V"], LAT, LON, layer["used"], layer["R"])
        assert np.isfinite(layer["gamma"]) and layer["gamma"] != 0
        assert np.isclose(check, layer["gamma"], rtol=1e-9)
    # Absent water is zero transport, so only land and missing data decide the cells, and both layers
    # share the domain, its boundary and its area.
    assert (upper["used"] == deep["used"]).all() and upper["area"] == deep["area"]
    shallow = ~land & (deep["layer_transport"](deep["u"], deep["z_edges"], 1500.0, np.inf) == 0)
    assert shallow.sum() > 100 and np.isnan(deep["U"][land]).all()
    # The cells beside land have no centred difference and drop out, the one-cell island's neighbours too.
    beside = np.zeros_like(land)
    beside[1:] |= land[:-1]
    beside[:-1] |= land[1:]
    beside[:, 1:] |= land[:, :-1]
    beside[:, :-1] |= land[:, 1:]
    assert np.isnan(deep["zeta"][land | beside]).all()
    assert not deep["used"][[20, 19, 21, 20, 20], [17, 17, 17, 16, 18]].any()


def test_the_operator_is_exact_on_linear_fields_and_a_cyclonic_gyre_is_positive():
    example = _example(_basin(0.0, 750.0)[0])
    vorticity, circulation, R = example["vorticity"], example["circulation"], example["R"]
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
    example = _example(_basin(0.0, 750.0)[0])
    vorticity, circulation = example["vorticity"], example["circulation"]
    U, V, region, R = example["U"], example["V"], example["region"], example["R"]
    gamma, area = example["gamma"], example["area"]
    for rows, cols in ((slice(None, None, -1), slice(None)), (slice(None), slice(None, None, -1)),
                       (slice(None, None, -1), slice(None, None, -1))):
        lat, lon = LAT[rows], LON[cols]
        zeta = vorticity(U[rows, cols], V[rows, cols], lat, lon)
        used = region[rows, cols] & np.isfinite(zeta)
        assert np.allclose(circulation(zeta, lat, lon, used), (gamma, area), rtol=1e-12)
        line = _boundary_circulation(U[rows, cols], V[rows, cols], lat, lon, used, R)
        assert np.isclose(line, gamma, rtol=1e-9)
    U2, V2 = np.stack([U, 2 * U]), np.stack([V, 2 * V])
    zeta = vorticity(U2, V2, LAT, LON)
    used = region & np.isfinite(zeta)
    assert np.allclose(circulation(zeta, LAT, LON, used)[0], [gamma, 2 * gamma], rtol=1e-12)
    assert np.allclose(_boundary_circulation(U2, V2, LAT, LON, used, R), [gamma, 2 * gamma], rtol=1e-9)
    layer = example["layer_transport"](np.stack([example["u"], example["u"]]), example["z_edges"], 0.0, 750.0)
    assert np.array_equal(layer[1], U, equal_nan=True)


def test_a_level_enters_a_layer_with_its_part_inside_it():
    layer_transport = _example(_basin(0.0, 750.0)[0])["layer_transport"]
    z_edges = np.array([0.0, 10, 20, 40, 60])
    u = np.ones((4, 1, 3))
    u[2:, 0, 1] = np.nan  # sea floor at 20 m
    u[:, 0, 2] = np.nan   # land
    assert np.allclose(layer_transport(u, z_edges, 15.0, 50.0)[0, :2], [35.0, 5.0])
    assert layer_transport(u, z_edges, 25.0, np.inf)[0, 1] == 0.0  # water, none in the layer
    assert np.isnan(layer_transport(u, z_edges, 0.0, np.inf)[0, 2])
