#!/usr/bin/env python3
"""HTML -> prose-only plain text.

The review corpus is built from HTML parts that mix real prose with page
chrome: a table of research questions, empty layout divs
(``<div class="sectionbar"></div>``), inline citation markers, and scripts.

Feeding table rows to the originality checker produces noise: a cell like
"RQ1 What does agentic AI add" is not a sentence, and it drags the whole row
into the report as a false candidate. This module strips chrome and keeps the
prose, with block boundaries preserved as newlines so paragraphs never merge.

Stdlib only.
"""

from __future__ import annotations

import html
import re

# Tags whose entire content is never prose.
_DROP_CONTENT = ("script", "style", "noscript", "svg", "math")

# Tags that mark a block boundary; their *content* is kept, the tag is not.
_BLOCK = r"(?:p|div|section|article|aside|h[1-6]|li|ul|ol|dl|dt|dd|blockquote|pre|figure|figcaption|header|footer|main|nav|form)"

# Empty layout elements, identified by their class, carry no prose at all.
_CHROME_CLASS = (
    r"sectionbar|section-bar|pagebreak|page-break|spacer|clearfix|rule|"
    r"toc|toc-item|breadcrumb|nav|runninghead|running-head"
)


def clean_html(markup, drop_tables=True):
    """Remove scripts, styles, comments, chrome elements and (optionally) tables."""
    text = re.sub(r"<!--.*?-->", " ", markup, flags=re.S)

    for tag in _DROP_CONTENT:
        text = re.sub(r"<%s\b.*?</%s\s*>" % (tag, tag), " ", text, flags=re.S | re.I)

    # Iteratively remove tables so a nested table is fully cleared: one pass
    # leaves the inner </table>, a second pass then matches the outer element.
    if drop_tables:
        previous = None
        while previous != text:
            previous = text
            text = re.sub(r"<table\b.*?</table\s*>", " ", text, flags=re.S | re.I)
        # Any stray table child tags left by malformed markup.
        text = re.sub(r"</?(?:tr|td|th|thead|tbody|tfoot|caption)\b[^>]*>", " ",
                      text, flags=re.I)

    # Empty chrome elements: <div class="sectionbar"></div>
    text = re.sub(
        r'<(div|span|p)\b[^>]*class\s*=\s*["\'][^"\']*(?:%s)[^"\']*["\'][^>]*>\s*</\1\s*>'
        % _CHROME_CLASS,
        " ",
        text,
        flags=re.I,
    )
    # Chrome elements that are not empty (e.g. a <div class="toc"> list).
    text = re.sub(
        r'<(div|span)\b[^>]*class\s*=\s*["\'][^"\']*(?:%s)[^"\']*["\'][^>]*>.*?</\1\s*>'
        % _CHROME_CLASS,
        " ",
        text,
        flags=re.S | re.I,
    )
    return text


def to_text(markup, drop_tables=True, drop_headings=True):
    """Convert HTML to plain text, preserving paragraph boundaries.

    Block tags become a *blank line* (a paragraph boundary); the source's own
    soft wraps inside a paragraph stay single newlines and are folded to spaces.
    Without that distinction a heading and the paragraph after it would merge
    into one "sentence", because a heading carries no terminal punctuation.

    ``drop_headings`` removes heading content entirely. Headings are handled
    separately (``outline.py`` extracts them from the markup; the sentence
    splitter strips markdown ones), and left inline they become fake
    "sentences" -- "1.1 Primary care as the pressure point in India" carries 10
    word-tokens, so it survives any minimum-length filter.
    """
    markup = clean_html(markup, drop_tables=drop_tables)
    if drop_headings:
        markup = re.sub(r"<h[1-6]\b[^>]*>.*?</h[1-6]\s*>", "\n\n", markup,
                        flags=re.S | re.I)
    markup = re.sub(r"<br\s*/?>", "\n\n", markup, flags=re.I)
    markup = re.sub(r"</%s\s*>" % _BLOCK, "\n\n", markup, flags=re.I)
    markup = re.sub(r"<%s\b[^>]*>" % _BLOCK, "\n\n", markup, flags=re.I)
    markup = re.sub(r"<[^>]+>", " ", markup)
    markup = html.unescape(markup)

    paragraphs = []
    for block in re.split(r"\n\s*\n", markup):
        # Fold the paragraph's internal soft wraps, then collapse whitespace.
        folded = re.sub(r"[ \t\u00a0]*\n[ \t\u00a0]*", " ", block)
        folded = re.sub(r"[ \t\u00a0]+", " ", folded).strip()
        # Tag removal leaves a space before punctuation ("prediction : a").
        folded = re.sub(r" +([,.;:!?])", r"\1", folded)
        if folded:
            paragraphs.append(folded)
    return "\n\n".join(paragraphs)


def is_html(path):
    return path.lower().endswith((".html", ".htm"))
