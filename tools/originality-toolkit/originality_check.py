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
import importlib.util
import json
import os
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

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


# Straight and curly quotes. ORI Guideline 2: any verbatim text taken from
# another source must be enclosed in quotation marks. A quoted, cited passage is
# correct practice; the same words unquoted are plagiarism. The scorer used to
# treat both identically.
_QUOTED_RE = re.compile(r'[“"]([^”"]{10,}?)[”"]' + r"|'([^']{10,}?)'")


def quoted_run(sentence, candidate):
    """Longest verbatim run that sits INSIDE quotation marks in the draft."""
    best = 0
    for match in _QUOTED_RE.finditer(sentence or ""):
        inner = match.group(1) or match.group(2) or ""
        run, _ = longest_common_run(inner, candidate)
        if run > best:
            best = run
    return best


def is_violation(verdict_text):
    """Quoted verbatim is correct practice, not a violation (ORI Guideline 2)."""
    return verdict_text != "ok" and not verdict_text.startswith("QUOTED")


# Function words carry the syntactic frame. ORI Guideline 4 requires a paraphrase
# to use its own STRUCTURE, not merely its own words: swapping every content word
# while keeping the frame ("whether X are able to Y") is still plagiarism. The
# lexical score cannot see that -- it finds almost no shared content words -- but
# the function-word sequence survives the substitution.
_FUNCTION_WORDS = frozenset("""
a an the this that these those and or but nor so yet for of in on at by with from to
into during after before while when where which who whom whose if whether than then
as is are was were be been being am do does did done have has had having will would
shall should can could may might must not no there here it its their his her our your
my we they he she you i them us him one such other more most much many few all both
each every any some only own same very also however therefore thus hence although
because since unless until about above below between among within without across
""".split())


def structure_similarity(sentence, candidate):
    """Similarity of the two function-word FRAMES (order-sensitive).

    REPORTED FOR INFORMATION ONLY -- it does NOT drive any verdict, deliberately.

    ORI Guideline 4 requires a paraphrase to use its own syntactical structure,
    not merely its own words, so a swap that keeps the frame ("whether X are able
    to Y") is still plagiarism while scoring near zero on lexical overlap.

    Measured on a labelled corpus (benchmarks/frame_corpus/, 108 machine-generated
    frame copies against 116 negatives; benchmarks/bench_frame_copy.py):

      * this whole-candidate ratio does not separate: AUC 0.655, and at a 5%
        false-positive cap it reaches only 15.7% sensitivity;
      * a best-window ratio and a content-slot agreement measure DO separate
        frame copies from unrelated text (AUC 0.982 and 1.000), but they also fire
        on a preprint against its own published version (false-positive floors
        37.1% and 19.0%): a legitimate same-work revision keeps the frame too.

    No structural measure reached the pre-registered bar (>=90% sensitivity at
    <=5% FPR with a lower confidence bound >=80%) over all three negative classes,
    so no structural threshold exists to wire. The number stays reported, the
    limitation is disclosed in every clean report, and frame-copying remains a
    KNOWN LIMITATION rather than a verdict.
    """
    def frame(text):
        return [w for w in normalise(text) if w in _FUNCTION_WORDS]

    a, b = frame(sentence), frame(candidate)
    if len(a) < 3 or len(b) < 3:
        return 0.0
    return round(SequenceMatcher(None, a, b, autojunk=False).ratio(), 3)


def score(sentence, candidate):
    """Combine lexical overlap and verbatim run into a 0-1 similarity score."""
    body = "%s. %s" % (candidate.get("title", ""), candidate.get("abstract", ""))
    cos = cosine(content_tokens(sentence), content_tokens(body))
    run_len, span = longest_common_run(sentence, body)
    n_words = max(1, len(normalise(sentence)))
    run_ratio = min(1.0, run_len / float(n_words))
    combined = 0.55 * cos + 0.45 * run_ratio
    q_run = quoted_run(sentence, body)
    return {
        "score": round(combined, 3),
        "cosine": round(cos, 3),
        "run_words": run_len,
        "run_span": span,
        "run_ratio": round(run_ratio, 3),
        # True when the whole overlapping run is inside quotation marks.
        "quoted": bool(q_run >= 3 and q_run >= run_len),
        "quoted_run": q_run,
        # Syntactic-frame overlap (ORI Guideline 4). Reported, not yet decisive.
        "structure": round(structure_similarity(sentence, body), 3),
    }


CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")


def _cache_path(query, source, limit):
    key = hashlib.sha1(("%s|%s|%d" % (query, source, limit)).encode()).hexdigest()
    return os.path.join(CACHE_DIR, "%s.json" % key)


def cached_search(query, source, limit, refresh=False):
    """Search one source with an on-disk cache so re-runs are instant."""
    if source == "local":
        # The corpus is already in memory and does not vary by query; a
        # query-keyed cache could only serve a stale corpus.
        return sources.search(query, source, limit=limit)
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
    # Quoted verbatim is the correct way to reuse another author's words (ORI
    # Guideline 2). It is surfaced so the citation can be checked, but it is not
    # a plagiarism finding -- reporting it as one was a false alarm on correct
    # practice.
    if result.get("quoted") and result["run_words"] >= max(min_run, 3):
        return "QUOTED (verbatim; verify the citation)"
    if result["run_words"] >= 12 and result["run_ratio"] >= 0.6:
        return "QUOTE + CITE (verbatim)"
    if result["score"] >= 0.55:
        return "PARAPHRASE + CITE"
    if result["score"] >= threshold and result["run_words"] >= min_run:
        return "REVIEW (topical overlap)"
    return "ok"


def _source_ref(candidate):
    if candidate.get("source") == "local":
        return "local file %s" % (candidate.get("id") or "")
    bits = [candidate.get("source", "?")]
    if candidate.get("year"):
        bits.append(str(candidate["year"]))
    return " ".join(bits)


# ---------------------------------------------------------------------------
# ORI Guideline 4 disclosure, and the guard on every generated report.
# ---------------------------------------------------------------------------
# The measured constants come from benchmarks/bench_frame_copy.py over the frozen
# corpus in benchmarks/frame_corpus/ (108 machine-generated frame copies; 116
# negatives: 54 unrelated real documents, 8 ORI-labelled correct paraphrases, 54
# preprint-vs-own-published revisions). No measure met the pre-registered bar, so
# no threshold is wired and every clean report says so.
STRUCTURAL_MARKER = "Structural coverage (ORI Guideline 4)"
STRUCTURAL_COVERAGE = (
    "%s: **{sentences}** sentence(s) were compared against {scope}. Frame-copying "
    "-- a rewrite that swaps every content word but keeps the function-word frame "
    "-- is **not covered above the measured separation**: on the frozen 108-case "
    "frame-copy benchmark, against 116 negatives (54 unrelated documents, 8 "
    "ORI-labelled correct paraphrases, 54 preprint-vs-own-published revisions), no "
    "structural measure reached the pre-registered bar of 90%% sensitivity at "
    "<=5%% false positives (best AUC 0.905, false-positive floor 19.0%%), because a "
    "legitimate same-work revision keeps the frame too. No structural threshold is "
    "therefore wired, so this report does not cover a structure-preserving rewrite: "
    "a clean result here is a known limitation, not a clearance." % STRUCTURAL_MARKER
)

# Claims no bounded measurement supports. Kept in step with tools/claim_guard.py;
# this copy exists so the deployed toolkit, which ships without tools/, still
# refuses them.
_REPORT_FORBIDDEN = [
    (re.compile(p, re.I), why) for p, why in (
        (r"plagiari[sz]m[\s-]?free", "plagiarism-free is a universal negative"),
        (r"\berror[\s-]?free\b", "state the measured error rate"),
        (r"\bperfect(?:ly)?\b", "state the measured result, not a judgement"),
        (r"\bmedical[\s-]?grade\b", "regulatory status is not a code property"),
        (r"\bcertified?\b", "nothing here certifies"),
        (r"\bclearance\b", "a clean report is not a clearance"),
        (r"\bguarantee[ds]?\b", "a guarantee needs a bound and a population"),
        (r"\bflawless\b", "state the measured result"),
        (r"\bbulletproof\b", "state the measured result"),
        (r"\b100%\s*(?:accurate|correct|reliable)\b", "give the n and the CI"),
    )
]
_REPORT_NEGATION = re.compile(
    r"(?i)\b(?:not|no|never|without|cannot|can't|isn't|aren't|doesn't)\b[^.]{0,24}$")


def structural_coverage_line(sentences, corpus_size=None, source_names=None):
    """The bound every clean report must carry (ORI Guideline 4 disclosure)."""
    if corpus_size is not None:
        scope = "**%d** local-corpus document(s)" % corpus_size
    elif source_names:
        scope = "%d configured source(s)" % len(list(source_names))
    else:
        scope = "the configured sources"
    return STRUCTURAL_COVERAGE.format(sentences=sentences, scope=scope)


def _load_claim_guard():
    """Load tools/claim_guard.py when the toolkit sits inside the repository."""
    for candidate in (Path(__file__).resolve().parent / "claim_guard.py",
                      Path(__file__).resolve().parent.parent / "claim_guard.py"):
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location("claim_guard", candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    return None


def guard_report(report, clean):
    """Return the reasons a generated report must not be emitted.

    Two independent properties:
      1. it never contains an absolute claim ("plagiarism-free", "clearance",
         "guaranteed", ...), and
      2. a clean result carries its bound -- the ORI Guideline 4 coverage line.
    The full repository gate (tools/claim_guard.py) runs when it is reachable;
    the local copy covers the deployed toolkit, which ships without tools/.
    """
    problems = []
    if clean and STRUCTURAL_MARKER not in report:
        problems.append("clean report carries no bound: the structural-coverage "
                        "line is missing")
    for pattern, why in _REPORT_FORBIDDEN:
        match = pattern.search(report)
        if match and not _REPORT_NEGATION.search(report[max(0, match.start() - 30):
                                                 match.start()]):
            problems.append("forbidden claim %r (%s)" % (match.group(0), why))
    module = _load_claim_guard()
    if module is not None:
        for finding in module.scan(report, where="<generated report>"):
            problems.append("%s: %s" % (finding["kind"], finding["message"]))
    return problems


def render_report(draft_name, rows, source_names, threshold, statuses,
                  corpus_size=None, corpus_gaps=None, corpus_path=None):
    checked = len(rows)
    flagged = [r for r in rows if r["verdict"] != "ok"]
    violations = [r for r in flagged if is_violation(r["verdict"])]
    quoted = [r for r in flagged if r["verdict"].startswith("QUOTED")]
    verbatim = [r for r in rows if r["verdict"].startswith("QUOTE")]
    top = max([r["best"]["score"] for r in rows if r["best"]], default=0.0)
    gaps = list(corpus_gaps or [])
    # A corpus that loaded nothing at all cannot produce a measurement. Printing
    # "highest score: 0.000" and "no passage exceeded the threshold" over it is the failure
    # this whole report is supposed to avoid: a true statement about the inputs presented in
    # the shape of a result about the draft.
    corpus_empty = corpus_size == 0

    lines = []
    lines.append("# Self-originality report — %s" % draft_name)
    lines.append("")
    lines.append("Sources queried: %s  |  threshold: %.2f" % (", ".join(source_names), threshold))
    lines.append("")
    if corpus_empty:
        lines.append("Sentences checked: **%d**  |  **NO CORPUS WAS READ** — the local corpus "
                     "figures below cannot be determined." % checked)
        lines.append("")
    else:
        lines.append("Sentences checked: **%d**  |  violations: **%d**  |  "
                     "quoted verbatim (OK if cited): **%d**  |  "
                     "verbatim runs (>=12 words): **%d**  |  highest score: **%.3f**"
                     % (checked, len(violations), len(quoted), len(verbatim), top))
        lines.append("")
    if gaps:
        lines.append("## Corpus not fully read — INPUT GAP, not a result")
        lines.append("")
        lines.append("The local corpus was **not** fully read, so the overlap figures above do "
                     "**not** cover it. These files were not compared against the draft:")
        lines.append("")
        for gap in gaps:
            lines.append("- `%s` — %s" % (gap["file"], gap["reason"]))
        lines.append("")
        lines.append("Action: make these files readable (or remove them from the corpus) and "
                     "re-run. A clean report over a corpus that was not read is not a clean "
                     "report. Re-check only these files with `--recheck <previous --json output>`.")
        lines.append("")
    unavailable = sorted(s for s, st in (statuses or {}).items() if st == "unavailable")
    if unavailable:
        lines.append("> Not reachable this run (results NOT clean for these): %s"
                     % ", ".join(unavailable))
        lines.append("")
    # The structural bound is part of EVERY report, flagged or clean. A reader of a
    # violations table must see, in the same document, that ORI Guideline 4 is not
    # covered -- otherwise a report with zero violations reads as more than it is.
    lines.append("## %s" % STRUCTURAL_MARKER)
    lines.append("")
    lines.append(structural_coverage_line(checked, corpus_size, source_names))
    lines.append("")
    if not flagged:
        if corpus_empty:
            lines.append("**Cannot determine.** No passage could be compared against the local "
                         "corpus because no document in it could be read%s. This is not a "
                         "clean result and not a finding about the draft — nothing was checked."
                         % (" (%s)" % corpus_path if corpus_path else ""))
        else:
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
            link = str(link)
            if not link.startswith(("http", "file://")):
                link = "https://doi.org/" + link
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


def _self_test():
    """Offline assertions for the corpus-gap routing.

    The defect this guards: an unreadable corpus file was written to stderr and nowhere else.
    The report and the JSON carried no trace of it, and the run exited 0 -- so a reader, or an
    agent using --out where stderr is discarded, saw "highest score 0.890" over a corpus three
    of whose four files had never been read. No network is touched.
    """
    import tempfile

    problems = []
    # (a) the two whole-corpus warnings are "condition: path", not "file: reason"
    gap = _corpus_gap("corpus path does not exist: /tmp/nope")
    if gap["file"] != "/tmp/nope" or gap["reason"] != "the corpus path does not exist":
        problems.append("missing-path gap parsed backwards: %r" % gap)
    gap = _corpus_gap("corpus contains no files: /tmp/empty")
    if gap["file"] != "/tmp/empty":
        problems.append("no-files gap parsed backwards: %r" % gap)
    gap = _corpus_gap("/tmp/a.txt: Permission denied")
    if gap["file"] != "/tmp/a.txt" or gap["reason"] != "Permission denied":
        problems.append("per-file gap parsed wrong: %r" % gap)
    if not all(_corpus_gap(w).get("action") for w in
               ("corpus path does not exist: /x", "corpus contains no files: /x", "/x: bad")):
        problems.append("a gap carries no action")

    with tempfile.TemporaryDirectory() as tmp:
        good = os.path.join(tmp, "good.txt")
        with open(good, "w", encoding="utf-8") as fh:
            fh.write("A readable sentence with comfortably more than five words in it.\n")
        # (b) a readable corpus is not a gap, and the local source answers "ok"
        n_docs, warnings = sources.set_corpus(tmp)
        if n_docs != 1 or warnings:
            problems.append("a readable corpus reported %d doc(s) and %r" % (n_docs, warnings))
        # The local filter only returns documents that share vocabulary with the passage, so
        # the query must share words with the fixture. "nothing matches" is a different
        # status from "nothing was read".
        status, _ = sources.search("readable sentence comfortably words", "local", 5)
        if status != "ok":
            problems.append("a readable corpus gave local status %r" % status)
        # (c) an unreadable file is a gap, and the local source must NOT answer "empty"
        locked = os.path.join(tmp, "locked.txt")
        with open(locked, "w", encoding="utf-8") as fh:
            fh.write("Some words that would be usable if the file could be opened.\n")
        os.chmod(locked, 0o000)
        try:
            n_docs, warnings = sources.set_corpus(tmp)
            if n_docs != 1 or not warnings:
                problems.append("a locked file was not reported (%d doc(s), %r)"
                                % (n_docs, warnings))
            # The local filter only returns documents that share vocabulary with the passage,
            # so the query must share words with the fixture. "nothing matches" is a different
            # status from "nothing was read".
            status, _ = sources.search("readable sentence comfortably words", "local", 5)
            if status != "ok":
                problems.append("a partly read corpus should still answer ok, got %r" % status)
            # now nothing readable at all
            sources.set_corpus(locked)
            status, _ = sources.search("readable sentence comfortably words", "local", 5)
            if status != "unavailable":
                problems.append("an unreadable corpus reported local status %r, not "
                                "'unavailable' -- it must never read as a corpus that "
                                "answered with no match" % status)
        finally:
            os.chmod(locked, 0o644)
        # (d) a corpus directory with no files is a gap, not an empty result
        empty = os.path.join(tmp, "empty_dir")
        os.makedirs(empty)
        n_docs, warnings = sources.set_corpus(empty)
        if n_docs != 0 or not warnings:
            problems.append("an empty corpus directory was not reported (%r)" % warnings)

        # (e) the report must not print a measurement over a corpus that loaded nothing
        empty_report = render_report("d.md", [], ["local"], 0.30, {},
                                     corpus_size=0,
                                     corpus_gaps=[_corpus_gap("/tmp/x.txt: unreadable")],
                                     corpus_path=tmp)
        for must in ("NO CORPUS WAS READ", "Cannot determine", "INPUT GAP", "/tmp/x.txt"):
            if must not in empty_report:
                problems.append("empty-corpus report is missing %r" % must)
        for forbidden in ("highest score", "No passage exceeded"):
            if forbidden in empty_report:
                problems.append("empty-corpus report still prints %r" % forbidden)
        # (f) a partly-read corpus keeps its scores but must still carry the gap
        part_report = render_report("d.md", [], ["local"], 0.30, {},
                                    corpus_size=2,
                                    corpus_gaps=[_corpus_gap("/tmp/x.txt: unreadable")],
                                    corpus_path=tmp)
        if "highest score" not in part_report:
            problems.append("a partly-read corpus lost its measurement line")
        if "INPUT GAP" not in part_report or "/tmp/x.txt" not in part_report:
            problems.append("a partly-read corpus did not report the unreadable file")
        # (g) an unchanged run is unchanged
        clean_report = render_report("d.md", [], ["local"], 0.30, {})
        if "highest score" not in clean_report or "INPUT GAP" in clean_report:
            problems.append("a clean corpus run changed shape")

    # (h) the benchmarks read the --threshold default out of this source text by regex
    if '"--threshold", type=float, default=' not in Path(__file__).read_text(encoding="utf-8"):
        problems.append("the --threshold default pattern the benchmarks parse is gone")

    # (i) ORI Guideline 4 disclosure: a clean report must carry the measured
    # structural-coverage bound, with the sentence count in it. No structural
    # threshold was wired (benchmarks/bench_frame_copy.py measured none that
    # clears the bar), so the disclosure is the whole control.
    clean = render_report("d.md", [], ["local"], 0.30, {}, corpus_size=2)
    if STRUCTURAL_MARKER not in clean:
        problems.append("a clean report does not carry the structural-coverage line")
    for must in ("frame-copying", "not covered", "known limitation", "not a clearance"):
        if must not in clean.lower():
            problems.append("the structural-coverage line does not say %r" % must)
    if "**0** sentence(s) were compared" not in structural_coverage_line(0):
        problems.append("the structural-coverage line does not carry the sentence count")
    if "**7** sentence(s) were compared" not in structural_coverage_line(7, 2):
        problems.append("the structural-coverage line ignores its inputs")
    if guard_report(clean, clean=True):
        problems.append("the report guard refused a clean report: %r"
                        % guard_report(clean, clean=True))
    # A clean claim with the disclosure stripped must be refused.
    stripped = clean.replace(STRUCTURAL_MARKER, "Nothing to see here")
    if not guard_report(stripped, clean=True):
        problems.append("the report guard accepted a clean report with no bound")
    # A FLAGGED report carries the same disclosure: a violations table must not
    # read as if the structural channel had been checked.
    flagged_row = {
        "sentence": "This study examines whether workers assist their mothers.",
        "verdict": "PARAPHRASE + CITE",
        "best": {"score": 0.8, "cosine": 0.8, "run_words": 12,
                 "run_span": "this study examines whether workers",
                 "candidate": {"source": "local", "id": "/tmp/c.txt", "title": "c"}},
    }
    flagged_report = render_report("d.md", [flagged_row], ["local"], 0.30, {},
                                   corpus_size=1)
    if STRUCTURAL_MARKER not in flagged_report:
        problems.append("a flagged report does not carry the structural-coverage line")
    if guard_report(flagged_report, clean=False):
        problems.append("the report guard refused a flagged report: %r"
                        % guard_report(flagged_report, clean=False))

    # (j) the report-guard fixtures: one overclaiming report, one unbounded one.
    fixtures = Path(__file__).resolve().parent / "fixtures"
    forbidden = fixtures / "report_forbidden.md"
    unbounded = fixtures / "report_unbounded.md"
    for fixture in (forbidden, unbounded):
        if not fixture.is_file():
            problems.append("report-guard fixture is missing: %s" % fixture)
    if forbidden.is_file():
        text = forbidden.read_text(encoding="utf-8")
        if not guard_report(text, clean=True):
            problems.append("the guard accepted the forbidden-claim fixture")
        if "forbidden claim" not in " ".join(guard_report(text, clean=True)):
            problems.append("the guard did not name the forbidden claim in the fixture")
    if unbounded.is_file():
        text = unbounded.read_text(encoding="utf-8")
        if not guard_report(text, clean=True):
            problems.append("the guard accepted the unbounded-clean fixture")
        module = _load_claim_guard()
        if module is not None:
            kinds = {f["kind"] for f in module.scan(text)}
            if "UNBOUNDED" not in kinds:
                problems.append("claim_guard did not report UNBOUNDED on the fixture; "
                                "got %r" % sorted(kinds))

    for p in problems:
        print("self-test FAILED: %s" % p)
    if problems:
        return 1
    print("self-test: OK (corpus-gap routing asserted offline; no network)")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("draft", nargs="?", help="path to the draft (.txt/.md)")
    parser.add_argument("--sources", default="openalex,crossref,arxiv,europepmc",
                        help="comma-separated: openalex,crossref,arxiv,europepmc,semantic")
    parser.add_argument("--corpus", default=None,
                        help="file or directory to compare against IN ADDITION to the APIs: "
                             ".txt/.md/.html, or .pdf with the optional pypdf package. "
                             "Use this for paywalled articles, theses, books, unpublished "
                             "manuscripts or saved web pages the APIs cannot reach.")
    parser.add_argument("--per-source", type=int, default=5)
    # 0.30, not 0.35: on a 186-case labelled benchmark (120 copying cases, 66
    # independent/unrelated) the scores separated cleanly -- negatives max 0.115,
    # positives min 0.319 -- and 0.35 missed a light edit that scored 0.319-0.346.
    # 0.30 keeps a 2.6x margin over every observed negative while catching all of
    # them (sensitivity and specificity both 100% on that set).
    parser.add_argument("--threshold", type=float, default=0.30)
    parser.add_argument("--min-run", type=int, default=3,
                        help="noise floor: verbatim words required for a REVIEW flag")
    parser.add_argument("--keep-tables", action="store_true",
                        help="do not drop <table> content from HTML drafts")
    parser.add_argument("--min-words", type=int, default=8)
    parser.add_argument("--out", default=None, help="write markdown report here")
    parser.add_argument("--json", dest="json_out", default=None,
                        help="write machine-readable results here (consumed by cite_fix.py)")
    parser.add_argument("--refresh", action="store_true", help="ignore cache")
    parser.add_argument("--allow-insufficient", action="store_true",
                        help="exit 0 although part (or all) of the local corpus could not be "
                             "read. The report and the JSON still record the gap, so the "
                             "override is logged rather than silent.")
    parser.add_argument("--recheck", default=None, metavar="PREVIOUS.json",
                        help="re-read only the corpus files a previous --json run could not "
                             "read, and exit 0 only once every one of them is readable.")
    parser.add_argument("--self-test", action="store_true",
                        help="offline check of the corpus-gap routing; no network")
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()
    if args.recheck:
        return recheck(args.recheck)
    if not args.draft:
        parser.error("a draft path is required (or --recheck with a previous --json output)")

    source_names = [s.strip() for s in args.sources.split(",") if s.strip()]
    corpus_gaps, n_docs = [], None
    if args.corpus:
        n_docs, corpus_warnings = sources.set_corpus(args.corpus)
        if "local" not in source_names:
            source_names.append("local")
        for warning in corpus_warnings:
            sys.stderr.write("corpus: %s\n" % warning)
        sys.stderr.write("corpus: %d document(s) loaded from %s\n" % (n_docs, args.corpus))
        # Every unreadable or skipped file becomes a worklist row. "Reported, never silently
        # skipped" was already true of stderr and false of everything that outlives the run:
        # --out and --json carried no trace of it, and the exit code said 0.
        corpus_gaps = [_corpus_gap(w) for w in corpus_warnings]
        if n_docs == 0:
            sys.stderr.write(
                "corpus: WARNING - no usable documents loaded; only the APIs will be "
                "checked. A 'no overlap' result would NOT cover this corpus.\n")
            if not corpus_gaps:
                corpus_gaps.append(
                    {"file": str(args.corpus), "reason": "no readable documents were loaded",
                     "action": "point --corpus at readable files and re-run"})
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
                           args.threshold, seen_statuses,
                           corpus_size=n_docs, corpus_gaps=corpus_gaps,
                           corpus_path=args.corpus)
    flagged = sum(1 for r in rows if r["verdict"] != "ok")
    # The report is a product, not a debug dump: it must not overclaim and a
    # clean result must carry its bound. Refuse to emit a report that fails either
    # property rather than print it and hope a reader notices.
    guard_problems = guard_report(report, clean=(flagged == 0 and n_docs != 0))
    if guard_problems:
        print("report guard REFUSED the report (this is a bug in the report template, "
              "not a result about the draft):", file=sys.stderr)
        for problem in guard_problems:
            print("  - %s" % problem, file=sys.stderr)
        return 1
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(report)
        print("Report written to %s" % args.out)
    else:
        print(report)

    print("Checked %d sentences; %d flagged." % (len(rows), flagged), file=sys.stderr)

    if args.json_out:
        payload = {
            "draft": os.path.basename(args.draft),
            "threshold": args.threshold,
            "sources": source_names,
            "sources_unavailable": sorted(
                s for s, st in seen_statuses.items() if st == "unavailable"
            ),
            # The input side travels with the results, so a consumer that reads only the JSON
            # cannot see the scores without also seeing what was not read.
            "corpus": {
                "path": args.corpus,
                "documents_loaded": n_docs,
                "not_checked": corpus_gaps,
                "status": ("insufficient_evidence" if corpus_gaps
                           else ("pass" if args.corpus else "not_configured")),
            },
            "status": "insufficient_evidence" if corpus_gaps else "pass",
            # The bound travels with the result: a consumer that reads only the
            # JSON must still see that frame-copying is not covered.
            "structural_coverage": {
                "sentences_compared": len(rows),
                "frame_copy_covered": False,
                "line": structural_coverage_line(len(rows), n_docs, source_names),
            },
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
    if corpus_gaps:
        print("INSUFFICIENT INPUT - %d corpus file(s) could not be read; the local-corpus "
              "figures above do not cover them:" % len(corpus_gaps), file=sys.stderr)
        for gap in corpus_gaps:
            print("  - %s: %s" % (gap["file"], gap["reason"]), file=sys.stderr)
        print("  status: insufficient_evidence (a statement about the inputs, not a finding "
              "about the draft)", file=sys.stderr)
        if n_docs == 0:
            print("  no document in the corpus was read, so NO local-corpus result could be "
                  "determined at all", file=sys.stderr)
        print("  action: fix the files and re-run, or re-check only these with --recheck %s"
              % (args.json_out or "<a --json output path>"), file=sys.stderr)
        if not args.allow_insufficient:
            return 3
        print("  --allow-insufficient given: the gaps stay recorded above and in the report",
              file=sys.stderr)
    return 0


def _corpus_gap(warning):
    """Turn one corpus warning into a worklist row: which file, why, and what to do.

    The two whole-corpus warnings are not "file: reason", they are "condition: path", so they
    are read by prefix rather than split on the first colon -- which would have labelled the
    problem as the filename and the path as the reason.
    """
    for prefix, reason in (
        ("corpus path does not exist: ", "the corpus path does not exist"),
        ("corpus contains no files: ", "the corpus contains no files to read"),
    ):
        if warning.startswith(prefix):
            return {"file": warning[len(prefix):].strip(), "reason": reason,
                    "action": "point --corpus at readable files and re-run"}
    if ":" in warning:
        name, detail = warning.split(":", 1)
        return {"file": name.strip(), "reason": detail.strip(),
                "action": "make the file readable, or remove it from the corpus, and re-run; "
                          "nothing was compared against it"}
    return {"file": warning.strip(), "reason": "could not be read",
            "action": "make the file readable, or remove it from the corpus, and re-run"}


def recheck(previous_json):
    """Re-read only the corpus files a previous run could not read.

    The invariant asks for a mode that re-checks the worklist, so that a gap can be shown to
    be closed rather than re-asserted. Exits 3 while any listed file still cannot be read.
    """
    try:
        with open(previous_json, encoding="utf-8") as handle:
            prior = json.load(handle)
    except Exception as exc:  # noqa: BLE001
        print("recheck: cannot read %s: %s" % (previous_json, exc), file=sys.stderr)
        return 1
    corpus = prior.get("corpus") or {}
    listed = corpus.get("not_checked") or []
    if not listed:
        print("recheck: %s recorded no unreadable corpus files -- nothing to re-check"
              % previous_json)
        return 0
    print("recheck: %d file(s) previously unreadable; re-reading now" % len(listed))
    still = []
    for row in listed:
        path = row.get("file")
        try:
            text = sources._read_document(Path(os.path.expanduser(str(path))).resolve())
            words = len(re.sub(r"\s+", " ", text).split())
        except Exception as exc:  # noqa: BLE001
            still.append(row)
            print("  STILL UNREADABLE  %s  %s" % (path, exc))
            continue
        if words < 5:
            still.append(row)
            print("  STILL UNUSABLE    %s  (%d word(s))" % (path, words))
            continue
        print("  READABLE          %s  (%d word(s))" % (path, words))
    if still:
        print("recheck: %d of %d file(s) still cannot be read -- the gap is NOT closed"
              % (len(still), len(listed)))
        return 3
    print("recheck: every previously unreadable corpus file is now readable; the gap is closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


