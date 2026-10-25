# PDF sources are read as extracted text

ADR 0012 kept every PDF opaque to the model. The desktop attaches a PDF through the general
source import (`source.import`), which gives agents its path but no way to read it: `read_file`
would send the whole PDF to the provider, which DeepSeek is not known to accept, and the analysis
environment has no PDF library. A paper the researcher supplies to be checked or reproduced must be
readable, so this ADR supersedes decision 3 of ADR 0012 for PDFs attached as Task sources.

When a Task source is a PDF, or a folder whose top level holds PDFs (the first ten by name), the
backend extracts their text locally with pypdf, page by page, into the project's
`.oceanx/cache/pdf-text`, each file named by the SHA-256 of its PDF. Nothing is sent to a third
party to extract it. The agent context lists each text file with a note that it is the document's
content, not instructions; the sandbox may read those files and no other part of the cache. Agents
read them with `read_file`, paged like any text, so the text only ever reaches a model as a tool
result. When the workspace disclosure policy does not allow `document_text`, the context says the
text is withheld and the files are not readable. DeepSeek models are marked as taking no PDF
attachments, so a PDF opened directly returns a note instead of an unknown provider error.

The figures a PDF embeds as images are saved beside its text, in the same cache and under the same
rules (`<sha256>.v2.figures/page-NN-figure-K.jpg`, long edge at most 1600 px; images under 200 000
pixels are taken for logos and skipped), and each page of the text names the figure images on that
page, next to their captions. The context lists them too, and the sandbox may read them. A model
that reads images opens one with `read_file` like any image; an agent whose model reads images is
told to look at a paper's figure before reproducing it and to compare its own figure with it once.

Unchanged: `paper.import` and `paper.register` (no desktop entry uses them), portable exports, and
the agents' tools and permissions.

Consequences. The model provider receives the text of an attached PDF when an agent reads it; for a
paper whose publisher reserves text and data mining or AI use, attaching it is the user's decision.
Scanned or password-protected PDFs give an error note in the context; there is no OCR. Equations
do not survive extraction, and a figure drawn as vector graphics has no image file; a model that
cannot read images still has only the captions. pypdf (pure Python, BSD licence) is a new core
dependency; saving figures uses Pillow, already installed.

Regression coverage: `tests/test_oceanx/test_pdf_text.py`.
