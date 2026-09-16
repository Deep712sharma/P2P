"""
slide_planner.py – Build the final ordered slide plan.

Priority path: ask Groq to produce a structured JSON plan that decides:
  - which section goes on which slide
  - which figures/tables attach to which slide
  - slide layout (content / split / figure / table / title / thankyou)
  - font_scale hint (large / normal / small)

Fallback path: use legacy heuristic ordering if the LLM call fails.
"""

from section_detector import get_slide_order
from summarizer import build_intelligent_slide_plan, summarize_all_sections

# ─────────────────────────────────────────────────────────────────────────────
# Section → human-readable slide title
# ─────────────────────────────────────────────────────────────────────────────

SECTION_TO_SLIDE_TITLE = {
    "abstract":              "Overview",
    "introduction":          "Introduction",
    "motivation":            "Motivation",
    "problem statement":     "Problem Statement",
    "problem formulation":   "Problem Formulation",
    "background":            "Background",
    "related work":          "Related Work",
    "literature review":     "Literature Review",
    "proposed method":       "Proposed Method",
    "methodology":           "Methodology",
    "method":                "Method",
    "approach":              "Our Approach",
    "model":                 "Model",
    "architecture":          "Architecture",
    "framework":             "Framework",
    "experimental setup":    "Experimental Setup",
    "experiments":           "Experiments",
    "results":               "Results",
    "experimental results":  "Experimental Results",
    "evaluation":            "Evaluation",
    "discussion":            "Discussion",
    "ablation":              "Ablation Study",
    "analysis":              "Analysis",
    "conclusion":            "Conclusion",
    "future work":           "Future Work",
    "body":                  "Key Points",
    "preamble":              "Highlights",
}

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _normalise_slide(raw: dict, images: list[dict], tables: list[dict]) -> dict | None:
    """
    Take one raw slide dict from the LLM plan and resolve figure_num / table_num
    to actual file paths. Return None if slide type is unknown.
    """
    stype = raw.get("slide_type", "content")
    allowed = {"title", "content", "split", "figure", "table", "thankyou"}
    if stype not in allowed:
        stype = "content"

    # Resolve figure
    image_path = None
    caption = ""
    fig_num = raw.get("figure_num")
    if fig_num is not None:
        # find by caption_num first, then by index
        for img in images:
            if img.get("caption_num") == fig_num:
                image_path = img["path"]
                caption    = img.get("caption", "")
                break
        if not image_path and len(images) >= fig_num:
            img = images[fig_num - 1]
            image_path = img["path"]
            caption    = img.get("caption", "")

    # Resolve table
    table_rows    = []
    table_text    = ""
    table_caption = ""
    col_widths     = []
    tab_num = raw.get("table_num")
    if tab_num is not None:
        matched_tbl = None
        for tbl in tables:
            if tbl.get("caption_num") == tab_num:
                matched_tbl = tbl
                break
        if not matched_tbl and len(tables) >= tab_num:
            matched_tbl = tables[tab_num - 1]
        if matched_tbl:
            table_rows    = matched_tbl.get("rows", [])
            table_text    = matched_tbl.get("text", "")
            table_caption = matched_tbl.get("caption", "")
            col_widths     = matched_tbl.get("col_widths", [])

    # If split type but no image found, degrade to content
    if stype == "split" and not image_path:
        stype = "content"

    # If figure type but no image found, skip slide
    if stype == "figure" and not image_path:
        return None

    return {
        "type":          stype,
        "title":         raw.get("title", "Slide"),
        "subtitle":      raw.get("subtitle", ""),
        "motivation":    raw.get("motivation", ""),
        "authors":       raw.get("authors", ""),
        "bullets":       raw.get("bullets", []),
        "image_path":    image_path,
        "caption":       caption,
        "table_rows":    table_rows,
        "col_widths":    col_widths,
        "table_text":    table_text,
        "table_caption": table_caption,
        "section":       raw.get("section_key", ""),
        "layout_hint":   raw.get("layout_hint", "default"),
        "font_scale":    raw.get("font_scale", "normal"),
    }


def _fallback_plan(
    title: str,
    authors: str,
    summarized: dict,
    sections: dict[str, str],
    images: list[dict],
    tables: list[dict],
) -> list[dict]:
    """Legacy heuristic plan when LLM plan fails."""
    slides: list[dict] = []

    title_info = summarized.get("title_slide", {})
    slides.append({
        "type": "title",
        "title": title,
        "subtitle": title_info.get("subtitle", ""),
        "motivation": title_info.get("motivation", ""),
        "authors": authors,
        "bullets": [],
        "image_path": None,
        "caption": "",
        "table_text": "",
        "table_caption": "",
        "section": "title",
        "layout_hint": "default",
        "font_scale": "large",
    })

    ordered_keys = get_slide_order(sections)
    section_summaries = summarized.get("sections", {})

    # Track which images have been used
    used_image_pages: set[int] = set()

    for section_key in ordered_keys:
        bullets = section_summaries.get(section_key, [])
        if not bullets:
            continue

        slide_title = SECTION_TO_SLIDE_TITLE.get(section_key, section_key.title())

        # Check if any image page roughly aligns with this section
        # (heuristic: later sections → later pages)
        section_idx  = ordered_keys.index(section_key)
        total_secs   = len(ordered_keys)
        total_pages  = max(img["page"] for img in images) if images else 1
        section_page_approx = int((section_idx / max(total_secs, 1)) * total_pages) + 1

        matched_img = None
        for img in images:
            if img["page"] not in used_image_pages:
                # prefer images near the section's approximate page
                if abs(img["page"] - section_page_approx) <= 3:
                    matched_img = img
                    used_image_pages.add(img["page"])
                    break

        if matched_img:
            slide_type = "split"
            image_path = matched_img["path"]
            caption    = matched_img.get("caption", "")
        else:
            slide_type = "content"
            image_path = None
            caption    = ""

        n = len(bullets)
        font_scale = "large" if n <= 3 else ("small" if n >= 5 else "normal")

        slides.append({
            "type":         slide_type,
            "title":        slide_title,
            "subtitle":     "",
            "motivation":   "",
            "authors":      "",
            "bullets":      bullets,
            "image_path":   image_path,
            "caption":      caption,
            "table_text":   "",
            "table_caption": "",
            "section":      section_key,
            "layout_hint":  "default",
            "font_scale":   font_scale,
        })

    # Remaining images as standalone figure slides
    for img in images:
        if img["page"] not in used_image_pages:
            slides.append({
                "type":         "figure",
                "title":        "Key Figure",
                "subtitle":     "",
                "motivation":   "",
                "authors":      "",
                "bullets":      [],
                "image_path":   img["path"],
                "caption":      img.get("caption", ""),
                "table_text":   "",
                "table_caption": "",
                "section":      "figures",
                "layout_hint":  "centered",
                "font_scale":   "normal",
            })

    # Table slides
    for tbl in tables:
        slides.append({
            "type":          "table",
            "title":         tbl.get("caption", "Table"),
            "subtitle":      "",
            "motivation":    "",
            "authors":       "",
            "bullets":       [],
            "image_path":    None,
            "caption":       "",
            "table_rows":    tbl.get("rows", []),
            "col_widths":    tbl.get("col_widths", []),
            "table_text":    tbl.get("text", ""),
            "table_caption": tbl.get("caption", ""),
            "section":       "tables",
            "layout_hint":   "default",
            "font_scale":    "small",
        })

    # Thank You
    slides.append({
        "type": "thankyou",
        "title": "Thank You",
        "subtitle": "Questions & Discussion",
        "motivation": "",
        "authors": authors,
        "bullets": [],
        "image_path": None,
        "caption": "",
        "table_text": "",
        "table_caption": "",
        "section": "end",
        "layout_hint": "centered",
        "font_scale": "large",
    })

    return slides


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def build_slide_plan(
    title: str,
    authors: str,
    summarized: dict,
    sections: dict[str, str],
    images: list[dict],
    tables: list[dict] = None,
    figure_captions: list[str] = None,
    table_captions: list[str] = None,
) -> list[dict]:
    """
    Build the ordered slide plan.

    Tries the LLM-based intelligent plan first; falls back to heuristic.

    Each slide descriptor:
        {
          "type":          "title" | "content" | "split" | "figure" | "table" | "thankyou"
          "title":         str,
          "subtitle":      str,
          "motivation":    str,
          "authors":       str,
          "bullets":       [str],
          "image_path":    str | None,
          "caption":       str,
          "table_text":    str,
          "table_caption": str,
          "section":       str,
          "layout_hint":   str,
          "font_scale":    "large" | "normal" | "small",
        }
    """
    tables         = tables         or []
    figure_captions = figure_captions or []
    table_captions  = table_captions  or []

    # ── Try intelligent LLM plan ──────────────────────────────────────────────
    raw_plan = build_intelligent_slide_plan(
        title=title,
        authors=authors,
        abstract=summarized.get("title_slide", {}).get("motivation", ""),
        sections=sections,
        figure_captions=figure_captions,
        table_captions=table_captions,
    )

    if raw_plan and isinstance(raw_plan, list) and len(raw_plan) >= 3:
        slides: list[dict] = []
        used_images = set()
        used_tables = set()

        # Inject author info into title/thankyou slides from LLM output
        for raw in raw_plan:
            if raw.get("slide_type") == "title":
                raw["authors"] = authors
                ti = summarized.get("title_slide", {})
                raw.setdefault("subtitle",   ti.get("subtitle", ""))
                raw.setdefault("motivation", ti.get("motivation", ""))

            if raw.get("slide_type") == "thankyou":
                raw["authors"] = authors

            slide = _normalise_slide(raw, images, tables)
            if slide:
                slides.append(slide)
                if slide.get("image_path"):
                    used_images.add(slide["image_path"])
                if slide.get("table_text") or slide.get("table_caption"):
                    used_tables.add(slide.get("table_caption") or slide.get("table_text"))

        if slides:
            # Ensure ALL unused images are appended as figure slides before the thankyou slide
            unused_images = [img for img in images if img["path"] not in used_images]
            unused_tables = [tbl for tbl in tables if (tbl.get("caption") or tbl.get("text")) not in used_tables]
            
            # Remove thankyou slide temporarily to append before it
            thankyou_slide = None
            if slides and slides[-1]["type"] == "thankyou":
                thankyou_slide = slides.pop()
                
            for img in unused_images:
                slides.append({
                    "type":         "figure",
                    "title":        "Supplementary Figure",
                    "subtitle":     "",
                    "motivation":   "",
                    "authors":      "",
                    "bullets":      [],
                    "image_path":   img["path"],
                    "caption":      img.get("caption", ""),
                    "table_text":   "",
                    "table_caption": "",
                    "section":      "figures",
                    "layout_hint":  "centered",
                    "font_scale":   "normal",
                })
                
            for tbl in unused_tables:
                slides.append({
                    "type":          "table",
                    "title":         tbl.get("caption", "Table"),
                    "subtitle":      "",
                    "motivation":    "",
                    "authors":       "",
                    "bullets":       [],
                    "image_path":    None,
                    "caption":       "",
                    "table_rows":    tbl.get("rows", []),
                    "col_widths":    tbl.get("col_widths", []),
                    "table_text":    tbl.get("text", ""),
                    "table_caption": tbl.get("caption", ""),
                    "section":       "tables",
                    "layout_hint":   "default",
                    "font_scale":    "small",
                })
                
            if thankyou_slide:
                slides.append(thankyou_slide)

            return slides

    # ── Fallback ──────────────────────────────────────────────────────────────
    print("[slide_planner] Falling back to heuristic plan.")
    return _fallback_plan(title, authors, summarized, sections, images, tables)
