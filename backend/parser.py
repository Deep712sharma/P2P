"""
parser.py – Extract text, images, tables, and metadata from a research paper PDF.
Enhanced: tracks page numbers for figures/tables so the LLM can place them smartly.
"""

import pymupdf as fitz  # PyMuPDF
import os
import re
from pathlib import Path
from PIL import Image
import io

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    """Remove excess whitespace and control characters."""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _clean_cell(text: str) -> str:
    """Clean table cell text, preserving newlines."""
    # Replace horizontal whitespace with a single space
    text = re.sub(r'[ \t\r\f\v]+', ' ', text)
    # Strip spaces around newlines
    text = re.sub(r' \n', '\n', text)
    text = re.sub(r'\n ', '\n', text)
    # Collapse multiple newlines
    text = re.sub(r'\n+', '\n', text)
    return text.strip()


def _is_figure_caption(line: str) -> bool:
    return bool(re.match(r'^\s*(Figure|Fig\.?|FIGURE)\s*\d+', line, re.IGNORECASE))


def _is_table_caption(line: str) -> bool:
    return bool(re.match(r'^\s*(Table|TABLE)\s*\d+', line, re.IGNORECASE))


def _extract_caption_number(caption: str) -> int | None:
    """Return the figure/table number from a caption string."""
    m = re.search(r'\d+', caption)
    return int(m.group()) if m else None


# ─────────────────────────────────────────────────────────────────────────────
# Main parser
# ─────────────────────────────────────────────────────────────────────────────

def extract_pdf(pdf_path: str, img_output_dir: str | None = None) -> dict:
    """
    Extract structured content from a research-paper PDF.

    Returns:
        {
          "title": str,
          "authors": str,
          "abstract": str,
          "full_text": str,
          "pages": [ {"page_num": int, "text": str} ],
          "images": [
              {
                "path": str,
                "page": int,
                "caption": str,
                "caption_num": int | None,   # e.g. 1 for "Figure 1"
                "width": int,
                "height": int,
              }
          ],
          "tables": [
              {
                "caption": str,
                "page": int,
                "caption_num": int | None,   # e.g. 1 for "Table 1"
                "text": str,                 # surrounding table text block
              }
          ],
          "figure_captions": [ str ],
          "table_captions":  [ str ],
        }
    """
    doc = fitz.open(pdf_path)
    result = {
        "title": "",
        "authors": "",
        "abstract": "",
        "full_text": "",
        "pages": [],
        "images": [],
        "tables": [],
        "figure_captions": [],
        "table_captions": [],
    }

    # ── Image output directory ────────────────────────────────────────────────
    if img_output_dir is None:
        img_output_dir = str(Path(pdf_path).parent / "extracted_images")
    os.makedirs(img_output_dir, exist_ok=True)

    all_text_blocks: list[str] = []
    img_index = 0

    # Per-page captions (built incrementally, used for caption-image matching)
    page_fig_captions: dict[int, list[str]] = {}   # page_num → [caption, ...]
    page_tab_captions: dict[int, list[str]] = {}

    for page_num, page in enumerate(doc):
        pn = page_num + 1  # 1-indexed

        # ── Text ──────────────────────────────────────────────────────────────
        page_text = page.get_text("text")
        all_text_blocks.append(page_text)
        result["pages"].append({"page_num": pn, "text": page_text})

        # ── Captions ──────────────────────────────────────────────────────────
        page_fig_captions[pn] = []
        page_tab_captions[pn] = []
        for line in page_text.splitlines():
            if _is_figure_caption(line):
                cap = _clean(line)
                result["figure_captions"].append(cap)
                page_fig_captions[pn].append(cap)
            if _is_table_caption(line):
                cap = _clean(line)
                result["table_captions"].append(cap)
                page_tab_captions[pn].append(cap)

        # ── Images ────────────────────────────────────────────────────────────
        image_list = page.get_images(full=True)
        for img_info in image_list:
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
                img_bytes = base_image["image"]
                img_ext   = base_image["ext"]

                pil_img = Image.open(io.BytesIO(img_bytes))
                w, h = pil_img.size

                # Skip tiny decorative images (icons, logos, line art)
                if w < 120 or h < 120:
                    continue
                # Skip extremely wide/thin banners (header/footer rules)
                if h > 0 and (w / h) > 15:
                    continue

                img_filename = f"img_p{pn}_{img_index}.{img_ext}"
                img_path = os.path.join(img_output_dir, img_filename)
                with open(img_path, "wb") as f:
                    f.write(img_bytes)

                # Match caption: prefer captions on the same page, else ±1 page
                caption = ""
                cap_num = None
                for search_pn in [pn, pn - 1, pn + 1]:
                    for cap in page_fig_captions.get(search_pn, []):
                        caption = cap
                        cap_num = _extract_caption_number(cap)
                        break
                    if caption:
                        break

                result["images"].append({
                    "path":        img_path,
                    "page":        pn,
                    "caption":     caption,
                    "caption_num": cap_num,
                    "width":       w,
                    "height":      h,
                })
                img_index += 1
            except Exception:
                continue

        # ── Tables – position-aware structured extraction ──────────────────
        for cap in page_tab_captions[pn]:
            rows_data: list[list[str]] = []
            col_widths: list[float]    = []   # proportional, sums to 1.0

            # Find where the caption sits on this page (in PDF pt coords)
            cap_y = None
            try:
                hits = page.search_for(cap[:40])
                if hits:
                    cap_y = hits[0].y1   # bottom of caption text rect
            except Exception:
                pass

            # Helper: extract rows from a PyMuPDF Table object
            def _extract_table(tab) -> tuple[list[list[str]], list[float]]:
                raw = tab.extract()   # list[list[str | None]]
                cleaned = [
                    [_clean_cell(cell) if cell else "" for cell in row]
                    for row in (raw or [])
                    if any(cell for cell in row)   # skip completely empty rows
                ]
                # Compute proportional column widths from the table's col positions
                widths: list[float] = []
                try:
                    cols = tab.col_positions          # list of x-coords
                    if cols and len(cols) > 1:
                        spans = [cols[i+1] - cols[i] for i in range(len(cols)-1)]
                        total = sum(spans) or 1.0
                        widths = [s / total for s in spans]
                except Exception:
                    pass
                return cleaned, widths

            # Search current page first, then the page before/after
            search_pages = [pn]
            if pn > 1:              search_pages.append(pn - 1)
            if pn < len(doc):       search_pages.append(pn + 1)

            for spn in search_pages:
                if rows_data:
                    break
                try:
                    sp = doc[spn - 1]   # 0-indexed
                    tabs = sp.find_tables()
                    if not (tabs and tabs.tables):
                        continue

                    if cap_y is not None and spn == pn:
                        # Prefer the table whose top edge is nearest (below) the caption
                        best_tab  = None
                        best_dist = float("inf")
                        for tab in tabs.tables:
                            dy = tab.bbox[1] - cap_y   # positive = below caption
                            dist = abs(dy) if dy >= -30 else abs(dy) + 10000
                            if dist < best_dist:
                                best_dist = dist
                                best_tab  = tab
                        if best_tab:
                            rows_data, col_widths = _extract_table(best_tab)
                    else:
                        # Adjacent page: take the first non-empty table
                        for tab in tabs.tables:
                            rows_data, col_widths = _extract_table(tab)
                            if rows_data:
                                break
                except Exception:
                    continue

            # Fallback: parse the text near the caption as tab/space-delimited rows
            if not rows_data:
                idx = page_text.find(cap[:30])
                snippet = page_text[idx: idx + 800] if idx != -1 else cap
                for ln in snippet.splitlines():
                    ln = ln.strip()
                    if not ln:
                        continue
                    # Split on 2+ spaces or tabs (common in PDF text tables)
                    parts = re.split(r'\t|  +', ln)
                    parts = [p.strip() for p in parts if p.strip()]
                    if parts:
                        rows_data.append(parts)

            result["tables"].append({
                "caption":     cap,
                "page":        pn,
                "caption_num": _extract_caption_number(cap),
                "rows":        rows_data,
                "col_widths":  col_widths,   # proportional widths list (may be empty)
                "text":        " | ".join(
                    " | ".join(cell for cell in row)
                    for row in rows_data[:8]
                ),
            })

    # ── Combine full text ─────────────────────────────────────────────────────
    full_text = "\n\n".join(all_text_blocks)
    result["full_text"] = full_text

    # ── Extract title ─────────────────────────────────────────────────────────
    first_page_lines = [l.strip() for l in all_text_blocks[0].splitlines() if l.strip()]
    if first_page_lines:
        result["title"] = first_page_lines[0]
    if len(first_page_lines) > 1:
        result["authors"] = " | ".join(first_page_lines[1:4])

    # ── Extract abstract ──────────────────────────────────────────────────────
    abstract_match = re.search(
        r'(?:Abstract|ABSTRACT)[:\s\n]+(.*?)(?=\n\s*\n|\n[A-Z][A-Za-z\s]+\n)',
        full_text, re.DOTALL | re.IGNORECASE
    )
    if abstract_match:
        result["abstract"] = _clean(abstract_match.group(1))

    doc.close()
    return result
