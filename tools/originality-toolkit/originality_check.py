#!/usr/bin/env python3
"""Self-originality checker: find passages in YOUR draft that overlap published sources.

This is the legitimate half of what a similarity engine does, run on your own
text before you submit: it tells you *which* sentences closely track a real
source, prints the overlapping wording, and links the source so you can quote,
paraphrase-with-attribution, or cite it.

    python3 originality_check.py draft.md --out report.md
    python3 originality_check.py draft.md --sources openalex,crossref,arxiv --threshold 0.30

It does NOT attempt to defeat AI-writing classifiers, and it cannot reproduce
Turnitin's private index -- it checks against open scholarly indexes, which is
where most *accidental* material comes from.

Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from difflib import SequenceMatcher

import htmltext
import sources

STOPWORDS = set("""
a about above after again against all also am an and any are aren't as at be
because been before being below between both but by can cannot could couldn't
did didn't do does doesn't doing don't down during each few for from further
had hadn't has hasn't have haven't having he her here hers herself him himself
his how however i if in into is isn't it its itself just let's me more most
mustn't my myself no nor not of off on once only or other ought our ours
ourselves out over own same shan't she should shouldn't so some such than that
the their theirs them themselves then there these they this those through to
too under until up very was wasn't we were weren't what when where which while
who whom why with won't would wouldn't you your yours yourself yourselves thus
therefore whereas moreover furthermore although though within without upon may
might must shall will can using used use based results study paper research
""".split())

WORD_RE = re.compile(r"[a-z0-9][a-z0-9'\-]*")


def normalise(text):
    """Lowercase, strip markdown/URLs/punctuation -> token list."""
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[*_`#>\[\]\(\)]", " ", text)
    text = text.lower()
    return WORD_RE.findall(text)


def content_tokens(text):
    return [w for w in normalise(text) if w not in STOPWORDS and len(w) > 2]



def split_sentences(text, min_words=8):
    """Split prose into candidate sentences, dropping noise and headings.

    Splitting is paragraph-aware: a blank line is a hard boundary, so a heading
    line never absorbs the sentence that follows it. Within a paragraph, soft
    wraps are folded before sentence segmentation.
    """
    text = re.sub(r"^\s{0,3}#{1,6}.*$", " ", text, flags=re.M)   # markdown headings
    text = re.sub(r"\|.*\|", " ", text)                           # pipe tables
    text = re.sub(r"https?://\S+", " ", text)

    out = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = re.sub(r"\s+", " ", paragraph).strip()
        if not paragraph:
            continue
        for raw in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", paragraph):
            sentence = raw.strip()
            if len(normalise(sentence)) >= min_words:
                out.append(sentence)
    return out


def keyphrase_query(sentence, max_terms=12):
    """Build a search query from the sentence's most distinctive terms.

    Order-insensitive term selection: rare/long terms first, which is what the
    scholarly indexes rank on.
    """
    tokens = content_tokens(sentence)
    seen, ranked = set(), []
    for tok in sorted(tokens, key=lambda w: (-len(w), tokens.index(w))):
        if tok not in seen:
            seen.add(tok)
            ranked.append(tok)
    return " ".join(ranked[:max_terms])


def _tf(tokens):
    counts = {}
    for tok in tokens:
        counts[tok] = counts.get(tok, 0) + 1
    return counts


def cosine(a_tokens, b_tokens):
    """TF cosine similarity over content tokens."""
    a, b = _tf(a_tokens), _tf(b_tokens)
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def longest_common_run(sentence, candidate):
    """Longest verbatim word run shared by sentence and candidate.

    Returns (length_in_words, the matching text). This is what distinguishes
    copying from coincidental topical overlap.
    """
    a, b = normalise(sentence), normalise(candidate)
    if not a or not b:
        return 0, ""
    match = SequenceMatcher(None, a, b, autojunk=False).find_longest_match(
        0, len(a), 0, len(b)
    )
    span = " ".join(a[match.a:match.a + match.size])
    return match.size, span


def score(sentence, candidate):
    """Combine lexical overlap and verbatim run into a 0-1 similarity score."""
    body = "%s. %s" % (candidate.get("title", ""), candidate.get("abstract", ""))
    cos = cosine(content_tokens(sentence), content_tokens(body))
    run_len, span = longest_common_run(sentence, body)
    n_words = max(1, len(normalise(sentence)))
    run_ratio = min(1.0, run_len / float(n_words))
    combined = 0.55 * cos + 0.45 * run_ratio
    return {
        "score": round(combined, 3),
        "cosine": round(cos, 3),
        "run_words": run_len,
        "run_span": span,
        "run_ratio": round(run_ratio, 3),
    }


CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")


def _cache_path(query, source, limit):
    key = hashlib.sha1(("%s|%s|%d" % (query, source, limit)).encode()).hexdigest()
    return os.path.join(CACHE_DIR, "%s.json" % key)


def cached_search(query, source, limit, refresh=False):
    """Search one source with an on-disk cache so re-runs are instant."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(query, source, limit)
    if os.path.exists(path) and not refresh:
        with open(path, "r", encoding="utf-8") as handle:
            blob = json.load(handle)
        return blob["status"], blob["candidates"]
    status, candidates = sources.search(query, source, limit=limit)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"status": status, "candidates": candidates}, handle)
    return status, candidates


def analyse(sentence, source_names, per_source, refresh=False, pause=0.4):
    """Find the best overlapping source for one sentence."""
    query = keyphrase_query(sentence)
    best = None
    statuses = {}
    for source in source_names:
        status, candidates = cached_search(query, source, per_source, refresh=refresh)
        statuses[source] = status
        if status != "ok":
            continue
        for candidate in candidates:
            result = score(sentence, candidate)
            if best is None or result["score"] > best["score"]:
                best = dict(result, candidate=candidate, query=query)
        time.sleep(pause)
    if best is None:
        return None, statuses
    return best, statuses


def verdict(result, threshold, min_run=3):
    """Classify a match.

    ``min_run`` is a noise floor. Cosine overlap on generic phrasing routinely
    clears the score threshold against an *unrelated* record -- a two-word run
    like "already exists" matched a 1983 pharmacy editorial in testing -- so a
    sub-``min_run`` verbatim run is only reported when the topical overlap is
    strong enough to stand on its own (>= 0.55).
    """
    if result is None:
        return "ok"
    if result["run_words"] >= 12 and result["run_ratio"] >= 0.6:
        return "QUOTE + CITE (verbatim)"
    if result["score"] >= 0.55:
        return "PARAPHRASE + CITE"
    if result["score"] >= threshold and result["run_words"] >= min_run:
        return "REVIEW (topical overlap)"
    return "ok"


def _source_ref(candidate):
    bits = [candidate.get("source", "?")]
    if candidate.get("year"):
        bits.append(str(candidate["year"]))
    return " ".join(bits)


def render_report(draft_name, rows, source_names, threshold, statuses):
    checked = len(rows)
    flagged = [r for r in rows if r["verdict"] != "ok"]
    verbatim = [r for r in rows if r["verdict"].startswith("QUOTE")]
    top = max([r["best"]["score"] for r in rows if r["best"]], default=0.0)

    lines = []
    lines.append("# Self-originality report — %s" % draft_name)
    lines.append("")
    lines.append("Sources queried: %s  |  threshold: %.2f" % (", ".join(source_names), threshold))
    lines.append("")
    lines.append("Sentences checked: **%d**  |  flagged: **%d**  |  "
                 "verbatim runs (>=12 words): **%d**  |  highest score: **%.3f**"
                 % (checked, len(flagged), len(verbatim), top))
    lines.append("")
    unavailable = sorted(s for s, st in (statuses or {}).items() if st == "unavailable")
    if unavailable:
        lines.append("> Not reachable this run (results NOT clean for these): %s"
                     % ", ".join(unavailable))
        lines.append("")
    if not flagged:
        lines.append("No passage exceeded the threshold against the open scholarly indexes. "
                     "This does **not** clear you: Turnitin's web and student-paper "
                     "repositories are private and not reachable here.")
        lines.append("")
        return "\n".join(lines)

    lines.append("## Flagged passages")
    lines.append("")
    for index, row in enumerate(flagged, 1):
        best = row["best"]
        cand = best["candidate"]
        lines.append("### %d. %s — score %.3f" % (index, row["verdict"], best["score"]))
        lines.append("")
        lines.append("> %s" % row["sentence"])
        lines.append("")
        lines.append("- **Source:** %s — %s (%s)"
                     % (cand.get("title") or "(untitled)", cand.get("authors") or "n/a",
                        _source_ref(cand)))
        link = cand.get("doi") or cand.get("url")
        if link:
            if not str(link).startswith("http"):
                link = "https://doi.org/" + str(link)
            lines.append("- **Link:** %s" % link)
        lines.append("- **Overlap:** cosine %.3f, longest verbatim run %d words"
                     % (best["cosine"], best["run_words"]))
        if best["run_span"]:
            lines.append("- **Matching wording:** \"%s\"" % best["run_span"])
        lines.append("- **Action:** %s" % _action_text(row["verdict"]))
        lines.append("")

    lines.append("## Score table")
    lines.append("")
    lines.append("| # | score | run | verdict | source |")
    lines.append("|---|-------|-----|---------|--------|")
    for index, row in enumerate(rows, 1):
        best = row["best"]
        if best:
            lines.append("| %d | %.3f | %d | %s | %s |"
                         % (index, best["score"], best["run_words"], row["verdict"],
                            (best["candidate"].get("title") or "")[:48]))
        else:
            lines.append("| %d | - | - | ok | (no candidate) |" % index)
    lines.append("")
    return "\n".join(lines)


def _action_text(verdict):
    if verdict.startswith("QUOTE"):
        return ("This is copied wording. Put it in quotation marks, add an "
                "in-text citation with a locator, or rewrite it in your own words.")
    if verdict.startswith("PARAPHRASE"):
        return ("Close to the source. Rewrite the sentence in your own voice and "
                "cite the idea.")
    if verdict.startswith("REVIEW"):
        return ("Topical overlap only. Check whether a citation is warranted; "
                "common phrasing needs nothing.")
    return "No action."


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("draft", help="path to the draft (.txt/.md)")
    parser.add_argument("--sources", default="openalex,crossref,arxiv,europepmc",
                        help="comma-separated: openalex,crossref,arxiv,europepmc,semantic")
    parser.add_argument("--per-source", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=0.35)
    parser.add_argument("--min-run", type=int, default=3,
                        help="noise floor: verbatim words required for a REVIEW flag")
    parser.add_argument("--keep-tables", action="store_true",
                        help="do not drop <table> content from HTML drafts")
    parser.add_argument("--min-words", type=int, default=8)
    parser.add_argument("--out", default=None, help="write markdown report here")
    parser.add_argument("--json", dest="json_out", default=None,
                        help="write machine-readable results here (consumed by cite_fix.py)")
    parser.add_argument("--refresh", action="store_true", help="ignore cache")
    args = parser.parse_args(argv)

    source_names = [s.strip() for s in args.sources.split(",") if s.strip()]
    with open(args.draft, "r", encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    if htmltext.is_html(args.draft):
        # Read the HTML source directly; strip chrome and tables so only prose
        # reaches the sentence splitter.
        text = htmltext.to_text(text, drop_tables=not args.keep_tables)

    sentences = split_sentences(text, min_words=args.min_words)
    rows, seen_statuses = [], {}
    for index, sentence in enumerate(sentences, 1):
        sys.stderr.write("\r[%d/%d] %s..." % (index, len(sentences), sentence[:60]))
        sys.stderr.flush()
        best, statuses = analyse(sentence, source_names, args.per_source,
                                refresh=args.refresh)
        seen_statuses.update(statuses)
        rows.append({"sentence": sentence, "best": best,
                     "verdict": verdict(best, args.threshold, args.min_run)})
    sys.stderr.write("\r" + " " * 90 + "\r")

    report = render_report(os.path.basename(args.draft), rows, source_names,
                           args.threshold, seen_statuses)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(report)
        print("Report written to %s" % args.out)
    else:
        print(report)

    flagged = sum(1 for r in rows if r["verdict"] != "ok")
    print("Checked %d sentences; %d flagged." % (len(rows), flagged), file=sys.stderr)

    if args.json_out:
        payload = {
            "draft": os.path.basename(args.draft),
            "threshold": args.threshold,
            "sources": source_names,
            "sources_unavailable": sorted(
                s for s, st in seen_statuses.items() if st == "unavailable"
            ),
            "results": [
                {
                    "index": i,
                    "sentence": row["sentence"],
                    "verdict": row["verdict"],
                    "score": row["best"]["score"] if row["best"] else None,
                    "run_words": row["best"]["run_words"] if row["best"] else 0,
                    "run_span": row["best"]["run_span"] if row["best"] else "",
                    "source": row["best"]["candidate"] if row["best"] else None,
                }
                for i, row in enumerate(rows, 1)
            ],
        }
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        print("JSON written to %s" % args.json_out, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


