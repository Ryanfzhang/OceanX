"""Preserve reproduction specs and require the worker's comparison at publication."""
from __future__ import annotations

import hashlib
from pathlib import Path

from deepagents.middleware.summarization import (
    DEEPAGENTS_DEFAULT_SUMMARY_PROMPT, SummarizationState, create_summarization_middleware,
)
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from oceanx.reproduction_state import (
    FigureReview, FigureSpec, ReproductionStore, TermEvidence, digest,
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
For each registered figure, record its intended output_file in the spec. Save it in outputs,
open the original and generated images yourself, and call publish_reproduction_figure with the
reference and a complete panel-by-panel comparison. Fix mismatches before publishing. Any change
to the output, spec or ledger invalidates that comparison. No other model checks your work;
you remain responsible for truthful comparisons and numerical validation. Unregistered outputs
and other tasks have no added publication gate.
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

    def _request(self, request):
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

    def wrap_tool_call(self, request, handler):
        self._activate(request)
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        self._activate(request)
        return await handler(request)


def reproduction_tools(*, work_root: Path, backend, on_change=None):
    store = ReproductionStore(work_root)

    async def reference_bytes(path):
        # Use the same sandbox permissions as ordinary agent reads; never read an
        # arbitrary model-supplied source path with the server's filesystem access.
        result = (await backend.adownload_files([path]))[0]
        if result.error or not result.content:
            raise ValueError(f"Cannot read original figure: {result.error}")
        if len(result.content) > 20 * 1024 * 1024:
            raise ValueError("Use a rendered paper page image smaller than 20 MiB")
        from PIL import Image
        import io
        with Image.open(io.BytesIO(result.content)) as image:
            image.verify()
        return result.content

    @tool
    async def record_reproduction_spec(spec: FigureSpec, correction_reason: str = "") -> str:
        """Persist original paper figure specs before analysis. Append corrections, never overwrite.

        reference_image must be the original paper page rendered as a PNG/JPEG, not a generated plot.
        List all budget terms, including those whose derivability is still pending.
        """
        try:
            raw = await reference_bytes(spec.reference_image)
            # Keep a durable original, independent of scratch cleanup or source image replacement.
            image_hash = hashlib.sha256(raw).hexdigest()
            reference = store.root / "references" / f"{image_hash}.png"
            reference.parent.mkdir(parents=True, exist_ok=True)
            reference.write_bytes(raw)
            spec = spec.model_copy(update={"reference_image": str(reference)})
            # Bound preserved contracts explicitly rather than silently truncating them.
            if len(store.context()) + len(spec.model_dump_json()) > 64_000:
                raise ValueError("Contracts exceed 64,000 characters; keep specs concise")
            path = store.register(spec, correction_reason)
            if on_change is not None:
                await on_change()
            return f"Original specification preserved at {path}. Pending terms: {store.pending(spec.figure_id)}"
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

    @tool
    async def publish_reproduction_figure(
        figure_id: str, output_file: str, reference_image: str, comparison: FigureReview,
    ) -> str:
        """Publish a reproduced figure after the working agent's panel-by-panel comparison.

        First read the original and the saved output. Supply the original reference and observed
        plot type, x/y axes, quantities/units and layout for every panel. Mark remaining mismatches
        as failed. This validates the comparison record, not the scientific truth of its claims.
        No separate model or reviewer is called.
        """
        try:
            store.invalidate_review(figure_id)
            if on_change is not None:
                await on_change()
            spec = store.spec(figure_id)
            original = await reference_bytes(reference_image)
            original_hash = hashlib.sha256(original).hexdigest()
            if original_hash != digest(Path(spec.reference_image)):
                raise ValueError("Reference does not match the registered original")
            output = store.output(output_file)
            store.approve(figure_id, output, comparison, reference_hash=original_hash,
                          output_hash=digest(output), contract_hash=store.contract_digest(figure_id))
            if on_change is not None:
                await on_change()
            return "Comparison record accepted; figure is published."
        except (OSError, ValueError) as error:
            return f"Not published: {error}"

    return [record_reproduction_spec, record_reproduction_term, publish_reproduction_figure]
