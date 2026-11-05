"""The Natural Earth files cartopy draws coastlines, land, lakes, rivers and borders from.

Agents' code runs in a sandbox that may not reach the internet, so cartopy cannot fetch these files the
first time a map is drawn. They are downloaded once when OceanX is installed, into ``share/cartopy`` of the
Python environment that runs the agents' code (a folder the sandbox may read), and that code finds them
through ``CARTOPY_DATA_DIR``, which cartopy reads before it tries the network.

    python -m oceanx.natural_earth [--prefix <environment that runs the agents' code>]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DATA_DIR_ENV = "CARTOPY_DATA_DIR"
# (category, name) of every feature the map guidance draws or an agent commonly adds, at each scale.
FEATURES = (("physical", "coastline"), ("physical", "land"), ("physical", "ocean"), ("physical", "lakes"),
            ("physical", "rivers_lake_centerlines"), ("cultural", "admin_0_boundary_lines_land"))
SCALES = ("110m", "50m", "10m")


def data_root(prefix: Path | str | None = None) -> Path:
    """Where the files live: share/cartopy of the environment at ``prefix`` (this one by default)."""
    return Path(prefix or sys.prefix) / "share" / "cartopy"


def shapefile(root: Path, scale: str, category: str, name: str) -> Path:
    """The path cartopy looks for under CARTOPY_DATA_DIR."""
    return root / "shapefiles" / "natural_earth" / category / f"ne_{scale}_{name}.shp"


def missing(root: Path) -> list[tuple[str, str, str]]:
    return [(scale, category, name) for category, name in FEATURES for scale in SCALES
            if not shapefile(root, scale, category, name).is_file()]


def download(root: Path) -> list[Path]:
    """Fetch every missing file into ``root`` with cartopy's own downloader; return the files fetched."""
    import cartopy
    from cartopy.io import shapereader

    cartopy.config["data_dir"] = root
    return [Path(shapereader.natural_earth(resolution=scale, category=category, name=name))
            for scale, category, name in missing(root)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m oceanx.natural_earth",
                                     description="Download the Natural Earth files cartopy draws maps from.")
    parser.add_argument("--prefix", help="the Python environment that runs the agents' code (default: this one)")
    root = data_root(parser.parse_args(argv).prefix)
    fetched = download(root)
    left = missing(root)
    print(f"Natural Earth in {root}: {len(fetched)} downloaded, "
          f"{len(FEATURES) * len(SCALES) - len(left)} of {len(FEATURES) * len(SCALES)} present")
    for scale, category, name in left:
        print(f"missing: {scale} {category} {name}", file=sys.stderr)
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main())
