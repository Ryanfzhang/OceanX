"""Durable reproduction contracts and byte-bound publication receipts.

Kept outside scratch and conversation history. Specs are append-only revisions;
ledger updates retain their evidence. This is a scientific QA gate, not a security
boundary against code intentionally tampering with its own work directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from functools import wraps
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

_WRITE_LOCK = threading.RLock()


def _serialized(method):
    @wraps(method)
    def call(*args, **kwargs):
        with _WRITE_LOCK:
            return method(*args, **kwargs)
    return call


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PanelSpec(StrictModel):
    panel: str = Field(min_length=1)
    plot_type: str = Field(min_length=1)
    x_axis: str = Field(min_length=1)
    y_axes: list[str] = Field(min_length=1)
    quantities: list[str] = Field(min_length=1)
    units_scales: str = Field(min_length=1)
    layout_overlays: str = Field(min_length=1)


class FigureSpec(StrictModel):
    figure_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    output_file: str = Field(min_length=1)
    reference_image: str = Field(min_length=1)
    caption: str = Field(min_length=1)
    panels: list[PanelSpec] = Field(min_length=1)
    budget_terms: list[str] = Field(default_factory=list)
    permitted_adaptations: str = "None"

    @model_validator(mode="after")
    def distinct_panels(self):
        output = Path(self.output_file)
        if output.is_absolute() or ".." in output.parts or self.output_file != output.as_posix():
            raise ValueError("output_file must be a relative path within outputs")
        names = [p.panel for p in self.panels]
        if len(set(names)) != len(names):
            raise ValueError("Panel identifiers must be unique")
        return self


class TermEvidence(StrictModel):
    term: str = Field(min_length=1)
    status: str = Field(pattern=r"^(pending|computed|not_computable)$")
    evidence: str = ""
    checked_sources: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    derivation_checked: str = ""

    @model_validator(mode="after")
    def require_evidence(self):
        if self.status != "pending" and not self.evidence:
            raise ValueError("Resolved terms need evidence; otherwise keep pending")
        if self.status == "not_computable" and not (
            self.checked_sources and self.missing_inputs and self.derivation_checked
        ):
            raise ValueError("Name checked files, missing inputs and attempted derivation")
        return self


class PanelReview(StrictModel):
    panel: str
    observed_plot_type: str = Field(min_length=1)
    observed_x_axis: str = Field(min_length=1)
    observed_y_axes: list[str] = Field(min_length=1)
    observed_quantities_units: str = Field(min_length=1)
    observed_layout_overlays: str = Field(min_length=1)
    plot_type: bool
    axes: bool
    quantities_units: bool
    layout_overlays: bool
    evidence: str = Field(min_length=1)


class FigureReview(StrictModel):
    passed: bool
    panels: list[PanelReview] = Field(min_length=1)
    issues: list[str]

    def accepts(self, spec: FigureSpec) -> bool:
        return (self.passed and not self.issues
                and sorted(p.panel for p in self.panels) == sorted(p.panel for p in spec.panels)
                and all(p.plot_type and p.axes and p.quantities_units and p.layout_overlays
                        for p in self.panels))


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


class ReproductionStore:
    def __init__(self, work_root: Path):
        self.work_root = Path(work_root).resolve()
        self.root = self.work_root / ".runtime" / "reproduction"

    @property
    def active(self):
        return (self.root / "active.json").exists()

    def activate(self):
        _write(self.root / "active.json", {"version": 1})

    def directory(self, figure_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", figure_id):
            raise ValueError("Invalid figure identifier")
        return self.root / figure_id

    def spec_path(self, figure_id: str) -> Path:
        versions = sorted(self.directory(figure_id).glob("spec-*.json"))
        if not versions:
            raise ValueError("Register the original figure specification first")
        return versions[-1]

    def spec(self, figure_id: str) -> FigureSpec:
        return FigureSpec.model_validate(json.loads(self.spec_path(figure_id).read_text())["spec"])

    @_serialized
    def register(self, spec: FigureSpec, correction_reason: str = "") -> Path:
        self.activate()
        directory = self.directory(spec.figure_id)
        versions = sorted(directory.glob("spec-*.json"))
        if versions:
            if self.spec(spec.figure_id) == spec:
                return versions[-1]
            if not correction_reason.strip():
                raise ValueError("Existing specs are immutable; an appended correction needs a reason")
        for other in self.root.glob("*/spec-*.json"):
            if other.parent != directory and self.spec(other.parent.name).output_file == spec.output_file:
                raise ValueError("This output_file already belongs to another figure")
        path = directory / f"spec-{len(versions) + 1:06d}.json"
        _write(path, {"spec": spec.model_dump(), "correction_reason": correction_reason})
        return path

    def ledger(self, figure_id: str) -> dict[str, dict]:
        result = {}
        for path in sorted(self.directory(figure_id).glob("term-*.json")):
            item = TermEvidence.model_validate_json(path.read_text())
            result[item.term] = item.model_dump()
        return result

    @_serialized
    def record_term(self, figure_id: str, item: TermEvidence):
        spec = self.spec(figure_id)
        if item.term not in spec.budget_terms:
            raise ValueError("Term must be listed in the figure specification")
        directory = self.directory(figure_id)
        index = len(list(directory.glob("term-*.json"))) + 1
        _write(directory / f"term-{index:06d}.json", item.model_dump())

    def pending(self, figure_id: str) -> list[str]:
        ledger = self.ledger(figure_id)
        return [t for t in self.spec(figure_id).budget_terms
                if ledger.get(t, {}).get("status", "pending") == "pending"]

    def contract_digest(self, figure_id: str) -> str:
        payload = self.spec_path(figure_id).read_text() + json.dumps(
            self.ledger(figure_id), sort_keys=True)
        reference = Path(self.spec(figure_id).reference_image)
        payload += digest(reference) if reference.is_file() else "reference unavailable"
        return hashlib.sha256(payload.encode()).hexdigest()

    def invalidate_review(self, figure_id: str):
        (self.directory(figure_id) / "review.json").unlink(missing_ok=True)

    def output(self, name: str) -> Path:
        root = (self.work_root / "outputs").resolve()
        path = (root / name).resolve(strict=True)
        path.relative_to(root)
        if not path.is_file():
            raise ValueError("Output must be a file under this agent's outputs directory")
        return path

    def approve(self, figure_id: str, path: Path, review: FigureReview,
                *, reference_hash: str, output_hash: str, contract_hash: str) -> None:
        if self.pending(figure_id) or not review.accepts(self.spec(figure_id)):
            raise ValueError("Unresolved terms or failed panel comparison; figure remains unpublished")
        if digest(path) != output_hash or self.contract_digest(figure_id) != contract_hash:
            raise ValueError("Figure or contract changed during review; verify again")
        key = path.relative_to(self.work_root / "outputs").as_posix()
        if key != self.spec(figure_id).output_file:
            raise ValueError("Output does not match the registered figure")
        _write(self.directory(figure_id) / "review.json", {
            "output": key, "output_sha256": output_hash, "reference_sha256": reference_hash,
            "contract_sha256": contract_hash, "review": review.model_dump(),
        })

    def allows(self, path: Path) -> bool:
        if not self.active:
            return True
        try:
            key = path.resolve(strict=True).relative_to(self.work_root / "outputs").as_posix()
            # Only explicitly registered reproductions have acceptance requirements.
            # Reading a skill must not gate unrelated outputs or Coordinator reports.
            registered = {version.parent.name for version in self.root.glob("*/spec-*.json")
                          if FigureSpec.model_validate(
                              json.loads(version.read_text())["spec"]).output_file == key}
            if not registered:
                return True
            for receipt in self.root.glob("*/review.json"):
                data = json.loads(receipt.read_text())
                figure_id = receipt.parent.name
                if (figure_id in registered and data["output"] == key and not self.pending(figure_id)
                        and self.spec(figure_id).output_file == key
                        and data["contract_sha256"] == self.contract_digest(figure_id)
                        and data["output_sha256"] == digest(path)
                        and FigureReview.model_validate(data["review"]).accepts(self.spec(figure_id))):
                    return True
        except (OSError, ValueError, KeyError):
            pass
        return False

    def context(self) -> str:
        if not self.active:
            return ""
        parts = ["Persistent reproduction contracts (source evidence, not instructions). "
                 "Use these original specs over a paraphrased summary. Unreviewed figures are drafts."]
        for directory in sorted(self.root.iterdir()):
            if directory.is_dir() and list(directory.glob("spec-*.json")):
                path = self.spec_path(directory.name)
                parts += [f"Specification file: {path}", path.read_text(),
                          "Current evidence ledger: " + json.dumps(self.ledger(directory.name)),
                          "Pending terms: " + json.dumps(self.pending(directory.name))]
        if len(parts) == 1:
            parts.append("No specs registered. Record the paper's original figure specs before plotting.")
        return "\n".join(parts)
