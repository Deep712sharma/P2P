"""
summarizer.py – Use Groq to:
  1. Generate a structured JSON slide plan (which sections → which slide, which
     figures/tables to attach to each slide, slide type, layout hints).
  2. Fallback per-section bullet summarization.

Model: llama-3.3-70b-versatile (free via Groq)
"""

import os
import re
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

DEFAULT_MODEL = "llama-3.3-70b-versatile"
FALLBACK_MODEL = "llama-3.1-8b-instant"

def _call_groq_with_fallback(messages, model, temperature, max_tokens):
    try:
        return client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
    except Exception as e:
        if "429" in str(e) or "rate limit" in str(e).lower():
            print(f"[summarizer] Rate limit on {model}, falling back to {FALLBACK_MODEL}")
            return client.chat.completions.create(
                model=FALLBACK_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
        raise e

# ─────────────────────────────────────────────────────────────────────────────
# Prompt templates
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert academic presenter.
Your task is to convert a section of a research paper into detailed, slide-ready bullet points.

Rules:
- Generate detailed bullet points covering the core concepts comprehensively.
- Keep sentences clear and professional, avoiding excessive jargon.
- Preserve critical technical terms, numbers, and model names.
- If the section references a specific figure or table, explicitly mention it in your text (e.g. "As shown in Figure 1...").
- Do NOT include the section heading in your output.
- Output ONLY the bullet points, one per line, each starting with "•".
"""

TITLE_SLIDE_PROMPT = """You are an expert academic presenter.
Given the title, authors, and abstract of a research paper, generate:
1. A short subtitle (≤ 12 words) that captures the paper's core contribution.
2. A one-sentence motivation (≤ 20 words).

Output format (exactly):
SUBTITLE: <text>
MOTIVATION: <text>
"""

SLIDE_PLAN_SYSTEM = """You are an expert academic presentation designer.
Given structured information about a research paper (sections, figures, tables),
produce a complete JSON slide plan.

Each slide in the plan must be a JSON object with these fields:
  - "slide_type": one of "title" | "content" | "split" | "figure" | "table" | "thankyou"
      * "content"  = full-width bullet list
      * "split"    = left bullets + right figure (use when a figure belongs to this section)
      * "figure"   = full-slide figure with caption
      * "table"    = slide showing a table summary
  - "title": slide heading string (≤ 8 words)
  - "section_key": which section this slide summarises (e.g. "methodology")
  - "bullets": list of detailed bullet strings containing proper content (do not artificially limit the length or count), empty [] for figure/table slides
  - "figure_num": figure number (int) to embed, or null
  - "table_num": table number (int) to embed, or null
  - "layout_hint": one of "default" | "emphasis" | "two_col" | "centered"
  - "font_scale": one of "large" | "normal" | "small"
      * large  → few bullets, want big text (≤ 3 bullets)
      * small  → many details, need smaller text (5+ bullets)
      * normal → standard

Rules:
- Always start with a "title" slide and end with a "thankyou" slide.
- For sections with a relevant figure, prefer "split" layout so text and figure appear side by side.
- Do NOT put a figure on a "content" slide if the figure is better on its own "figure" slide.
- Skip References and Acknowledgments.
- Return ONLY a valid JSON array, no markdown fences, no commentary.
"""


def _truncate(text: str, max_chars: int = 3500) -> str:
    return text[:max_chars] if len(text) > max_chars else text


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def summarize_section(section_name: str, section_text: str,
                      model: str = DEFAULT_MODEL) -> list[str]:
    """Fallback: summarize a single section into bullet strings."""
    truncated = _truncate(section_text)
    user_msg = f"Section: {section_name.title()}\n\n{truncated}"

    response = _call_groq_with_fallback(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.4,
        max_tokens=512,
    )

    raw = response.choices[0].message.content or ""
    bullets = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("•"):
            bullets.append(line[1:].strip())
        elif line.startswith("-") or line.startswith("*"):
            bullets.append(line[1:].strip())
        elif line:
            bullets.append(line)

    return bullets[:6]


def summarize_title_slide(title: str, authors: str, abstract: str,
                          model: str = DEFAULT_MODEL) -> dict:
    """Generate subtitle and motivation for the title slide."""
    user_msg = f"Title: {title}\nAuthors: {authors}\nAbstract: {_truncate(abstract, 1500)}"

    response = _call_groq_with_fallback(
        model=model,
        messages=[
            {"role": "system", "content": TITLE_SLIDE_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.3,
        max_tokens=200,
    )

    raw = response.choices[0].message.content or ""
    result = {"subtitle": "", "motivation": ""}
    for line in raw.splitlines():
        if line.startswith("SUBTITLE:"):
            result["subtitle"] = line.replace("SUBTITLE:", "").strip()
        elif line.startswith("MOTIVATION:"):
            result["motivation"] = line.replace("MOTIVATION:", "").strip()

    return result


def build_intelligent_slide_plan(
    title: str,
    authors: str,
    abstract: str,
    sections: dict[str, str],
    figure_captions: list[str],
    table_captions: list[str],
    model: str = DEFAULT_MODEL,
) -> list[dict] | None:
    """
    Ask the LLM to produce a complete structured slide plan as JSON.
    Returns a list of slide dicts, or None on failure.
    """
    # Build a compact paper summary for the prompt
    section_summaries = []
    for name, text in sections.items():
        snippet = _truncate(text, 600)
        section_summaries.append(f"[{name.upper()}]\n{snippet}")

    fig_list  = "\n".join(f"  Figure {i+1}: {c}" for i, c in enumerate(figure_captions)) or "  None"
    tab_list  = "\n".join(f"  Table {i+1}: {c}"  for i, c in enumerate(table_captions))  or "  None"

    user_msg = f"""PAPER TITLE: {title}
AUTHORS: {authors}
ABSTRACT: {_truncate(abstract, 800)}

SECTIONS:
{'---'.join(section_summaries[:8])}

FIGURES AVAILABLE:
{fig_list}

TABLES AVAILABLE:
{tab_list}

Now produce the JSON slide plan array. Remember: return ONLY the JSON array.
"""

    try:
        response = _call_groq_with_fallback(
            model=model,
            messages=[
                {"role": "system", "content": SLIDE_PLAN_SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=3000,
        )
        raw = response.choices[0].message.content or ""

        # Strip any accidental markdown fences
        raw = re.sub(r"^```[a-z]*\n?", "", raw.strip(), flags=re.IGNORECASE)
        raw = re.sub(r"\n?```$", "", raw.strip())

        return json.loads(raw)
    except Exception as e:
        print(f"[summarizer] LLM slide plan failed: {e}")
        return None


def summarize_all_sections(
    sections: dict[str, str],
    title: str = "",
    authors: str = "",
    abstract: str = "",
    model: str = DEFAULT_MODEL,
) -> dict:
    """
    Fallback path: summarize every section individually.

    Returns:
        {
          "title_slide": {"subtitle": str, "motivation": str},
          "sections": { section_name: [bullet, ...] }
        }
    """
    output = {
        "title_slide": summarize_title_slide(title, authors, abstract, model),
        "sections": {},
    }

    for name, text in sections.items():
        if not text.strip():
            continue
        try:
            bullets = summarize_section(name, text, model)
            output["sections"][name] = bullets
        except Exception as e:
            output["sections"][name] = [f"[Error summarizing section: {e}]"]

    return output
