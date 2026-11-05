"""A layer's transport, vorticity and circulation on a regular latitude-longitude grid, as the physics skill
defines them, under Vorticity budgets and streamfunctions, and the open edges of a domain.

The skill showed these functions as code to copy. A run of 2026-11-05 had them in its instructions and wrote
its own instead, setting each layer's transport to NaN wherever the layer held no water and dividing by the
area left over, which reversed the sign of the middle and deep layers. So the functions are tested here and
every agent's Python imports this file as ``ocean_layers`` (expert_execution.py writes it into the agent's
runtime folder and puts that folder on PYTHONPATH); ``layer_circulations`` takes every layer at once, on one
domain and one area. The next run cut its domain from a latitude-longitude box whose corner lay in the open
sea beside a strait: most of the water it counted through the strait left again across the box's other
edge. ``open_edges`` lists a domain's open edges with the transport through each and the corners where the
edge turns in open water, and ``layer_circulations`` warns of such corners. The file imports nothing but
numpy.
"""
from __future__ import annotations

import warnings

import numpy as np

R = 6.371e6  # Earth's radius, m
CORNER_FACES = 3  # open faces in a row on both sides of a corner; the steps of a diagonal cut are shorter
CORNER_NOTE = ("ocean_layers: the domain's edge turns a corner in open water at {places} (latitude, longitude); "
               "there it cuts the sea instead of closing on a coast, and water can cross the domain's corner "
               "rather than enter it. Unless the paper defines its domain so, close it at the straits; "
               "open_edges lists each open edge with the transport through it.")


def level_edges(z):
    """The edges of the cells of levels at depths ``z`` (m, positive down): the surface, the midpoints
    between levels and, below the last, half its spacing to the level above."""
    z = np.asarray(z, dtype=float)
    return np.r_[0.0, (z[1:] + z[:-1]) / 2, z[-1] + (z[-1] - z[-2]) / 2]


def layer_transport(u, z_edges, top, bottom):
    """Integral of u (..., level, lat, lon) from depth top to bottom (m, positive down; np.inf for the sea
    floor), in m2 s-1 for a velocity. z_edges (level + 1) bound the levels' cells: for depths given as points,
    the midpoints between them (level_edges). Zero where the column holds water but none in the layer; NaN
    where it holds no valid data, on land or where data are missing."""
    dz = np.clip(np.minimum(z_edges[1:], bottom) - np.maximum(z_edges[:-1], top), 0, None)[:, None, None]
    total = np.where(np.isfinite(u), u * dz, 0.0).sum(axis=-3)
    return np.where(np.isfinite(u).any(axis=-3), total, np.nan)


def vorticity(U, V, lat, lon):
    """Relative vorticity of (U, V) (..., lat, lon) by centred differences on the sphere. A cell gets NaN
    when it or one of its four neighbours is NaN, so the cells beside land or missing data drop out."""
    phi, lam = np.deg2rad(lat), np.deg2rad(lon)
    Uc = U * np.cos(phi)[:, None]
    zeta = np.full(np.shape(U), np.nan)
    zeta[..., 1:-1, 1:-1] = ((V[..., 1:-1, 2:] - V[..., 1:-1, :-2]) / (lam[2:] - lam[:-2])
                             - (Uc[..., 2:, 1:-1] - Uc[..., :-2, 1:-1]) / (phi[2:] - phi[:-2])[:, None]
                             ) / (R * np.cos(phi[1:-1])[:, None])
    return np.where(np.isfinite(U) & np.isfinite(V), zeta, np.nan)


def circulation(zeta, lat, lon, used):
    """Area integral of zeta over the cells used (bool, ..., lat, lon), in m3 s-1 for transports, and the
    area of those cells in m2, the denominator of a domain average."""
    phi, lam = np.deg2rad(lat), np.deg2rad(lon)
    area = R**2 * np.cos(phi)[:, None] * np.abs(np.gradient(phi))[:, None] * np.abs(np.gradient(lam))
    return np.where(used, zeta * area, 0.0).sum(axis=(-2, -1)), np.where(used, area, 0.0).sum(axis=(-2, -1))


def _cell_edges(values):
    middle = (values[1:] + values[:-1]) / 2
    return np.r_[2 * values[0] - middle[0], middle, 2 * values[-1] - middle[-1]]


def _runs(indices):
    """Consecutive runs in sorted indices, as (first, last) pairs."""
    breaks = np.flatnonzero(np.diff(indices) != 1)
    return list(zip(indices[np.r_[0, breaks + 1]], indices[np.r_[breaks, len(indices) - 1]], strict=True))


def open_edges(region, ocean, lat, lon, U=None, V=None):
    """The edges of the domain ``region`` (bool, lat x lon) open to the sea: straight runs of faces where an
    ocean cell of the region borders an ocean cell outside it, or the end of the arrays; ``ocean`` (bool,
    lat x lon) marks the cells holding water. Each edge is a dict with its side (east, west, north or south),
    the longitude or latitude of its faces (at), the first and last centre of its cells along it (start,
    end), its number of faces and, given transports U, V (..., lat, lon; eastward and northward, m2 s-1),
    the transport out through it in m3 s-1, each face taking the mean of the cells on its two sides. Also
    the corners, (latitude, longitude), where two runs of at least CORNER_FACES faces meet in open water:
    there the domain's edge cuts the sea instead of closing on a coast. A domain closed at its straits has
    none, and its full-depth transports out add up to about zero."""
    region, ocean = np.asarray(region, dtype=bool), np.asarray(ocean, dtype=bool)
    lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
    rows = slice(None, None, 1 if lat[-1] > lat[0] else -1)  # work south to north and west to east
    cols = slice(None, None, 1 if lon[-1] > lon[0] else -1)
    region, ocean, lat, lon = region[rows, cols], ocean[rows, cols], lat[rows], lon[cols]
    if U is not None:
        U, V = np.asarray(U, dtype=float)[..., rows, cols], np.asarray(V, dtype=float)[..., rows, cols]
    inside, ny, nx = region & ocean, *region.shape
    beyond = np.pad(ocean & ~region, 1, constant_values=True)  # past the end of the arrays counts as open
    phi, lat_edges, lon_edges = np.deg2rad(lat), _cell_edges(lat), _cell_edges(lon)
    dy, dlam = R * np.abs(np.gradient(phi)), np.abs(np.gradient(np.deg2rad(lon)))
    edges, ends = [], {}
    for side, (dj, di) in {"east": (0, 1), "west": (0, -1), "north": (1, 0), "south": (-1, 0)}.items():
        facing = inside & beyond[1 + dj:1 + dj + ny, 1 + di:1 + di + nx]
        vertical = di != 0
        for line in range(nx if vertical else ny):
            cells = np.flatnonzero(facing[:, line] if vertical else facing[line])
            for first, last in _runs(cells) if cells.size else ():
                along = np.arange(first, last + 1)
                j, i = (along, np.full_like(along, line)) if vertical else (np.full_like(along, line), along)
                at = lon_edges[line + (di > 0)] if vertical else lat_edges[line + (dj > 0)]
                centres = lat if vertical else lon
                edge = {"side": side, "at": float(at), "start": float(centres[first]),
                        "end": float(centres[last]), "faces": len(along)}
                if U is not None:
                    field, step = (U, (0, di)) if vertical else (V, (dj, 0))
                    j2, i2 = j + step[0], i + step[1]
                    there = (j2 >= 0) & (j2 < ny) & (i2 >= 0) & (i2 < nx)
                    across = field[..., np.clip(j2, 0, ny - 1), np.clip(i2, 0, nx - 1)]
                    face = (field[..., j, i] + np.where(there, across, field[..., j, i])) / 2
                    if vertical:
                        length = dy[j]
                    else:
                        length = R * np.cos((phi[j] + phi[np.clip(j2, 0, ny - 1)]) / 2) * dlam[i]
                    edge["transport"] = (np.sign(di + dj) * face * length).sum(axis=-1)
                edges.append(edge)
                # the run's two ends on the grid of cell corners, as (row edge, column edge)
                if vertical:
                    points = ((first, line + (di > 0)), (last + 1, line + (di > 0)))
                else:
                    points = ((line + (dj > 0), first), (line + (dj > 0), last + 1))
                for point in points:
                    ends.setdefault(point, []).append((vertical, len(along)))
    corners = []
    for (J, I), runs in sorted(ends.items()):
        long_runs = {vertical for vertical, faces in runs if faces >= CORNER_FACES}
        if long_runs == {True, False} and 1 <= J < ny and 1 <= I < nx and ocean[J - 1:J + 1, I - 1:I + 1].all():
            corners.append((float(lat_edges[J]), float(lon_edges[I])))
    return edges, corners


def layer_circulations(u, v, z, lat, lon, region, layers):
    """The circulation of each of ``layers``, (top, bottom) in m, positive down, np.inf for the sea floor, in
    m3 s-1, and the area of the domain in m2, the denominator of a domain average. u and v are (..., level,
    lat, lon) at the depths ``z``, NaN on land, below the sea floor and where data are missing; ``region``
    (bool, lat x lon) is the domain, open only at real straits. Every layer uses the same cells, those of
    the region where every layer's vorticity is defined, so the same boundary and the same area: a layer
    is zero transport where the sea floor lies above it, not outside the domain. A corner of the domain's
    edge in open water is reported as a warning (open_edges)."""
    edges = level_edges(z)
    transports = [(layer_transport(u, edges, top, bottom), layer_transport(v, edges, top, bottom))
                  for top, bottom in layers]
    zetas = [vorticity(U, V, lat, lon) for U, V in transports]
    region = np.asarray(region, dtype=bool)
    ocean = np.isfinite(transports[0][0]).reshape(-1, *region.shape).any(axis=0)
    corners = open_edges(region, ocean, lat, lon)[1]
    if corners:
        places = ", ".join(f"({corner_lat:.2f}, {corner_lon:.2f})" for corner_lat, corner_lon in corners)
        warnings.warn(CORNER_NOTE.format(places=places), stacklevel=2)
    used = region & np.logical_and.reduce([np.isfinite(zeta) for zeta in zetas])
    gammas = [circulation(zeta, lat, lon, used)[0] for zeta in zetas]
    return gammas, circulation(zetas[0], lat, lon, used)[1]


__all__ = ["CORNER_FACES", "R", "circulation", "layer_circulations", "layer_transport", "level_edges",
           "open_edges", "vorticity"]
