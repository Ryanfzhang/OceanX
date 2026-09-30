import pytest

from oceanx.palettes import BLUE_RED, OCEAN_TEAL, normalize_palette, palette_colors


def test_palette_aliases_use_shared_semantic_defaults():
    assert normalize_palette("sequential") == "ocean_teal"
    assert normalize_palette("diverging") == "blue_red"
    assert normalize_palette("RdBu_r") == "blue_red"
    assert palette_colors("ocean_teal") == list(OCEAN_TEAL)
    assert palette_colors("grouped") == list(BLUE_RED)


def test_supported_model_palette_and_custom_stops_are_preserved():
    assert normalize_palette("viridis") == "viridis"
    assert normalize_palette(["#001122", "#AABBCC"]) == ["#001122", "#AABBCC"]


def test_scale_type_selects_semantic_default_without_overriding_model_choice():
    assert normalize_palette("sequential") == "ocean_teal"
    assert normalize_palette("diverging") == "blue_red"


def test_unknown_palette_is_rejected_instead_of_silently_recoloured():
    with pytest.raises(ValueError, match="Unsupported scientific palette"):
        normalize_palette("almost-viridis")
