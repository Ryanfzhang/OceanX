"""Shared projection of cached scientific metadata; never scans source arrays."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from oceanx.artifacts.models import ArtifactVersion


def source_metadata_summary(artifact: ArtifactVersion, cache_root: Path | None) -> dict[str, object]:
    """Read the same version-keyed metadata cache used by Experts, without probing data.

    This is an optional hint, not a startup gate. Missing/corrupt caches fall back
    to explicitly uninspected registered metadata. No directory scan or imports.
    """
    raw = {key: artifact.content[key] for key in (
        "format", "dimensions", "time_range", "spatial_context", "variables",
        "coordinates", "data_variables",
    ) if key in artifact.content}
    raw["inspection"] = "registered_only"
    if cache_root is not None:
        key = hashlib.sha256(artifact.ref.key.encode("utf-8")).hexdigest()[:32]
        path = cache_root / f"{key}.json"
        try:
            if not cache_root.is_symlink() and not path.is_symlink():
                with path.open(encoding="utf-8") as stream:
                    content = stream.read(2_000_001)
                if len(content) <= 2_000_000:
                    payload = json.loads(content)
                    sources = payload.get("sources") if isinstance(payload, dict) else None
                    if isinstance(sources, list) and len(sources) == 1 and isinstance(sources[0], dict):
                        raw = sources[0]
        except (OSError, ValueError):
            pass
    return compact_source_metadata(raw)


def compact_source_metadata(raw: dict) -> dict[str, object]:
    """Project header facts, shared by explicit inspection and cached context."""
    source = compact_dataset_context({"sources": [raw]})["sources"][0]
    # Coordinator needs scientific metadata, not file manifests or array values.
    for key in ("path", "files", "error", "title", "handle", "registered_metadata"):
        source.pop(key, None)
    members = source.pop("members", [])
    if members:
        source["member_count"] = len(members)
        source["coordinate_scope"] = "first inspected member; variants listed separately"
        source["uninspected_members"] = sum(m.get("inspection") != "ready" for m in members)
        variants = []
        ranges = []
        variables = source.setdefault("data_variables", [])
        seen = {json.dumps(item, sort_keys=True) for item in variables}
        for member in members:
            coordinates = member.get("coordinates") or source.get("coordinates", [])
            for coord in coordinates:
                if coord not in source.get("coordinates", []) and coord not in variants:
                    variants.append(coord)
                if (coord.get("coordinate_role") == "time" and coord.get("extent")
                        and coord["extent"] not in ranges):
                    ranges.append(coord["extent"])
            for item in member.get("data_variables", []):
                description = {key: item[key] for key in ("name", "dims", "units", "standard_name") if key in item}
                identity = json.dumps(description, sort_keys=True)
                if identity not in seen:
                    variables.append(description)
                    seen.add(identity)
        source["time_ranges"] = ranges[:8]
        source["omitted_time_ranges"] = max(0, len(ranges) - 8)
        # A collection's first member range is not its overall coverage. Keep
        # per-member ranges rather than implying continuous sampling across gaps.
        source.pop("time_range", None)
        if variants:
            source["coordinate_variants"] = variants[:8]
            source["omitted_coordinate_variants"] = max(0, len(variants) - 8)
    for key in ("data_variables", "coordinates", "variables"):
        values = source.get(key)
        if isinstance(values, list) and len(values) > 32:
            source[key] = values[:32]
            source[f"omitted_{key}"] = len(values) - 32
    return source


def compact_dataset_context(context: dict[str, object]) -> dict[str, object]:
    """Keep the task DatasetContext useful without replaying bulky metadata.

    Full metadata stays in the immutable execution ``inputs.json``.  The
    participant needs paths, array layout, dimensions, coordinate extents,
    variable names, shapes, and units—not arbitrary global/variable attrs.
    """

    def compact_array(value: object) -> dict[str, object] | None:
        if not isinstance(value, dict):
            return None
        result = {
            key: value[key]
            for key in (
                "name",
                "dims",
                "shape",
                "dtype",
                "chunks",
                "coordinate_role",
                "extent",
                "spacing",
            )
            if key in value
        }
        attrs = value.get("attrs")
        if isinstance(attrs, dict):
            for key in ("units", "standard_name", "long_name", "positive"):
                if key in attrs:
                    result[key] = attrs[key]
        return result

    def compact_arrays(value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []
        return [item for raw in value if (item := compact_array(raw)) is not None]

    sources: list[dict[str, object]] = []
    raw_sources = context.get("sources")
    if isinstance(raw_sources, list):
        for raw_source in raw_sources:
            if not isinstance(raw_source, dict):
                continue
            source = {
                key: raw_source[key]
                for key in (
                    "handle",
                    "kind",
                    "title",
                    "path",
                    "files",
                    "format",
                    "inspection",
                    "error",
                    "dataset_layout",
                    "coordinate_scope",
                    "member_count",
                    "candidate_count",
                    "omitted_members",
                    "member_selection",
                    "dimensions",
                    "spatial_context",
                    "time_range",
                    "variables",
                )
                if key in raw_source
            }
            source["coordinates"] = compact_arrays(raw_source.get("coordinates"))
            source["data_variables"] = compact_arrays(raw_source.get("data_variables"))
            if raw_source.get("inspection") == "not_run" and isinstance(raw_source.get("metadata"), dict):
                source["registered_metadata"] = raw_source["metadata"]
            members: list[dict[str, object]] = []
            raw_members = raw_source.get("members")
            if isinstance(raw_members, list):
                for raw_member in raw_members:
                    if not isinstance(raw_member, dict):
                        continue
                    member = {
                        key: raw_member[key]
                        for key in (
                            "path",
                            "format",
                            "inspection",
                            "error",
                            "dimensions",
                        )
                        if key in raw_member
                    }
                    member["coordinates"] = compact_arrays(raw_member.get("coordinates"))
                    member["data_variables"] = compact_arrays(raw_member.get("data_variables"))
                    members.append(member)
            if members:
                source["members"] = members
            sources.append(source)
    return {
        key: context[key]
        for key in ("schema_version", "context_id", "scope", "task_id")
        if key in context
    } | {
        "sources": sources,
        "instruction": (
            "Use exact source paths and confirmed metadata. Registered metadata has not "
            "necessarily been inspected. Unknown or unavailable inspection is not a data "
            "or runtime failure; inspect only missing details needed by your analysis. "
            "The execution manifest carries the full context for code calls."
        ),
    }
