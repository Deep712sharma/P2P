"""
section_detector.py – Identify and split academic paper sections from raw text.
"""

import re
from typing import OrderedDict

# ─────────────────────────────────────────────────────────────────────────────
# Known section keywords (order matters for priority matching)
# ─────────────────────────────────────────────────────────────────────────────

SECTION_KEYWORDS = [
    "abstract",
    "introduction",
    "related work",
    "background",
    "literature review",
    "problem statement",
    "problem formulation",
    "motivation",
    "proposed method",
    "methodology",
    "method",
    "approach",
    "model",
    "architecture",
    "framework",
    "experimental setup",
    "experiments",
    "experimental results",
    "results",
    "evaluation",
    "discussion",
    "ablation",
    "analysis",
    "conclusion",
    "future work",
    "acknowledgment",
    "acknowledgements",
    "references",
]

# Regex to find numbered or unnumbered headings
HEADING_PATTERN = re.compile(
    r'^\s*(?:(\d+\.?\d*\.?\d*)\s+)?'        # optional numbering like "1.", "2.1"
    r'([A-Z][A-Za-z &/\-]{2,60})'            # heading text
    r'\s*$',
    re.MULTILINE,
)


def _normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip().lower()


def _is_known_heading(line: str) -> str | None:
    """Return canonical section name if line matches a known keyword, else None."""
    norm = _normalize(line)
    for kw in SECTION_KEYWORDS:
        if norm == kw or norm.startswith(kw) or norm.endswith(kw):
            return kw
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Main detector
# ─────────────────────────────────────────────────────────────────────────────

def detect_sections(full_text: str) -> dict[str, str]:
    """
    Split full_text into a dict mapping section_name → section_content.

    Strategy:
      1. Walk lines; detect heading candidates via regex.
      2. If the heading matches a known keyword, start a new section.
      3. Fallback: if no sections found, treat the whole text as "body".
    """
    sections: dict[str, str] = {}
    current_section = "preamble"
    buffer: list[str] = []

    lines = full_text.splitlines()

    for line in lines:
        stripped = line.strip()

        # Try regex heading match first
        m = HEADING_PATTERN.match(stripped)
        if m:
            heading_text = m.group(2).strip()
            canonical = _is_known_heading(heading_text)

            if canonical:
                # Save previous section
                if buffer:
                    prev_content = "\n".join(buffer).strip()
                    if prev_content:
                        # Merge with existing if duplicate key
                        if current_section in sections:
                            sections[current_section] += "\n" + prev_content
                        else:
                            sections[current_section] = prev_content
                buffer = []
                current_section = canonical
                continue  # don't add the heading line itself

        buffer.append(line)

    # Flush last section
    if buffer:
        content = "\n".join(buffer).strip()
        if content:
            if current_section in sections:
                sections[current_section] += "\n" + content
            else:
                sections[current_section] = content

    # If almost nothing was detected, put everything under "body"
    if len(sections) <= 1:
        sections = {"body": full_text}

    # Remove references & acknowledgments (rarely useful in slides)
    for drop in ("references", "acknowledgment", "acknowledgements"):
        sections.pop(drop, None)

    return sections


def get_slide_order(sections: dict[str, str]) -> list[str]:
    """Return section keys in presentation order."""
    priority = [
        "abstract", "introduction", "motivation", "problem statement",
        "problem formulation", "background", "related work", "literature review",
        "proposed method", "methodology", "method", "approach", "model",
        "architecture", "framework", "experimental setup", "experiments",
        "results", "experimental results", "evaluation", "discussion",
        "ablation", "analysis", "conclusion", "future work",
    ]
    ordered = []
    for p in priority:
        if p in sections:
            ordered.append(p)
    # Append any remaining sections not in priority list
    for k in sections:
        if k not in ordered:
            ordered.append(k)
    return ordered
