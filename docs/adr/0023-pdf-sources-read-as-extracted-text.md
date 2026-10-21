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

Unchanged: `paper.import` and `paper.register` (no desktop entry uses them), portable exports, and
the agents' tools and permissions.

Consequences. The model provider receives the text of an attached PDF when an agent reads it; for a
paper whose publisher reserves text and data mining or AI use, attaching it is the user's decision.
Scanned or password-protected PDFs give an error note in the context; there is no OCR. Equations
and figures do not survive extraction, so a value read off a figure still needs the PDF or the
published data. pypdf (pure Python, BSD licence) is a new core dependency.

Regression coverage: `tests/test_oceanx/test_pdf_text.py`.
