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

Text extraction garbles equations, symbols and tables and misses figures drawn as vector graphics,
so each of the first 40 pages is also rendered as an image with pdfium (`page-NN.jpg`, long edge at
most 1600 px), as Claude reads a PDF page by page as text and image and DeepSeek's own harness
renders pages with pdfium for its image reader. The figures a PDF embeds as images are saved too
(`page-NN-figure-K.jpg`; images under 200 000 pixels are taken for logos and skipped). Both lie
beside the text in the same cache and under the same rules (`<sha256>.v3.figures/`), and each page
of the text names its page image and figures above its text. The context lists the figures, the
note tells agents to read a page's image where its text is garbled, and the sandbox may read both.
A model that reads images opens one with `read_file` like any image; an agent whose model reads
images is told to look at a paper's figure before reproducing it and to compare its own figure
with it once. For DeepSeek, which takes images in user messages over Chat Completions, the images a
tool returned move into a user message right after that turn's tool results, as OpenCode does: the
LangChain integration would otherwise send them as base64 text, and LangChain's profiles, which mark
DeepSeek models text-only, would have the agent replace them with a note; the Flash models on
DeepSeek's own endpoint are marked as reading images (`model_config.py`).

Unchanged: `paper.import` and `paper.register` (no desktop entry uses them), portable exports, and
the agents' tools and permissions.

Consequences. The model provider receives the text of an attached PDF when an agent reads it; for a
paper whose publisher reserves text and data mining or AI use, attaching it is the user's decision.
Scanned or password-protected PDFs give an error note in the context; there is no OCR. A model that
cannot read images has only the garbled text and the captions for equations and figures. pypdf
(pure Python, BSD licence) and pypdfium2 (Apache-2.0 or BSD-3, prebuilt wheels) are core
dependencies; saving images uses Pillow, already installed. Page images take about 0.5 MB each.

Regression coverage: `tests/test_oceanx/test_pdf_text.py`.
