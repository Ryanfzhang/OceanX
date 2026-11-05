"""A layer's transport, vorticity and circulation on a regular latitude-longitude grid, as the physics skill
defines them, under Vorticity budgets and streamfunctions.

The skill showed these functions as code to copy. A run of 2026-11-05 had them in its instructions and wrote
its own instead, setting each layer's transport to NaN wherever the layer held no water and dividing by the
area left over, which reversed the sign of the middle and deep layers. So the functions are tested here and
every agent's Python imports this file as ``ocean_layers`` (expert_execution.py writes it into the agent's
runtime folder and puts that folder on PYTHONPATH); ``layer_circulations`` takes every layer at once, on one
domain and one area. The file imports nothing but numpy.
"""
from __future__ import annotations

import numpy as np

R = 6.371e6  # Earth's radius, m


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


def layer_circulations(u, v, z, lat, lon, region, layers):
    """The circulation of each of ``layers``, (top, bottom) in m, positive down, np.inf for the sea floor, in
    m3 s-1, and the area of the domain in m2, the denominator of a domain average. u and v are (..., level,
    lat, lon) at the depths ``z``, NaN on land, below the sea floor and where data are missing; ``region``
    (bool, lat x lon) is the domain, open only at real straits. Every layer uses the same cells, those of
    the region where every layer's vorticity is defined, so the same boundary and the same area: a layer
    is zero transport where the sea floor lies above it, not outside the domain."""
    edges = level_edges(z)
    zetas = [vorticity(layer_transport(u, edges, top, bottom), layer_transport(v, edges, top, bottom), lat, lon)
             for top, bottom in layers]
    used = np.asarray(region, dtype=bool) & np.logical_and.reduce([np.isfinite(zeta) for zeta in zetas])
    gammas = [circulation(zeta, lat, lon, used)[0] for zeta in zetas]
    return gammas, circulation(zetas[0], lat, lon, used)[1]


__all__ = ["R", "circulation", "layer_circulations", "layer_transport", "level_edges", "vorticity"]
