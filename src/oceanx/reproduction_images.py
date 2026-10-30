"""PDF reference regions and evidence exported from actual matplotlib objects.

No model calls here. Coordinates are normalized left/top/right/bottom in the
rendered page. Crops are rendered separately, so small panels keep their pixels.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw


def image_bytes(raw: bytes) -> bytes:
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        return buffer.getvalue()


def render_pdf_regions(raw: bytes, page_number: int, regions: dict, folder: Path) -> dict:
    import pypdfium2 as pdfium

    folder.mkdir(parents=True, exist_ok=True)
    with pdfium.PdfDocument(raw) as document:
        if not 1 <= page_number <= len(document):
            raise ValueError("PDF page number is out of range (one-based)")
        page = document[page_number - 1]
        width, height = page.get_size()
        textpage = page.get_textpage()
        bitmap = page.render(scale=1600 / max(width, height))
        full = bitmap.to_pil().convert("RGB")
        full.save(folder / "page.png")
        overlay = full.copy()
        draw = ImageDraw.Draw(overlay)
        result = {"page_image": str(folder / "page.png"), "regions": {}}
        for name, box in regions.items():
            left, top, right, bottom = box
            if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
                raise ValueError("Region must be normalized left/top/right/bottom within the page")
            crop_width, crop_height = (right - left) * width, (bottom - top) * height
            rendered = page.render(scale=1600 / max(crop_width, crop_height),
                                   crop=(left * width, (1 - bottom) * height,
                                         (1 - right) * width, top * height))
            path = folder / f"{name}.png"
            rendered.to_pil().convert("RGB").save(path)
            # PDFium uses bottom-left page coordinates for text extraction.
            text = textpage.get_text_bounded(left * width, (1 - bottom) * height,
                                            right * width, (1 - top) * height)
            result["regions"][name] = {"image": str(path), "text": text, "box": box}
            rect = [left * full.width, top * full.height, right * full.width, bottom * full.height]
            draw.rectangle(rect, outline="red", width=3)
            draw.text((rect[0] + 3, rect[1] + 3), name, fill="red")
            rendered.close()
        overlay.save(folder / "regions.png")
        result["overlay_image"] = str(folder / "regions.png")
        result["page_text"] = textpage.get_text_range()
        textpage.close()
        bitmap.close()
        page.close()
    return result


def preview_bytes(path: Path) -> bytes:
    if path.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(path) as document:
            if len(document) != 1:
                raise ValueError("Publish one figure per single-page PDF")
            page = document[0]
            bitmap = page.render(scale=1600 / max(page.get_size()))
            buffer = io.BytesIO()
            bitmap.to_pil().convert("RGB").save(buffer, format="PNG")
            bitmap.close()
            page.close()
            return buffer.getvalue()
    return image_bytes(path.read_bytes())


def pair_image(original: bytes, generated: bytes) -> bytes:
    with Image.open(io.BytesIO(original)) as left, Image.open(io.BytesIO(generated)) as right:
        panels = []
        for source in (left, right):
            item = source.convert("RGB")
            item.thumbnail((760, 1100))
            panels.append(item)
        canvas = Image.new("RGB", (sum(p.width for p in panels), max(p.height for p in panels) + 24), "white")
        draw = ImageDraw.Draw(canvas)
        offset = 0
        for label, panel in zip(("Original", "Reproduction"), panels):
            draw.text((offset + 4, 4), label, fill="black")
            canvas.paste(panel, (offset, 24))
            offset += panel.width
        buffer = io.BytesIO()
        canvas.save(buffer, format="PNG")
        return buffer.getvalue()


def save_reproduction_figure(fig, output_file, *, panels, source_code, data_files=()):
    """Save a matplotlib figure and its actual artists, labels, and per-panel crops.

    panels maps paper panel IDs to lists of Axes (include twinx axes in the same
    panel). This records observable structure, NOT the correctness of calculations.
    Returns the JSON metadata path to pass to review_reproduction_figure.
    """
    from matplotlib.collections import PathCollection
    from matplotlib.transforms import Bbox

    output = Path(output_file).resolve()
    source = Path(source_code).resolve(strict=True)
    data = [Path(p).resolve(strict=True) for p in data_files]
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    fig.savefig(output, bbox_inches="tight")
    evidence = output.parent / ".reproduction-evidence" / output.name
    evidence.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, (name, axes) in enumerate(panels.items()):
        if not axes or any(ax not in fig.axes for ax in axes):
            raise ValueError("Each panel must name actual Axes from this figure")
        bounds = Bbox.union([ax.get_tightbbox(renderer) for ax in axes]).transformed(fig.dpi_scale_trans.inverted())
        # The delivery scanner skips draft filenames, not hidden directories.
        crop = evidence / f".panel-{index}.png"
        fig.savefig(crop, bbox_inches=bounds.expanded(1.03, 1.03), dpi=160)
        kinds = set()
        for ax in axes:
            if ax.lines:
                kinds.add("line")
            if any(isinstance(c, PathCollection) for c in ax.collections):
                kinds.add("scatter")
            if ax.images:
                kinds.add("image")
            if ax.containers:
                kinds.add("bar")
        rows.append({"panel": str(name), "image": str(crop),
                     "image_sha256": hashlib.sha256(crop.read_bytes()).hexdigest(),
                     "artist_types": sorted(kinds),
                     "axes": [{"x_label": ax.get_xlabel(), "y_label": ax.get_ylabel(),
                               "legend": ax.get_legend_handles_labels()[1],
                               "x_scale": ax.get_xscale(), "y_scale": ax.get_yscale()}
                              for ax in axes]})
    payload = {"format": 1, "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
               "source_code": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "data_files": [{"path": str(p), "size": p.stat().st_size} for p in data],
               "panels": rows}
    target = evidence / "structure.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return str(target)
