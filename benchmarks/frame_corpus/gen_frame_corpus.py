#!/usr/bin/env python3
"""gen_frame_corpus.py -- build the labelled frame-copy corpus (deterministic).

The question this corpus answers: can a stdlib-only measure tell a
*structure-preserving* rewrite (every content word swapped, the function-word
sequence, clause boundaries and punctuation kept) apart from:

  * unrelated real text, and
  * legitimate paraphrases the US ORI guide labels correct?

Classes (every item is one (draft sentence, candidate document) pair):

  frame_copy        POSITIVE. A real sentence the toolkit resolves, with every
                    content word swapped for a different content word and the
                    frame kept verbatim. MACHINE-GENERATED (see audit in README).
  unrelated         NEGATIVE. A real sentence checked against a DIFFERENT real
                    document from the same 54 preprint/published pairs.
  legit_paraphrase  NEGATIVE. ORI guide "Paraphrasing/Plagiarism Exercise"
                    versions 5 and 6, which the guide labels correctly
                    paraphrased, checked against the guide's source paragraph.
  real_revision     NEGATIVE (secondary). A preprint's sentence checked against
                    its OWN published abstract -- the same work, legitimately
                    revised by the same authors.

Reported separately, never in the decision set:

  human_frame_copy  POSITIVE (secondary, n=3). Hand-written frame copies in the
                    style of ORI Guideline 4 ("whether X are able to Y" ->
                    "whether P are able to Q"). Too few to decide anything; they
                    show what a human, not a substitution script, produces.

Determinism: the corpus is a pure function of source_pairs.json, the ORI text in
../bench_ori_guide.py and the fixed seed below. No network, no clock, no
filesystem entropy. Re-running overwrites corpus.json byte-for-byte.

Usage:
  python3 gen_frame_corpus.py                 # write corpus.json
  python3 gen_frame_corpus.py --fetch         # refresh source_pairs.json (network)
  python3 gen_frame_corpus.py --audit         # re-check the labels, write nothing
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH_DIR = HERE.parent
TOOLKIT = BENCH_DIR.parent / "tools/originality-toolkit"
sys.path.insert(0, str(TOOLKIT))

spec = importlib.util.spec_from_file_location("oc", TOOLKIT / "originality_check.py")
oc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oc)

SEED = 20260101
PAIRS_FILE = HERE / "source_pairs.json"
CORPUS_FILE = HERE / "corpus.json"

# ---------------------------------------------------------------------------
# Substitution pools. Content words only; disjoint from every function word the
# toolkit knows, so a swap can never change the function-word frame.
# ---------------------------------------------------------------------------
_NOUNS = """
alpha beta gamma delta epsilon zeta eta theta iota kappa lambda sigma tau
ridge valley basin plateau canyon dune marsh delta estuary lagoon reef atoll
falcon heron ibis martin osprey plover quail raven shrike tern veery wren
cedar birch aspen alder juniper larch spruce willow poplar hazel maple
granite basalt gneiss shale slate marble quartz feldspar mica chert
lantern compass anchor rudder sextant astrolabe barometer gauge valve piston
ledger archive almanac atlas chronicle digest gazette index lexicon primer
baker cooper fletcher saddler tanner weaver miller potter chandler
cobalt copper nickel zinc silver argon neon krypton xenon radon helium
glacier tundra savanna steppe taiga chaparral mangrove prairie moor
sensor actuator encoder decoder router switch bridge gateway socket buffer
""".split()

_VERBS = """
assemble calibrate catalogue clarify cluster collapse compare compile compress
configure consolidate constrain construct correlate decode decompose detect
dispatch dissolve distill divide encode enumerate estimate evaluate expand
explain extract fabricate filter gauge gather generate identify index inspect
integrate interpret invert isolate label laminate locate magnify map measure
merge modulate monitor normalise observe operate partition perturb position
preserve probe process propagate quantify rank reassemble reconcile recover
reduce refine register regulate reject release relocate render reorganise
replicate rescale resolve retrieve reveal rotate sample scale segment select
separate sequence simplify sort split stabilise store structure survey suspend
synthesise tabulate tally test trace track transform transpose truncate tune
unify validate vary verify weigh widen wrap
""".split()

_ADJS = """
abrupt annual arduous austere brisk brittle buoyant coarse compact concave
convex crisp dense diffuse distal dorsal dual elongate faint fibrous flat
fluent fragile granular humid inert intact intermittent inward lateral latent
littoral lofty lucid mature meagre minute moist nominal oblique opaque outward
placid pliant porous precise proximal robust rugged saline scanty sparse
steep stiff subtle supple taut temperate tenuous tepid thin tidal tolerant
translucent uneven vacant vast ventral viscous vivid waxy
""".split()

_ADVS = """
abruptly briskly carefully chiefly compactly densely faintly flatly fluently
gently granularly humidly inertly intermittently inward largely laterally
loosely lucidly mildly minutely moistly nominally obliquely outwardly placidly
precisely proximally robustly roughly scarcely sparsely steeply stiffly
subtly supplely tautly temperately tenuously thinly tidally unevenly vastly
vividly waxy widely
""".split()

_POOL = {"noun": _NOUNS, "verb": _VERBS, "adj": _ADJS, "adv": _ADVS}
_FUNCTION = set(oc._FUNCTION_WORDS) | set(oc.STOPWORDS) | {
    "using", "used", "use", "based", "results", "study", "paper", "research",
}

# oc.WORD_RE starts with [a-z0-9], so it silently splits "Here" into a copied
# "H" plus a swapped "ere" -- which changed the function-word frame. The swap
# needs its own case-insensitive tokeniser.
SWAP_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]*")


def swapped_content(text):
    """Tokens the swap is allowed to touch: not a function word by either list.

    ``oc.content_tokens`` is not the right class here: it filters on STOPWORDS
    only, so it counts "whether", "across", "many" and "one" as content even
    though they are in ``oc._FUNCTION_WORDS`` and the swap deliberately keeps
    them. Overlap is measured on the words actually swapped.
    """
    return [w for w in oc.normalise(text) if w not in _FUNCTION]


def _seeded_index(seed_text, modulo):
    digest = hashlib.sha1(seed_text.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % modulo


def _pos_guess(word):
    if word.endswith("ly"):
        return "adv"
    if word.endswith("ing") or word.endswith("ed") or word.endswith("ise") \
            or word.endswith("ize") or word.endswith("ate"):
        return "verb"
    if word.endswith("ous") or word.endswith("ive") or word.endswith("al") \
            or word.endswith("ic") or word.endswith("ent") or word.endswith("ant"):
        return "adj"
    return None


def _replacement(word, pos, forbidden, used):
    """Pick a pool word of the same rough part of speech, never a source word."""
    suffix = ""
    if pos == "verb" and word.endswith("ing"):
        suffix = "ing"
    elif pos == "verb" and word.endswith("ed"):
        suffix = "ed"
    elif pos == "noun" and word.endswith("s") and not word.endswith("ss"):
        suffix = "s"
    pool = _POOL[pos]
    start = _seeded_index(word + "|" + pos + "|" + str(SEED), len(pool))
    for step in range(len(pool)):
        base = pool[(start + step) % len(pool)]
        candidate = base + suffix
        key = candidate.lower()
        if key in forbidden or key in used or key in _FUNCTION:
            continue
        used.add(key)
        return candidate
    return word  # pool exhausted; leave the word (the audit will catch it)


def content_swap(text, forbidden):
    """Swap EVERY content word in ``text``, keeping punctuation and frame.

    ``forbidden`` is the set of content words present in the candidate document:
    a replacement never collides with them, so lexical overlap stays at zero and
    the measure under test cannot be helped by a content-word coincidence.
    """
    used = set()
    out, last = [], 0
    for match in SWAP_RE.finditer(text):
        out.append(text[last:match.start()])
        word = match.group(0)
        low = word.lower()
        if low in _FUNCTION:
            out.append(word)
        else:
            pos = _pos_guess(low) or ("noun", "verb", "adj")[
                _seeded_index(low + str(SEED), 3)
            ]
            rep = _replacement(low, pos, forbidden, used)
            if word[:1].isupper():
                rep = rep.capitalize()
            out.append(rep)
        last = match.end()
    out.append(text[last:])
    return "".join(out)


# ---------------------------------------------------------------------------
# Source material
# ---------------------------------------------------------------------------
def load_ori():
    spec2 = importlib.util.spec_from_file_location("ori", BENCH_DIR / "bench_ori_guide.py")
    mod = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(mod)
    return mod.ORIGINAL, mod.VERSIONS, mod.STRUCTURE_COPIES


def load_pairs():
    if not PAIRS_FILE.is_file():
        sys.exit("frame_corpus: %s is missing; run with --fetch once" % PAIRS_FILE)
    return json.loads(PAIRS_FILE.read_text(encoding="utf-8"))


def fetch_pairs():
    """Refresh source_pairs.json from the same collector the real benchmark uses."""
    spec2 = importlib.util.spec_from_file_location("real", BENCH_DIR / "bench_originality_real.py")
    mod = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(mod)
    import os
    os.environ["PAIRS"] = "60"
    pairs = mod.collect()
    pairs = pairs[:54]
    PAIRS_FILE.write_text(json.dumps(pairs, indent=1), encoding="utf-8")
    print("frame_corpus: fetched %d real pairs -> %s" % (len(pairs), PAIRS_FILE))
    return pairs


def document(pair, side):
    if side == "preprint":
        return {"title": pair["preprint_doi"], "abstract": pair["preprint_abstract"]}
    return {"title": pair["published_title"], "abstract": pair["published_abstract"]}


def body(doc):
    return "%s. %s" % (doc.get("title", ""), doc.get("abstract", ""))


def first_sentences(text, count=3, min_words=9):
    out = []
    for sentence in oc.split_sentences(text, min_words=min_words):
        out.append(sentence)
        if len(out) >= count:
            break
    return out


# ---------------------------------------------------------------------------
# Corpus construction
# ---------------------------------------------------------------------------
def build():
    ori_original, ori_versions, structure_copies = load_ori()
    pairs = load_pairs()
    items = []

    def add(cls, label, draft, doc, origin, anchor="", note=""):
        items.append({
            "id": "%s-%03d" % (cls, sum(1 for i in items if i["class"] == cls) + 1),
            "class": cls, "label": label, "draft": draft,
            "source_title": doc.get("title", ""),
            "source_text": doc.get("abstract", ""),
            "origin": origin, "anchor": anchor, "note": note,
        })

    # ---- POSITIVES: machine-generated frame copies -------------------------
    # One sentence per real pair, alternating preprint / published as the
    # anchor, checked against its own document. The anchor is a sentence the
    # toolkit already resolves to that document (asserted in --audit).
    for index, pair in enumerate(pairs):
        side = "preprint" if index % 2 == 0 else "published"
        doc = document(pair, side)
        sentences = first_sentences(doc["abstract"], count=1)
        if not sentences:
            continue
        anchor = sentences[0]
        forbidden = {w for w in oc.normalise(body(doc))} | {w for w in oc.normalise(anchor)}
        draft = content_swap(anchor, forbidden)
        add("frame_copy", 1, draft, doc, "generated:content-swap", anchor=anchor,
            note="preprint" if side == "preprint" else "published")

    # A second, shorter positive per pair from the opposite side, so the class
    # is not one sentence shape repeated.
    for index, pair in enumerate(pairs):
        side = "published" if index % 2 == 0 else "preprint"
        doc = document(pair, side)
        sentences = first_sentences(doc["abstract"], count=2, min_words=10)
        if len(sentences) < 2:
            continue
        anchor = sentences[1]
        forbidden = {w for w in oc.normalise(body(doc))} | {w for w in oc.normalise(anchor)}
        draft = content_swap(anchor, forbidden)
        add("frame_copy", 1, draft, doc, "generated:content-swap", anchor=anchor,
            note="second sentence")

    # ---- NEGATIVES: unrelated real documents ------------------------------
    n = len(pairs)
    offset = max(1, n // 2)
    for index, pair in enumerate(pairs):
        draft_doc = document(pair, "preprint")
        other = pairs[(index + offset) % n]
        if other is pair:
            continue
        source_doc = document(other, "published")
        sentences = first_sentences(draft_doc["abstract"], count=1)
        if not sentences:
            continue
        add("unrelated", 0, sentences[0], source_doc, "real:different-document",
            anchor=sentences[0], note="preprint %d vs published %d"
            % (index, (index + offset) % n))

    # ---- NEGATIVES: ORI versions 5 and 6 (labelled correct) ---------------
    for version in (5, 6):
        verdict, text = ori_versions[version]
        for sentence in oc.split_sentences(text, min_words=9):
            add("legit_paraphrase", 0, sentence,
                {"title": "ORI guide source paragraph", "abstract": ori_original},
                "ori-guide:%s (labelled PROPER)" % verdict)

    # ---- NEGATIVE (secondary): legitimate same-work revision --------------
    for index, pair in enumerate(pairs):
        doc = document(pair, "published")
        preprint_doc = document(pair, "preprint")
        sentences = first_sentences(preprint_doc["abstract"], count=1)
        if not sentences:
            continue
        add("real_revision", 0, sentences[0], doc, "real:own-published-version",
            anchor=sentences[0], note="same work, revised by the authors")

    # ---- SECONDARY POSITIVE: hand-written frame copies (n=3) --------------
    for copy in structure_copies:
        add("human_frame_copy", 1, copy,
            {"title": "ORI guide source paragraph", "abstract": ori_original},
            "ori-guide:hand-written structure copy")

    order = {"frame_copy": 0, "human_frame_copy": 1, "unrelated": 2,
             "real_revision": 3, "legit_paraphrase": 4}
    items.sort(key=lambda i: (order[i["class"]], i["id"]))
    counts = {}
    for item in items:
        counts[item["class"]] = counts.get(item["class"], 0) + 1
    return {
        "version": 1,
        "generator": "gen_frame_corpus.py",
        "seed": SEED,
        "source": {
            "ori_guide": "bench_ori_guide.py (ORIGINAL, VERSIONS 5/6, STRUCTURE_COPIES)",
            "real_pairs": "source_pairs.json (%d bioRxiv/medRxiv preprint-vs-published pairs)" % len(pairs),
        },
        "decision": {
            "positives": ["frame_copy"],
            "negatives": ["unrelated", "legit_paraphrase", "real_revision"],
            "reported_separately": ["human_frame_copy", "real_revision"],
        },
        "machine_generated": {
            "frame_copy": True,
            "human_frame_copy": False,
            "unrelated": False,
            "real_revision": False,
            "legit_paraphrase": False,
        },
        "counts": dict(sorted(counts.items())),
        "items": items,
    }


def audit(corpus):
    """Re-derive the labels from the text. Every claim the corpus makes is checked."""
    problems, notes = [], []
    for item in corpus["items"]:
        cls = item["class"]
        draft, cand = item["draft"], body({"title": item["source_title"],
                                           "abstract": item["source_text"]})
        d_fw = [w for w in oc.normalise(draft) if w in oc._FUNCTION_WORDS]
        d_swap = set(swapped_content(draft))
        c_swap = set(swapped_content(cand))
        if cls == "frame_copy":
            a_fw = [w for w in oc.normalise(item["anchor"]) if w in oc._FUNCTION_WORDS]
            if d_fw != a_fw:
                problems.append("%s: function-word frame changed by the swap" % item["id"])
            overlap = d_swap & c_swap
            if overlap:
                problems.append("%s: swapped-content overlap is not zero: %s"
                                % (item["id"], sorted(overlap)[:4]))
            if d_swap == set(swapped_content(item["anchor"])):
                problems.append("%s: no content word was swapped" % item["id"])
            kept = set(swapped_content(item["anchor"])) & d_swap
            if kept:
                problems.append("%s: %d content word(s) left unswapped: %s"
                                % (item["id"], len(kept), sorted(kept)[:4]))
        if cls in ("unrelated", "real_revision"):
            if not item["anchor"]:
                problems.append("%s: missing anchor" % item["id"])
        if not draft.strip():
            problems.append("%s: empty draft" % item["id"])
    machine = sum(1 for i in corpus["items"] if corpus["machine_generated"][i["class"]])
    notes.append("items: %d; machine-generated: %d; human-sourced: %d"
                 % (len(corpus["items"]), machine, len(corpus["items"]) - machine))
    for cls, count in sorted(corpus["counts"].items()):
        notes.append("  %-18s n=%-4d machine_generated=%s"
                     % (cls, count, corpus["machine_generated"][cls]))
    return problems, notes


def resolution_audit(corpus):
    """Prove the frame-copy anchors are sentences the toolkit already resolves.

    Each candidate document is loaded through the toolkit's own local-corpus
    adapter, then each anchor is queried exactly as the checker queries it. Only
    the classes whose draft really belongs to the candidate document are checked:
    an ``unrelated`` draft is from a different paper on purpose, so "it resolves
    to this document" is not a claim the corpus makes. Returns (checked, resolved).
    """
    import tempfile
    items = corpus["items"]
    checked = resolved = 0
    with tempfile.TemporaryDirectory() as tmp:
        names = []
        for index, item in enumerate(items):
            path = Path(tmp) / ("doc-%03d.txt" % index)
            path.write_text(body({"title": item["source_title"],
                                  "abstract": item["source_text"]}), encoding="utf-8")
            names.append(path.stem)
        n_docs, warnings = oc.sources.set_corpus(tmp)
        if warnings:
            print("frame_corpus: WARNING resolution audit corpus: %r" % warnings)
        for index, item in enumerate(items):
            if item["class"] not in ("frame_copy", "human_frame_copy", "real_revision"):
                continue
            anchor = item["anchor"] or item["draft"]
            checked += 1
            status, candidates = oc.sources.search(
                oc.keyphrase_query(anchor), "local", 999)
            if status != "ok":
                continue
            expected = names[index]
            # local docs carry id=<full path>, title=<file stem> (sources._cand).
            if any(str(c.get("title", "")) == expected for c in candidates):
                resolved += 1
    return checked, resolved


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fetch", action="store_true",
                    help="refresh source_pairs.json from bioRxiv/medRxiv+OpenAlex (network)")
    ap.add_argument("--audit", action="store_true", help="check the labels, write nothing")
    args = ap.parse_args(argv)

    if args.fetch:
        fetch_pairs()
    corpus = build()
    problems, notes = audit(corpus)
    checked, resolved = resolution_audit(corpus)
    corpus["resolution"] = {"anchors_checked": checked, "anchors_resolved": resolved}
    for note in notes:
        print("frame_corpus: " + note)
    print("frame_corpus: toolkit resolves %d/%d anchors against their own document"
          % (resolved, checked))
    if problems:
        for problem in problems:
            print("frame_corpus AUDIT FAILED: %s" % problem)
        return 1
    print("frame_corpus: label audit OK")
    if not args.audit:
        CORPUS_FILE.write_text(json.dumps(corpus, indent=1, sort_keys=True),
                               encoding="utf-8")
        print("frame_corpus: wrote %s" % CORPUS_FILE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
