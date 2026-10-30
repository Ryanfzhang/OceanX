"""Preserve source figures and check structure in a fresh visual context."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from deepagents.middleware.summarization import (
    DEEPAGENTS_DEFAULT_SUMMARY_PROMPT, SummarizationState, create_summarization_middleware,
)
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from oceanx.reproduction_state import (
    FigureSpec, ReproductionStore, TermEvidence, digest, _write,
)

SUMMARY_PROMPT = DEEPAGENTS_DEFAULT_SUMMARY_PROMPT + """

For paper-reproduction sessions only, apply these continuity requirements:
- Do not paraphrase figure specifications or acceptance requirements stored by
  record_reproduction_spec. Reference their exact files instead; the framework
  re-injects the originals. If not yet recorded, preserve the requirements verbatim
  and make recording them from the source the first pending action.
- Separate verified findings (with evidence paths) from tentative choices and pending
  investigations. Never promote a tentative choice into an established fact or a to-do.
- A term is not computable only with checked files, specific missing inputs and an
  explanation of why it cannot be derived. Otherwise retain pending status.
- Acceptance steps must name both the original reference and the generated artifact.
  Never reduce scientific comparison to checking a generated figure's layout.
"""

REPRODUCTION_POLICY = """
# Durable paper reproduction
When reproducing a paper, read /skills/paper-reproduction/SKILL.md first.
After reading each original figure, call record_reproduction_spec before computing or plotting it.
Record every panel's plot type, axes, quantities, units/scales and layout/overlays, the caption,
reference page image, and each budget term. The framework preserves these files outside scratch
and re-injects them on every model call, including after compaction. Do not replace them with a
summary. Correct a spec only by appending an evidenced correction through the same tool.
Use record_reproduction_term to keep computed, pending and not_computable terms separate.
Not_computable requires checked source files, named missing inputs and a derivation check;
otherwise the term stays pending. Resolve pending terms before plotting a budget. A residual
must be labelled as such; it cannot substitute for independently unresolved budget terms.
For each registered figure, preserve its PDF source/page and normalized figure/panel regions with
record_reproduction_spec. The framework renders them, extracts source text and generates an
illustrated repro_spec.md. A Markdown image link is not pixels: open the saved reference images.
Use oceanx.reproduction_images.save_reproduction_figure from the plotting script to save the actual
figure and export its panel crops and plotting-object metadata. Pass that metadata file to
publish_reproduction_figure. An independent fresh-context check compares structure, not whether
new scientific values/trends agree with the paper. Numerical validation remains your responsibility.
Only parameter adjustments may be justified by the worker. Changes of quantity, variable or plot
type require an exact user quotation and its message ID; never alter the original to match output.
After at most two repair rounds, retain unresolved drafts and report specific differences to the
user for a decision; do not continue revising or claim complete reproduction. Missing evidence or
unreadable labels are uncertain. Unregistered outputs and other tasks have no added gate.
"""

class ReproductionSummarizationMiddleware(AgentMiddleware):
    """Retain native summaries until this worker actually enters reproduction."""
    state_schema = SummarizationState

    @property
    def name(self):
        return "SummarizationMiddleware"

    def __init__(self, model, backend, work_root, *, factory=create_summarization_middleware):
        self.store = ReproductionStore(work_root)
        self.standard = factory(model, backend)
        self.reproduction = factory(model, backend, summary_prompt=SUMMARY_PROMPT)

    def wrap_model_call(self, request, handler):
        selected = self.reproduction if self.store.active else self.standard
        return selected.wrap_model_call(request, handler)

    async def awrap_model_call(self, request, handler):
        selected = self.reproduction if self.store.active else self.standard
        return await selected.awrap_model_call(request, handler)


class ReproductionMiddleware(AgentMiddleware):
    """Runs inside the built-in summarizer, so even its retry gets original specs."""
    def __init__(self, work_root: Path):
        self.store = ReproductionStore(work_root)
        self._users = {}

    def _request(self, request):
        for message in request.state.get("messages", []):
            if isinstance(message, HumanMessage) and message.id:
                self._users.setdefault(message.id, message)
        if self.store.active:
            self.store.remember_users(self._users.values())
        context = self.store.context()
        if not context:
            return request
        # Keep this out of durable message state and out of the summarizer's input.
        return request.override(messages=[*request.messages, HumanMessage(content=context)])

    def wrap_model_call(self, request, handler):
        return handler(self._request(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._request(request))

    def _activate(self, request):
        call = request.tool_call
        path = str(call.get("args", {}).get("file_path", ""))
        if call["name"] == "read_file" and path.endswith("/paper-reproduction/SKILL.md"):
            self.store.activate()
            self.store.remember_users(self._users.values())

    def wrap_tool_call(self, request, handler):
        self._activate(request)
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        self._activate(request)
        return await handler(request)


def reproduction_tools(*, work_root: Path, backend, model=None, on_change=None):
    from oceanx.reproduction_images import image_bytes, pair_image, preview_bytes, render_pdf_regions
    from oceanx.reproduction_review import check_figure

    store = ReproductionStore(work_root)
    figure_locks = {}

    async def read_bytes(path, limit=20 * 1024 * 1024):
        # All external reads retain the ordinary sandbox permissions.
        result = (await backend.adownload_files([path]))[0]
        if result.error or not result.content:
            raise ValueError(f"Cannot read evidence: {result.error}")
        if len(result.content) > limit:
            raise ValueError(f"Evidence exceeds {limit} bytes")
        return result.content

    async def reference_bytes(path):
        return image_bytes(await read_bytes(path))

    @tool
    async def record_reproduction_spec(spec: FigureSpec, correction_reason: str = "") -> str:
        """Save original specs, PDF regions and captions before computing each reproduced figure.

        Supply source.pdf/page and normalized [left,top,right,bottom] figure and panel boxes.
        The framework saves original pixels, region text and an illustrated repro_spec.md.
        reference_image is used only for legacy/image-only references if no PDF source exists.
        verified_labels are literal labels you have checked against the original, not guesses.
        Non-parameter adjustments require an exact user quotation. Its message ID is
        resolved from preserved user messages if omitted; worker prose is not authorization.
        """
        try:
            users = store.user_messages()
            for adjustment in spec.adjustments:
                if adjustment.kind != "parameter":
                    if not adjustment.authorization_message_id and adjustment.user_authorization:
                        adjustment.authorization_message_id = next((key for key, text in users.items()
                            if adjustment.user_authorization in text), "")
                    if not (adjustment.user_authorization and adjustment.authorization_message_id in users
                            and adjustment.user_authorization in users[adjustment.authorization_message_id]):
                        raise ValueError("Quantity, variable or plot-type changes need a matching user message and quotation")
            source_record = None
            if spec.source is not None:
                raw = await read_bytes(spec.source.pdf, limit=80 * 1024 * 1024)
                region_ids = [r.panel for r in spec.source.panels]
                if len(region_ids) != len(set(region_ids)) or set(region_ids) != {p.panel for p in spec.panels}:
                    raise ValueError("Supply one source region for every panel")
                regions = {"figure": spec.source.figure_box}
                regions.update({f"panel-{i}": r.box for i, r in enumerate(spec.source.panels)})
                key = hashlib.sha256(raw + json.dumps(regions, sort_keys=True).encode()
                                     + str(spec.source.page).encode()).hexdigest()
                folder = store.root / "references" / key
                source_record = render_pdf_regions(raw, spec.source.page, regions, folder)
                source_record.update(pdf=spec.source.pdf, page=spec.source.page,
                                     pdf_sha256=hashlib.sha256(raw).hexdigest(),
                                     panel_regions={r.panel: f"panel-{i}" for i, r in enumerate(spec.source.panels)})
                reference = Path(source_record["regions"]["figure"]["image"])
            else:
                raw = await reference_bytes(spec.reference_image)
                key = hashlib.sha256(raw).hexdigest()
                reference = store.root / "references" / f"{key}.png"
                reference.parent.mkdir(parents=True, exist_ok=True)
                reference.write_bytes(raw)
            spec = spec.model_copy(update={"reference_image": str(reference)})
            preserved = sum(len(store.spec(d.name).model_dump_json())
                for d in store.root.glob("*/") if d.name != spec.figure_id and list(d.glob("spec-*.json")))
            if preserved + len(spec.model_dump_json()) > 64_000:
                raise ValueError("Contracts exceed 64,000 characters; keep specs concise")
            path = store.register(spec, correction_reason)
            if source_record:
                _write(store.directory(spec.figure_id) / "source.json", source_record)
            store.write_markdown()
            if on_change is not None:
                await on_change()
            return (f"Original specification preserved at {path}. Illustrated record: {store.root / 'repro_spec.md'}. "
                    f"Pending terms: {store.pending(spec.figure_id)}")
        except (OSError, ValueError) as error:
            return f"Not recorded: {error}"

    @tool
    async def record_reproduction_term(figure_id: str, evidence: TermEvidence) -> str:
        """Append evidence for one budget term; unsupported missing-data claims remain pending."""
        try:
            store.record_term(figure_id, evidence)
            if on_change is not None:
                await on_change()
            return f"Recorded. Pending terms: {store.pending(figure_id)}"
        except (OSError, ValueError) as error:
            return f"Not recorded: {error}"

    async def publish(figure_id: str, output_file: str, metadata_file: str) -> str:
        try:
            spec = store.spec(figure_id)
            output = store.output(output_file)
            if output_file != spec.output_file:
                raise ValueError("Output does not match the registered figure")
            receipt = store.directory(figure_id) / "review.json"
            if receipt.is_file() and json.loads(receipt.read_text()).get("format") == 2 and store.allows(output):
                return "Figure is already published with a current independent comparison; no repeat check needed."
            if store.repair_exhausted(figure_id):
                return "Repair limit reached. Retain drafts; report the recorded differences and ask the user to decide."
            if model is None:
                raise ValueError("No visual checker configured; comparison cannot be claimed")
            if (getattr(model, "profile", None) or {}).get("image_inputs") is False:
                raise ValueError("Configured model has no image input support; retain draft for user review")
            if store.pending(figure_id):
                raise ValueError(f"Resolve pending terms first: {store.pending(figure_id)}")
            output_hash, contract_hash = digest(output), store.contract_digest(figure_id)
            metadata = json.loads(await read_bytes(metadata_file, limit=512_000))
            if metadata.get("format") != 1 or metadata["output_sha256"] != output_hash:
                raise ValueError("Plotting metadata does not match output bytes; export from the plotting script again")
            code = await read_bytes(metadata["source_code"])
            if hashlib.sha256(code).hexdigest() != metadata["source_sha256"]:
                raise ValueError("Plotting source changed since metadata export")
            images = [("Original full figure", Path(spec.reference_image).read_bytes()),
                      ("Generated full figure", preview_bytes(output))]
            source_path = store.directory(figure_id) / "source.json"
            source = json.loads(source_path.read_text()) if source_path.exists() else None
            if source:
                images.append(("Original page with region boxes", Path(source["overlay_image"]).read_bytes()))
                for panel, key in source["panel_regions"].items():
                    images.append((f"Original panel {panel}", Path(source["regions"][key]["image"]).read_bytes()))
            for panel in metadata["panels"]:
                raw = await read_bytes(panel["image"])
                if hashlib.sha256(raw).hexdigest() != panel["image_sha256"]:
                    raise ValueError("Panel crop changed since plotting metadata export")
                images.append((f"Generated panel {panel['panel']}", image_bytes(raw)))
            # Keep individual crops as well as an overview: a composite alone hides small text.
            images.append(("Overview only: original left, reproduction right", pair_image(images[0][1], images[1][1])))
            store.invalidate_review(figure_id)
            if on_change is not None:
                await on_change()
            check_path = store.record_check(figure_id, {"output_sha256": output_hash,
                "contract_sha256": contract_hash, "accepted": False, "status": "started",
                "note": "No verdict until this record is completed; interrupted checks are uncertain."})
            review = await check_figure(model, spec, metadata, images, source=source,
                                       user_messages=store.user_messages())
            accepted = review.accepts(spec)
            if accepted:
                store.approve_structural(figure_id, output, review, output_hash=output_hash, contract_hash=contract_hash)
            store.finish_check(check_path, {"output_sha256": output_hash, "contract_sha256": contract_hash,
                "metadata": metadata, "review": review.model_dump(), "accepted": accepted, "status": "completed"})
            if on_change is not None:
                await on_change()
            detail = review.model_dump_json()
            if accepted:
                return "Structural comparison accepted; figure is published. Scientific differences remain in the record. " + detail
            if store.repair_exhausted(figure_id):
                return "Repair limit reached. Retain draft and ask the user to decide. " + detail
            return "Not published; correct structural issues or clarify uncertain evidence. Do not force scientific agreement. " + detail
        except (OSError, ValueError, KeyError) as error:
            return f"Not published: {error}"

    @tool
    async def publish_reproduction_figure(figure_id: str, output_file: str, metadata_file: str) -> str:
        """Compare one saved reproduction with the original in a fresh visual context.

        metadata_file is the JSON from save_reproduction_figure, bound to the output bytes.
        Do not supply a self-assessed pass/fail. Scientific differences are recorded, not rejected.
        After the initial check and two repair checks, stop and present unresolved drafts to the user.
        """
        async with figure_locks.setdefault(figure_id, asyncio.Lock()):
            return await publish(figure_id, output_file, metadata_file)

    return [record_reproduction_spec, record_reproduction_term, publish_reproduction_figure]
