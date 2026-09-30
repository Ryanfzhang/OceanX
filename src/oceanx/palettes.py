"""Shared scientific palette semantics for saved results and static previews."""

from __future__ import annotations

import re
from collections.abc import Sequence

OCEAN_TEAL = (
    "#F4F0E5", "#C6DCD5", "#83B9B2", "#47888E", "#27536D",
)
BLUE_RED = (
    "#104E8B", "#376B9E", "#5F89B1", "#AFC3D8", "#C5E9E3",
    "#D7E1EB", "#F2DADA", "#E5B5B5", "#D89090", "#B22222",
)
GROUPED = BLUE_RED
CATEGORICAL = (
    "#154F70", "#BD6840", "#4A8E92", "#7775A7",
    "#9D7B36", "#5D7E68", "#A64F68", "#52719B",
)

PALETTES: dict[str, tuple[str, ...]] = {
    "ocean_teal": OCEAN_TEAL,
    "blue_red": BLUE_RED,
    "grouped": GROUPED,
    "categorical": CATEGORICAL,
    "depth": ("#F3EDC9", "#CDDDC8", "#93C4BD", "#5A9EA5", "#477992", "#455777", "#66516D"),
    "thermal": ("#243C62", "#47759A", "#82AFB5", "#E8E2CD", "#DA9A70", "#A94B42"),
    "chlorophyll": ("#F1EDC8", "#C8DDA7", "#83B984", "#4B8C6C", "#285C56"),
    "viridis": ("#440154", "#414487", "#2A788E", "#22A884", "#7AD151", "#FDE725"),
    "cividis": ("#00224E", "#24476D", "#576D72", "#8D8A66", "#C3AA4B", "#FEE838"),
    "magma": ("#000004", "#2C115F", "#721F81", "#B73779", "#F1605D", "#FEB078", "#FCFDBF"),
    "plasma": ("#0D0887", "#6A00A8", "#B12A90", "#E16462", "#FCA636", "#F0F921"),
    "blues": ("#F7FBFF", "#DEEBF7", "#9ECAE1", "#4292C6", "#2171B5", "#08306B"),
}

ALIASES = {
    "default": "ocean_teal",
    "sequential": "ocean_teal",
    "haline": "ocean_teal",
    "diverging": "blue_red",
    "balance": "blue_red",
    "rdbu_r": "blue_red",
    "ocean-teal": "ocean_teal",
    "blue-red": "blue_red",
}

DEFAULT_SEQUENTIAL_PALETTE = "ocean_teal"
DEFAULT_DIVERGING_PALETTE = "blue_red"
DEFAULT_GROUPED_PALETTE = "grouped"


def canonical_palette_name(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_")
    return ALIASES.get(normalized, normalized)


def normalize_palette(value: str | Sequence[str]) -> str | list[str]:
    """Return a renderer-safe named palette or explicit continuous colour stops."""

    if isinstance(value, str):
        name = canonical_palette_name(value)
        if name not in PALETTES:
            raise ValueError(
                f"Unsupported scientific palette {value!r}; choose one of "
                + ", ".join(sorted(PALETTES))
                + " or provide hexadecimal colour stops"
            )
        return name
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) < 2:
        raise TypeError("palette must be a supported name or at least two hexadecimal colours")
    colors = [str(color).upper() for color in value]
    if not all(re.fullmatch(r"#[0-9A-F]{6}", color) for color in colors):
        raise ValueError("custom palette colours must use six-digit hexadecimal notation")
    return colors


def palette_colors(value: str | Sequence[str]) -> list[str]:
    normalized = normalize_palette(value)
    return list(PALETTES[normalized]) if isinstance(normalized, str) else normalized


__all__ = [
    "BLUE_RED", "CATEGORICAL", "DEFAULT_DIVERGING_PALETTE",
    "DEFAULT_GROUPED_PALETTE", "DEFAULT_SEQUENTIAL_PALETTE", "GROUPED",
    "OCEAN_TEAL", "PALETTES", "canonical_palette_name", "normalize_palette",
    "palette_colors",
]
