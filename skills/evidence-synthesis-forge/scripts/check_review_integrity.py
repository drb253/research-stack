#!/usr/bin/env python3
"""Cross-artifact review-integrity gate.
Catches the defect classes the numeric/provenance gates are blind to:
  R  reference-list completeness vs the included set
  C  claims-ledger numeric sync vs the ledger
  C2 supporting-ID validity (unsourced claims, prose-in-ID-column, unknown IDs)
  D  retrieval/dedup plausibility (records from >1 overlapping source cannot be 0 duplicates)
  M  manuscript numeric sync vs the ledger (screened/excluded/included/RoB)
  E  eligibility red-flags on INCLUDED studies (ER-001 perception-only, ER-009 preliminary)
  X  cross-artifact fact consistency (same fact, same number, every artifact)
  T  template/placeholder leakage into a rendered deliverable
  W  CSV well-formedness (ragged / unquoted-embedded-comma rows)
  P  PRISMA flow reconciliation
    python3 tools/check_review_integrity.py            # gate run (exit 2 on any problem)
    python3 tools/check_review_integrity.py --selftest # prove each check fires
"""
import argparse, csv, json, os, re, sys
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _load_csv(name, root=REPO):
    # utf-8-sig tolerates a UTF-8 BOM. A BOM-prefixed ledger must never turn its own first
    # column name into '\ufeffsource_id' and raise KeyError - that is a data-format artefact,
    # not a finding about the review.
    # A missing ledger is likewise reported as a finding by the caller, never as a raw
    # traceback: sources.csv and claims.csv are mandatory, the ledgers/ files may legitimately
    # be absent in a review that has not reached extraction/appraisal yet.
    path = os.path.join(root, name)
    if not os.path.exists(path):
        return []
    return list(csv.DictReader(open(path, encoding="utf-8-sig")))

_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
          "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
          "nineteen", "twenty", "twenty-one", "twenty-two", "twenty-three", "twenty-four",
          "twenty-five", "twenty-six", "twenty-seven", "twenty-eight", "twenty-nine", "thirty"]
_W2I = dict(zip(_WORDS, range(31)))
_NUM = r"(?:\d+|" + "|".join(_WORDS) + r")"


def _num_before(s, phrase):
    s = re.sub(r"\s+", " ", (s or "")).lower()
    s = re.sub(r"[*_`#]", "", s)
    m = re.search(r"(" + _NUM + r")\s+" + phrase, s)
    if not m:
        return None
    t = m.group(1)
    return int(t) if t.isdigit() else _W2I.get(t)

# --- R: reference-list completeness ---
def check_references(included_ids, manuscript):
    refs = set(re.findall(r"\[src:(S\d+)\]", manuscript.split("## References")[-1]))
    inc = set(included_ids); probs = []
    missing = sorted(inc - refs)
    if missing:
        probs.append("R: %d included study(ies) missing from the reference list: %s" % (len(missing), missing[:8]))
    extra = sorted(refs - inc)
    if extra:
        probs.append("R: %d reference(s) not in the included set: %s" % (len(extra), extra[:8]))
    return probs

# --- C: claims-ledger numeric sync ---
def check_claims(claims, n_included, n_effect, n_direction):
    probs = []
    for c in claims:
        s = c.get("claim_summary", "")
        got = _num_before(s, "included studies")
        if got is not None and got != n_included:
            probs.append("C:%s says %d included studies; ledger has %d" % (c["claim_id"], got, n_included))
        got = _num_before(s, "contribute an effect estimate")
        if got is not None and got != n_effect:
            probs.append("C:%s says %d contribute an effect estimate; extraction has %d" % (c["claim_id"], got, n_effect))
        got = _num_before(s, "contribute none")
        if got is not None and got != n_direction:
            probs.append("C:%s says %d contribute none; extraction has %d direction-only" % (c["claim_id"], got, n_direction))
    return probs

# --- M: manuscript numeric sync ---
def check_manuscript(manuscript, n_total, n_excluded, n_included, n_rob2, n_robins):
    probs = []
    got = _num_before(manuscript, "unique records screened")
    if got is not None and got != n_total:
        probs.append("M: manuscript says %d unique records screened; ledger has %d" % (got, n_total))
    got = _num_before(manuscript, "excluded at title/abstract")
    if got is not None and got != n_excluded:
        probs.append("M: manuscript says %d excluded at title/abstract; ledger has %d" % (got, n_excluded))
    got = _num_before(manuscript, "studies included")
    if got is not None and got != n_included:
        probs.append("M: manuscript says %d studies included; ledger has %d" % (got, n_included))
    got = _num_before(manuscript, "randomised studies")
    if got is not None and got != n_rob2:
        probs.append("M: manuscript says %d randomised studies; RoB ledger has %d RoB 2" % (got, n_rob2))
    got = _num_before(manuscript, "non-randomised studies")
    if got is not None and got != n_robins:
        probs.append("M: manuscript says %d non-randomised studies; RoB ledger has %d ROBINS-I" % (got, n_robins))
    return probs

# --- E: eligibility red-flags on included studies ---
_PERCEPTION = {"perception", "perceptions", "trust", "comfort", "attitude", "attitudes",
               "satisfaction", "willingness", "awareness", "communication"}
_CARE = {"health", "outcome", "clinical", "cost", "visit", "admission", "diagnosis",
         "diagnoses", "prescribing", "referral", "healing", "infection", "mortality",
         "survival", "detection", "knowledge", "compliance", "adherence", "practices",
         "delivery", "screening", "uptake", "treatment", "care", "safety", "readmission",
         "hba1c", "vascular", "event", "antibiotic", "glycaemic", "symptom", "workload",
         "reading", "referral", "follow-up", "follow up"}

def _perception_only(text):
    t = (text or "").lower()
    return any(w in t for w in _PERCEPTION) and not any(w in t for w in _CARE)

def check_eligibility(extraction):
    flags = []
    for r in extraction:
        sid = r.get("source_id", "?")
        if _perception_only(r.get("primary_outcome", "")):
            flags.append("E:%s ER-001 red-flag: primary outcome is perception/attitude-only (%s)"
                         % (sid, r.get("primary_outcome", "")[:70]))
        out = " ".join([r.get("primary_outcome", ""), r.get("effect_primary", ""),
                        r.get("extraction_note", "")]).lower()
        if any(w in out for w in ("preliminary", "ongoing", "no completed",
                                  "no completed comparative", "will be conducted")):
            flags.append("E:%s ER-009 red-flag: preliminary/ongoing data or no completed result" % sid)
    return flags

def _read(name, root=REPO):
    p = os.path.join(root, name)
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def _rows(name, root=REPO):
    p = os.path.join(root, name)
    if not os.path.exists(p):
        return []
    with open(p, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


# --- D: retrieval/dedup plausibility ---
def check_dedup_plausibility(pc, search_log_rows):
    """Zero duplicates across more than one overlapping database is not a finding, it is a
    missing step: PubMed/Europe PMC/OpenAlex/Semantic Scholar/Crossref overlap heavily."""
    probs = []
    ident = pc.get("identification", {}) or {}
    dbs = int(ident.get("records_from_databases", 0) or 0)
    dups = int(ident.get("duplicates_removed", 0) or 0)
    sources = {(r.get("source") or "").strip().lower()
               for r in search_log_rows if (r.get("source") or "").strip()}
    if dbs > 0 and dups == 0 and len(sources) > 1:
        probs.append("D: %d records drawn from %d sources but duplicates_removed=0 - sources with "
                     "overlapping coverage cannot yield zero duplicates; the deduplication step is "
                     "missing, not the duplicates" % (dbs, len(sources)))
    return probs


# --- C2: supporting-ID validity (catches unquoted-comma claims rows) ---
_SID_RE = re.compile(r"^S\d{3,}$")


def check_supporting_ids(claims, known_ids):
    """Every claim must cite >=1 well-formed source id present in sources.csv.

    Catches the corruption class where an unquoted embedded comma splits a claim's text
    into the supporting_sids column, so prose ends up where source IDs belong. The
    column-count check (W) cannot see this: the row still has the right shape.
    """
    probs = []
    for c in claims:
        cid = c.get("claim_id", "?")
        raw = (c.get("supporting_sids") or "").strip()
        if not raw:
            probs.append("C2:%s has no supporting_sids - claim is unsourced" % cid)
            continue
        toks = [t for t in re.split(r"[;,\s]+", raw) if t]
        bad = [t for t in toks if not _SID_RE.match(t)]
        if bad:
            probs.append("C2:%s supporting_sids holds non-ID content %r - an unquoted embedded "
                         "comma split the row; quote the claim text"
                         % (cid, " ".join(bad)[:70]))
            continue
        unknown = sorted({t for t in toks if t not in known_ids})
        if unknown:
            probs.append("C2:%s cites unknown source id(s) %s" % (cid, unknown[:6]))
    return probs


# --- X: cross-artifact fact consistency ---
def check_fact_consistency(sources, artifacts):
    """A fact carried by two artifacts must carry the same number in both.

    Reference values are derived from the ledger; each artifact is then scanned for the
    same fact asserted in prose. Disagreement between artifacts IS the defect.
    """
    probs = []
    inc = [r for r in sources if r.get("inclusion_status") == "included"]
    n = len(inc)
    if not n:
        return probs
    npat = r"(?:%d|%s)" % (n, _WORDS[n]) if n < len(_WORDS) else str(n)
    multi = sum(1 for r in inc if "multi" in (r.get("country") or "").lower())
    for fact, want in (("multi-country", multi), ("India-specific", n - multi)):
        rx = re.compile(r"(\w+)\s+of\s+" + npat + r"\s+(?:included\s+)?stud(?:y|ies)\s+"
                        r"(?:are|were)\s+" + re.escape(fact), re.I)
        for name, text in artifacts.items():
            for m in rx.finditer(text or ""):
                tok = m.group(1).strip().lower()
                got = int(tok) if tok.isdigit() else _W2I.get(tok)
                if got is not None and got != want:
                    probs.append("X: %s asserts %d %s; sources.csv yields %d - artifacts disagree"
                                 % (name, got, fact, want))
    return probs


# --- T: template/placeholder leakage into a rendered deliverable ---
_LEAK = ("[src:", "{{", "}}", "TODO", "TBD", "FIXME")


def check_no_template_leak(paths, root=REPO):
    probs = []
    for name in paths:
        p = os.path.join(root, name)
        if not os.path.exists(p):
            continue
        text = open(p, encoding="utf-8", errors="replace").read()
        for tok in _LEAK:
            if tok in text:
                probs.append("T: %s leaks template marker %r" % (name, tok))
    return probs


# --- W: CSV well-formedness ---
def check_csv_wellformed(paths, root=REPO):
    probs = []
    for name in paths:
        p = os.path.join(root, name)
        if not os.path.exists(p):
            probs.append("W: missing %s" % name); continue
        with open(p, encoding="utf-8") as f:
            rd = csv.reader(f); header = next(rd, None)
            if header is None:
                probs.append("W: %s is empty" % name); continue
            ncol = len(header)
            for i, row in enumerate(rd, start=2):
                if len(row) != ncol:
                    probs.append("W: %s line %d has %d columns (header %d) - ragged/unquoted-comma row"
                                 % (name, i, len(row), ncol))
    return probs

# --- P: PRISMA reconciliation ---
def normalize_prisma(pc):
    """Return nested PRISMA sections, accepting the flat prisma_flow.py shape too.

    prisma_flow.py renders BOTH shapes, but this gate only understood the nested one,
    so a valid flat counts file crashed it with a raw KeyError instead of a finding.
    """
    if isinstance(pc.get("screening"), dict):
        return pc
    if "screened" in pc:
        ft = pc.get("excluded_ft") or {}
        return {
            "identification": {
                "records_from_databases": pc.get("identified_databases", 0),
                "records_from_registers": pc.get("identified_registers", 0),
                "records_from_other_methods": pc.get("identified_other", 0),
                "duplicates_removed": pc.get("duplicates_removed", 0)},
            "screening": {"records_screened": pc.get("screened", 0),
                          "records_excluded": pc.get("excluded_ta", 0)},
            "retrieval": {"reports_sought": pc.get("sought", 0),
                          "reports_not_retrieved": pc.get("not_retrieved", 0)},
            "eligibility": {"reports_assessed": pc.get("assessed", 0),
                            "reports_excluded": sum(int(v or 0) for v in ft.values())},
            "included": {"studies_included": pc.get("included_studies", 0),
                         "in_meta_analysis": pc.get("in_meta_analysis", 0)},
        }
    raise SystemExit(
        "prisma_counts.json: unrecognised shape. Expected either the nested keys "
        "(identification/screening/retrieval/eligibility/included) or the flat keys "
        "used by prisma_flow.py (identified_databases/screened/excluded_ta/...).")


def check_prisma(pc):
    pc = normalize_prisma(pc)
    sc, rt, el, ii = pc["screening"], pc["retrieval"], pc["eligibility"], pc["included"]
    probs = []
    if sc["records_screened"] - sc["records_excluded"] != rt["reports_sought"]:
        probs.append("P: screened(%d) - excluded(%d) != sought(%d)" % (sc["records_screened"], sc["records_excluded"], rt["reports_sought"]))
    if el["reports_assessed"] - el["reports_excluded"] != ii["studies_included"]:
        probs.append("P: assessed(%d) - excluded(%d) != included(%d)" % (el["reports_assessed"], el["reports_excluded"], ii["studies_included"]))
    return probs

def collect(root=REPO):
    mandatory = ["sources.csv", "claims.csv", "manuscript.md", "prisma_counts.json"]
    missing = [n for n in mandatory if not os.path.exists(os.path.join(root, n))]
    if missing:
        # A missing artifact is a finding about the review, not a reason to traceback.
        return ["X: mandatory review artifact(s) missing: %s" % ", ".join(missing)]
    src = _load_csv("sources.csv", root)
    included = [r for r in src if r["inclusion_status"] == "included"]
    excluded = [r for r in src if r["inclusion_status"] == "excluded"]
    extraction = _load_csv("ledgers/extraction.csv", root)
    rob = _load_csv("ledgers/rob_assessment.csv", root)
    claims = _load_csv("claims.csv", root)
    manuscript = open(os.path.join(root, "manuscript.md"), encoding="utf-8").read()
    pc = json.load(open(os.path.join(root, "prisma_counts.json")))
    n_effect = sum(1 for r in extraction if "not recoverable" not in r["effect_primary"] and "NOT EXTRACTABLE" not in r["effect_primary"])
    n_direction = len(extraction) - n_effect
    n_rob2 = sum(1 for r in rob if r["tool"] == "RoB 2")
    n_robins = sum(1 for r in rob if r["tool"] == "ROBINS-I")
    probs = []
    probs += check_references([r["source_id"] for r in included], manuscript)
    probs += check_claims(claims, len(included), n_effect, n_direction)
    probs += check_manuscript(manuscript, len(src), len(excluded), len(included), n_rob2, n_robins)
    probs += check_eligibility(extraction)
    probs += check_dedup_plausibility(pc, _rows("search_log.csv", root))
    probs += check_supporting_ids(claims, {r["source_id"] for r in src})
    probs += check_fact_consistency(src, {"manuscript.md": manuscript,
                                          "synthesis.md": _read("synthesis.md", root)})
    probs += check_no_template_leak(["review_full.html"], root)
    probs += check_csv_wellformed(["sources.csv", "claims.csv", "ledgers/extraction.csv",
                                   "ledgers/rob_assessment.csv", "ledgers/sources_included.csv"], root)
    probs += check_prisma(pc)
    return probs

def _INC4():
    """5 included rows, 1 multi-country -> 4 India-specific (X-check selftest fixture)."""
    return ([{"inclusion_status": "included", "country": "multi-country incl India"}]
            + [{"inclusion_status": "included", "country": "India"}] * 4)


def _leak_case():
    import tempfile
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "x.html"), "w", encoding="utf-8") as fh:
        fh.write("<p>[src:S001]</p>")
    return check_no_template_leak(["x.html"], d)


def selftest():
    ok, n, passed = True, 0, 0
    def case(label, fn, expect):
        nonlocal ok, n, passed
        good = bool(fn()) == expect; ok &= good; n += 1; passed += good
        print("%-4s %s" % ("OK" if good else "BAD", label))
    case("R missing reference fires", lambda: bool(check_references(["S001", "S002"], "## References\n1. [src:S001] x")), True)
    case("R complete passes", lambda: bool(check_references(["S001"], "## References\n1. [src:S001] x")), False)
    case("C stale count fires", lambda: bool(check_claims([{"claim_id": "C1", "claim_summary": "Nine included studies"}], 25, 18, 7)), True)
    case("C correct passes", lambda: bool(check_claims([{"claim_id": "C1", "claim_summary": "25 included studies"}], 25, 18, 7)), False)
    case("M stale RoB fires", lambda: bool(check_manuscript("Five randomised studies; three non-randomised", 368, 340, 25, 21, 4)), True)
    case("M correct passes", lambda: bool(check_manuscript("368 unique records screened; 340 excluded; 25 studies included; 21 randomised studies; 4 non-randomised", 368, 340, 25, 21, 4)), False)
    case("E perception-only fires", lambda: bool(check_eligibility([{"source_id": "S1", "primary_outcome": "Patient trust, comfort and communication (Likert)", "effect_primary": "", "extraction_note": ""}])), True)
    case("E preliminary fires", lambda: bool(check_eligibility([{"source_id": "S2", "primary_outcome": "HbA1c", "effect_primary": "preliminary/ongoing-RCT data, no completed result", "extraction_note": ""}])), True)
    case("E legit passes", lambda: bool(check_eligibility([{"source_id": "S3", "primary_outcome": "Acute care visits", "effect_primary": "RR 0.556", "extraction_note": ""}])), False)
    case("C2 unsourced claim fires", lambda: bool(check_supporting_ids([{"claim_id": "C1", "supporting_sids": ""}], {"S001"})), True)
    case("C2 prose-in-ids fires", lambda: bool(check_supporting_ids([{"claim_id": "C2", "supporting_sids": " boosted and SVR baselines for dengue case prediction in Kerala (RMSE 0.345"}], {"S001"})), True)
    case("C2 unknown id fires", lambda: bool(check_supporting_ids([{"claim_id": "C3", "supporting_sids": "S999"}], {"S001"})), True)
    case("C2 clean passes", lambda: bool(check_supporting_ids([{"claim_id": "C4", "supporting_sids": "S001"}], {"S001"})), False)
    case("X contradiction fires", lambda: bool(check_fact_consistency(_INC4(), {"m.md": "only two of five included studies are India-specific"})), True)
    case("X consistent passes", lambda: bool(check_fact_consistency(_INC4(), {"m.md": "only four of five included studies are India-specific"})), False)
    case("T template leak fires", lambda: bool(_leak_case()), True)
    case("D zero-dedup fires", lambda: bool(check_dedup_plausibility(
        {"identification": {"records_from_databases": 7475, "duplicates_removed": 0}},
        [{"source": "PubMed"}, {"source": "Scopus"}])), True)
    case("D real dedup passes", lambda: bool(check_dedup_plausibility(
        {"identification": {"records_from_databases": 7475, "duplicates_removed": 900}},
        [{"source": "PubMed"}, {"source": "Scopus"}])), False)
    print("\nSELFTEST: %d/%d assertions pass" % (passed, n))
    return 0 if ok else 1

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--root", default=REPO)
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    probs = collect(a.root)
    if probs:
        print("FAIL - %d integrity problem(s):" % len(probs))
        for x in probs[:30]:
            print("  - %s" % x)
        return 2
    print("OK - cross-artifact review integrity consistent (R/C/C2/D/M/E/X/T/W/P)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
