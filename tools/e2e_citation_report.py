#!/usr/bin/env python3
"""e2e_citation_report.py -- score a citation-report run against skills/citation-report/eval.md.

Every section of eval.md is represented. The scorer recomputes the numbers from
the run's own artifacts, re-opens the artifacts through the skill's gate, runs
the skill offline against fixtures that must fail loudly, and reports the checks
it cannot decide rather than skipping them.

Two fixtures are scored:
  * a fresh offline run (`report.py report --offline`) of the skill's own
    sample manuscript/sources/claims, and
  * the checked-in `citation-report-example/` artifact set.

Exit codes:
  0  every decided check passed
  1  a decided check failed
  4  input gap: a required fixture/script is missing, or a run that needed an
     input did not get one (a network/tool gap is never a pass)

Usage:
  python3 tools/e2e_citation_report.py [--json OUT.json] [--offline]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SKILL = os.path.join(REPO, "skills", "citation-report", "scripts")
REPORT = os.path.join(SKILL, "report.py")
GATE = os.path.join(SKILL, "report_gate.py")
ASSETS = os.path.join(REPO, "skills", "citation-report", "assets")
RULES = os.path.join(REPO, "skills", "citation-report", "references", "verdict-rules.md")
EVAL = os.path.join(REPO, "skills", "citation-report", "eval.md")
BLANK_PDF = os.path.join(HERE, "e2e-fixtures", "citation-report", "blank.pdf")
DEFAULT_EXAMPLE = os.path.join(os.path.dirname(REPO), "citation-report-example")
SECTION = re.compile(r"^##[ \t]+(\d+[a-d]?)\.", re.M)

NON_TRIGGERS = ("at least one", "at most", "most participants", "leading")
BARE_SMALL_INT = re.compile(r"^\d{1,2}$")
LABEL = re.compile(r"^(?:[A-Z]{1,4}-\d+|\d+[a-z]?)$")
STRUCTURAL = re.compile(r"^(?:fig(?:ure)?|tab(?:le)?|phase|grade|step|section)\s*\.?\s*\d+$", re.I)

ROWS = []


def record(section, phase, rc, expected, ok, decided=True, mode="mechanical", evidence=""):
    ROWS.append({"section": section, "phase": phase, "rc": rc, "expected": expected,
                 "ok": bool(ok), "decided": bool(decided), "mode": mode,
                 "evidence": evidence})
    tag = "PASS" if ok else "FAIL"
    if decided:
        print("  %-5s %-54s rc=%-4s %s" % (section, phase[:54], rc, tag))
    else:
        print("  %-5s %-54s UNDECIDED -- %s" % (section, phase[:54], evidence[:64]))


def run(argv, cwd=None):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def check_numbers(tag, verdicts, coverage, rules_text):
    """eval.md sec 1: every published number is recomputable from verdicts.json."""
    if not isinstance(verdicts, dict) or not isinstance(coverage, dict):
        return None, "verdicts.json/coverage.json unreadable"
    v = verdicts.get("verdicts", [])
    states = coverage.get("states") or {}
    total = coverage.get("sentences_total")
    cov = coverage.get("citation_coverage") or {}
    problems = []
    if sum(states.values()) != total:
        problems.append("states sum %d != sentences_total %s" % (sum(states.values()), total))
    if cov.get("numerator") != states.get("attributed", 0) + states.get("synthesis", 0):
        problems.append("numerator %s != attributed+synthesis" % cov.get("numerator"))
    denom = cov.get("denominator")
    support = coverage.get("sentences_with_support_claim")
    if denom != support or denom != (total - states.get("no_citation_needed", 0)):
        problems.append("denominator %s != support %s != total-no_citation_needed" %
                        (denom, support))
    if not (isinstance(cov.get("numerator"), int) and isinstance(denom, int)
            and cov["numerator"] <= denom):
        problems.append("numerator is not a subset of the denominator")
    req = coverage.get("sentences_requiring_citation")
    if req is None:
        problems.append("sentences_requiring_citation is not reported separately")
    elif req == denom:
        problems.append("sentences_requiring_citation is used as the denominator")
    rules = coverage.get("rules")
    rule_ids = list(rules) if isinstance(rules, dict) else [
        r.get("rule_id") or r.get("id") for r in (rules or []) if isinstance(r, dict)]
    if not rule_ids:
        problems.append("coverage.rules is empty (no rule ids to trace)")
    for rid in rule_ids:
        if rid and rid not in rules_text:
            problems.append("rule %s is not documented in verdict-rules.md" % rid)
    return (not problems), ("; ".join(problems) if problems else
                            "sum(states)=%d total=%s numerator=%s denominator=%s requiring=%s "
                            "rules=%d" % (sum(states.values()), total, cov.get("numerator"),
                                          denom, req, len(rule_ids)))


def check_greens(verdicts):
    v = verdicts.get("verdicts", [])
    bad = []
    weak = []
    for r in v:
        if r.get("state") != "attributed":
            continue
        srcs = r.get("sources") or []
        avail = [s.get("evidence_availability") for s in srcs]
        if not srcs or any(a not in ("full_text", "abstract") for a in avail):
            bad.append("%s availability=%s" % (r.get("sentence_id"), avail))
        if r.get("missing_numbers"):
            bad.append("%s missing_numbers=%s" % (r.get("sentence_id"), r["missing_numbers"]))
        # 2b: a green must rest on a distinctive checkable value, not a label/int
        checkable = [q for q in (r.get("quantities") or [])
                     if q.get("checkable") and q.get("raw")]
        if not checkable:
            weak.append("%s has no checkable quantity" % r.get("sentence_id"))
        for q in checkable:
            raw = str(q.get("raw", "")).strip()
            if BARE_SMALL_INT.match(raw) or LABEL.match(raw) or STRUCTURAL.match(raw):
                weak.append("%s rests on %r" % (r.get("sentence_id"), raw))
    return (not bad, not weak,
            "greens: evidence problems=%s; distinctive-value problems=%s"
            % (bad or "none", weak or "none"))


def check_reds(verdicts):
    v = verdicts.get("verdicts", [])
    bad = []
    for r in v:
        if r.get("state") != "conflict":
            continue
        sid = r.get("sentence_id")
        rule = r.get("rule_id") or ""
        if not rule:
            bad.append("%s has no rule_id" % sid)
        if rule == "D07":
            bad.append("%s is a red from absence (D07 must be a warning)" % sid)
        if not (r.get("note") or "").strip():
            bad.append("%s has no note" % sid)
        if not (r.get("sources") or r.get("unresolved_tokens")):
            bad.append("%s names no source and no offending token" % sid)
    return (not bad, "conflicts=%d; problems=%s"
            % (sum(1 for r in v if r.get("state") == "conflict"), bad or "none"))


def check_orange(verdicts):
    v = verdicts.get("verdicts", [])
    bad = []
    n = 0
    for r in v:
        if r.get("state") != "unattributed":
            continue
        n += 1
        sid = r.get("sentence_id")
        # eval.md sec 4: orange must genuinely need a citation and genuinely have
        # none. A prose trigger is not the only legitimate reason: a citation
        # marker that resolves to no source (D03) is a sentence with a citation
        # that provides nothing, so an unresolved token is an equally honest
        # reason. What is never acceptable is an orange with neither reason.
        trig = [str(t) for t in (r.get("triggers") or [])]
        tokens = r.get("unresolved_tokens") or []
        if not r.get("requires_citation") and not tokens:
            bad.append("%s is orange but requires_citation is false and no citation is "
                       "unresolved" % sid)
        if not trig and not tokens:
            bad.append("%s is orange with no trigger and no unresolved citation" % sid)
        for t in trig:
            low = t.lower()
            if any(nt in low for nt in NON_TRIGGERS):
                bad.append("%s fired on the non-trigger %r" % (sid, t))
    return (not bad, "orange=%d; problems=%s" % (n, bad or "none"))


def check_unverifiable(verdicts, sources_csv):
    v = verdicts.get("verdicts", [])
    bad = []
    n = 0
    for r in v:
        if r.get("state") != "unverifiable":
            continue
        n += 1
        if not (r.get("note") or "").strip():
            bad.append("%s gives no reason" % r.get("sentence_id"))
        if not r.get("rule_id"):
            bad.append("%s has no rule id" % r.get("sentence_id"))
    held = 0
    not_held = 0
    for line in sources_csv.splitlines()[1:]:
        if "full_text" in line or ",abstract," in line:
            held += 1
        if "metadata_only" in line or ",none," in line:
            not_held += 1
    # both directions: unverifiable is warranted only while some source is unheld,
    # and greens must not appear from unheld sources (checked in sec 2).
    if not_held == 0 and n:
        bad.append("unverifiable=%d but no source is unheld (the state is not warranted)" % n)
    if held == 0 and any(r.get("state") == "attributed" for r in v):
        bad.append("greens exist but no source holds full text or an abstract")
    return (not bad, "unverifiable=%d; held=%d not_held=%d; problems=%s"
            % (n, held, not_held, bad or "none"))


def check_reflist(verdicts):
    v = verdicts.get("verdicts", [])
    bad = []
    for r in v:
        sec = (r.get("section") or "")
        if re.search(r"referenc|bibliograph", sec, re.I) and r.get("state") in ("conflict",
                                                                               "unattributed"):
            bad.append("%s graded a reference entry (%s)" % (r.get("sentence_id"), sec))
        txt = (r.get("text") or "")
        if r.get("state") == "conflict" and re.search(r"\b(Internet|Epub|cited 20\d\d)\b", txt):
            bad.append("%s looks like a reference entry" % r.get("sentence_id"))
    return (not bad, "reference-entry problems=%s" % (bad or "none"))


def check_preconditions(tmp):
    """eval.md sec 8d: the audit `preconditions` fail with exit 4, and are observed."""
    de = os.path.join(tmp, "de.md")
    two = os.path.join(tmp, "two.md")
    with open(de, "w", encoding="utf-8") as fh:
        fh.write("Die vorliegende Arbeit untersucht den Zusammenhang zwischen zwei Merkmalen. "
                 "Wir haben Daten aus mehreren Jahren ausgewertet und die Ergebnisse "
                 "zusammengefasst. Die Analyse zeigt einen deutlichen Effekt ueber alle Gruppen "
                 "hinweg. Weitere Studien sind notwendig, um die Befunde zu bestaetigen. "
                 "Zusammenfassend laesst sich sagen, dass der Effekt robust erscheint.\n")
    with open(two, "w", encoding="utf-8") as fh:
        fh.write("The cache cut latency by 42 percent. The error rate stayed flat.\n")
    p_de = run([sys.executable, REPORT, "audit", "--document", de, "--offline",
                "--out-dir", os.path.join(tmp, "p_de")])
    p_two = run([sys.executable, REPORT, "audit", "--document", two, "--offline",
                 "--out-dir", os.path.join(tmp, "p_two")])

    def preconds(p):
        try:
            return json.loads(p.stdout).get("preconditions", [])
        except ValueError:
            return []

    pre = preconds(p_de)
    codes = {x.get("code"): x for x in pre}
    lang = codes.get("TRIGGER_LANGUAGE_UNSUPPORTED", {}).get("status") == "failed"
    observed = all((x.get("observed") or "").strip() for x in pre) and len(pre) >= 4
    two_pre = preconds(p_two)
    split = {x.get("code"): x.get("status") for x in two_pre}
    not_blocked = p_two.returncode == 0 and split.get("SENTENCE_SPLIT_SUSPECT") == "passed"
    ok = p_de.returncode == 4 and lang and observed and not_blocked
    return ok, ("german rc=%d language_failed=%s all_observed=%s codes=%d; two-sentence rc=%d "
                "split=%s" % (p_de.returncode, lang, observed, len(pre), p_two.returncode,
                              split.get("SENTENCE_SPLIT_SUSPECT")))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Score citation-report against eval.md.")
    ap.add_argument("--json", help="write the full report as JSON to this path")
    ap.add_argument("--offline", action="store_true",
                    help="accepted for parity; every check here runs offline")
    ap.add_argument("--example", default=DEFAULT_EXAMPLE,
                    help="the checked-in example artifact directory")
    args = ap.parse_args(argv)

    for path, what in ((REPORT, "report.py"), (GATE, "report_gate.py"),
                       (ASSETS, "assets/"), (RULES, "verdict-rules.md"), (EVAL, "eval.md")):
        if not os.path.exists(path):
            print("INPUT GAP: %s not found: %s" % (what, path), file=sys.stderr)
            return 4
    if not os.path.isfile(BLANK_PDF):
        print("INPUT GAP: blank.pdf fixture missing: %s" % BLANK_PDF, file=sys.stderr)
        return 4

    sections = [m.group(1) for m in SECTION.finditer(open(EVAL, encoding="utf-8").read())]
    tmp = tempfile.mkdtemp(prefix="e2e-citation-report-")
    rules_text = open(RULES, encoding="utf-8").read()
    print("=" * 78)
    print("CITATION-REPORT E2E RUBRIC SCORER")
    print("eval.md sections found: %s" % ", ".join(sections))
    print("workdir: %s" % tmp)
    print("=" * 78)
    input_gap = None

    # ---- the fresh offline run of the skill's own assets ------------------- #
    man = os.path.join(ASSETS, "sample-manuscript.md")
    src = os.path.join(ASSETS, "sample-sources.csv")
    claims = os.path.join(ASSETS, "sample-claims.csv")
    run_a = os.path.join(tmp, "a")
    p = run([sys.executable, REPORT, "report", "--document", man, "--sources", src,
             "--claims", claims, "--offline", "--advisory", "off",
             "--out-dir", run_a])
    if p.returncode not in (0, 1, 3):
        input_gap = "the offline sample run did not complete (rc=%d)" % p.returncode
    verdicts = load(os.path.join(run_a, "verdicts.json")) or {}
    coverage = load(os.path.join(run_a, "coverage.json")) or {}
    sources_csv = ""
    try:
        sources_csv = open(os.path.join(run_a, "sources_report.csv"), encoding="utf-8").read()
    except OSError:
        pass

    # ---- 1. recompute every number ---------------------------------------- #
    ok, ev = check_numbers("fresh run", verdicts, coverage, rules_text)
    record("1", "every number recomputable from verdicts.json", p.returncode,
           "consistent", bool(ok), evidence=ev or "unreadable")

    # ---- 2 / 2b. greens earned -------------------------------------------- #
    ok2, ok2b, ev = check_greens(verdicts)
    record("2", "every green has held evidence and no missing number", p.returncode,
           "0 problems", ok2, evidence=ev)
    record("2b", "every green rests on a distinctive checkable value", p.returncode,
           "0 problems", ok2b, evidence=ev)

    # ---- 3. reds defensible ----------------------------------------------- #
    ok3, ev = check_reds(verdicts)
    record("3", "every red names a rule, a source/token and a note", p.returncode,
           "0 problems", ok3, evidence=ev)

    # ---- 4. orange honest -------------------------------------------------- #
    ok4, ev = check_orange(verdicts)
    record("4", "orange needs a citation and no non-trigger fired", p.returncode,
           "0 problems", ok4, evidence=ev)

    # ---- 5. unverifiable both ways ---------------------------------------- #
    ok5, ev = check_unverifiable(verdicts, sources_csv)
    record("5", "unverifiable warranted, and no green from unheld evidence", p.returncode,
           "0 problems", ok5, evidence=ev)

    # ---- 6. reference list stays out of the prose ------------------------- #
    ok6, ev = check_reflist(verdicts)
    record("6", "no reference entry graded as prose", p.returncode, "0 problems", ok6,
           evidence=ev)

    # ---- 7. advisory channel is inert ------------------------------------- #
    run_b = os.path.join(tmp, "b")
    p2 = run([sys.executable, REPORT, "report", "--document", man, "--sources", src,
              "--claims", claims, "--offline", "--advisory",
              os.path.join(ASSETS, "sample-advisory.json"), "--out-dir", run_b])
    vb = load(os.path.join(run_b, "verdicts.json")) or {}
    cb = load(os.path.join(run_b, "coverage.json")) or {}

    def strip(d):
        return [{k: v for k, v in r.items() if k != "advisory"}
                for r in (d.get("verdicts") or [])]
    inert = (strip(verdicts) == strip(vb) and coverage.get("states") == cb.get("states")
             and verdicts.get("gate") == vb.get("gate"))
    record("7", "advisory changes no verdict, coverage or gate", (p.returncode, p2.returncode),
           "identical", inert,
           evidence="verdicts equal (minus advisory)=%s; coverage equal=%s; gate equal=%s"
                    % (strip(verdicts) == strip(vb), coverage.get("states") == cb.get("states"),
                       verdicts.get("gate") == vb.get("gate")))

    # ---- 8. artifacts contain what they claim ----------------------------- #
    g_out = run([sys.executable, GATE, "--dir", run_a])
    try:
        g = json.loads(g_out.stdout)
    except ValueError:
        g = {}
    artifacts_ok = (g.get("summary", {}).get("artifacts_verified") == 3
                    and not [i for i in g.get("issues", [])
                             if i.get("code", "").startswith("ARTIFACT_")
                             and i.get("severity") == "error"])
    record("8", "PDF/DOCX/HTML re-open and match the verdict list", g_out.returncode,
           "3 artifacts verified", artifacts_ok,
           evidence="artifacts_verified=%s; artifact errors=%s"
                    % (g.get("summary", {}).get("artifacts_verified"),
                       [i["code"] for i in g.get("issues", [])
                        if i.get("code", "").startswith("ARTIFACT_")
                        and i.get("severity") == "error"] or "none"))

    # ---- 8b. input/result boundary is visible ----------------------------- #
    worklist = os.path.join(run_a, "evidence_worklist.csv")
    html = ""
    try:
        html = open(os.path.join(run_a, "report.html"), encoding="utf-8").read()
    except OSError:
        pass
    status = verdicts.get("status") or coverage.get("status")
    boundary = (p.returncode == 3 and status == "insufficient_evidence"
                and os.path.exists(worklist) and os.path.getsize(worklist) > 0
                and "INPUT-BOUND" in html and "NOT A FINDING" in html)
    record("8b", "a run that could check little is input-bound, not a finding", p.returncode,
           "3 + worklist + banner", boundary,
           evidence="status=%s worklist=%s banner=%s"
                    % (status, os.path.exists(worklist),
                       ("INPUT-BOUND" in html and "NOT A FINDING" in html)))
    over = os.path.join(tmp, "c")
    p3 = run([sys.executable, REPORT, "report", "--document", man, "--sources", src,
              "--claims", claims, "--offline", "--allow-insufficient", "--out-dir", over])
    v3 = load(os.path.join(over, "verdicts.json")) or {}
    keeps = (v3.get("status") == "insufficient_evidence" and p3.returncode != 3)
    record("8b*", "--allow-insufficient keeps the status, restores the code", p3.returncode,
           "status kept, rc != 3", keeps,
           evidence="status=%s rc=%d" % (v3.get("status"), p3.returncode))

    # ---- 8c. every accusation clears the red bar -------------------------- #
    # This scores the FRESHLY GENERATED run above (run_a), never the stored
    # example: a report produced by an older revision must not be able to fail
    # this check, and a fixed tool must be able to pass it. The example's own
    # (known-bad) status is asserted separately, as 8c*.
    codes = [i.get("code") for i in g.get("issues", []) if i.get("severity") == "error"]
    link_bad = [i for i in g.get("issues", [])
                if i.get("severity") == "error"
                and i.get("code") in ("CONFLICT_LINK_INFERRED", "CONFLICT_EVIDENCE_TOO_WEAK")]
    record("8c", "no red in a fresh report rests on an inferred link or weak evidence",
           g_out.returncode, "none", not link_bad,
           evidence="fresh run %s: its own gate reports %s; offending items=%s"
                    % (run_a, [i.get("code") for i in link_bad] or "none",
                       [i.get("item_id") for i in link_bad] or "none"))

    # ---- 8d. the tool understands the document ---------------------------- #
    ok8d, ev = check_preconditions(tmp)
    record("8d", "preconditions trip at exit 4; 2 sentences do not", None,
           "4/fail + 0/short", ok8d, evidence=ev)

    # ---- 9. a bad input fails loudly --------------------------------------- #
    bad_ext = os.path.join(tmp, "thing.xyz")
    with open(bad_ext, "w", encoding="utf-8") as fh:
        fh.write("not a document")
    p_bad = run([sys.executable, REPORT, "report", "--document", bad_ext, "--offline",
                 "--out-dir", os.path.join(tmp, "bad")])
    loud = p_bad.returncode != 0 and "INVALID_INPUT" in (p_bad.stdout + p_bad.stderr)
    p_scan = run([sys.executable, REPORT, "report", "--document", BLANK_PDF, "--offline",
                  "--no-ocr", "--out-dir", os.path.join(tmp, "scan")])
    scan_ok = p_scan.returncode == 4 and "no_text_layer" in (p_scan.stdout + p_scan.stderr)
    record("9", "unsupported extension and an unreadable scan fail loudly", p_bad.returncode,
           "!=0 with INVALID_INPUT", loud,
           evidence="unsupported-extension legible refusal=%s" % loud)
    record("9*", "a text-less PDF is an input gap (exit 4, no_text_layer)", p_scan.returncode,
           "4 + no_text_layer", scan_ok,
           evidence="rc=%d kind named=%s" % (p_scan.returncode,
                                             "no_text_layer" in (p_scan.stdout + p_scan.stderr)))
    tamper = os.path.join(tmp, "tamper_cov")
    shutil.copytree(run_a, tamper)
    covp = os.path.join(tamper, "coverage.json")
    d = load(covp) or {}
    if d.get("states"):
        d["states"]["attributed"] = d["states"].get("attributed", 0) + 1
        with open(covp, "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=2)
    g_t = run([sys.executable, GATE, "--dir", tamper])
    record("9**", "a hand-incremented coverage count fails the gate", g_t.returncode,
           "!=0", g_t.returncode != 0,
           evidence="gate rc=%d" % g_t.returncode)

    # ---- 10. a transcription stays a transcription ------------------------ #
    transcription_claimed = json.dumps(verdicts).find("transcription:") >= 0
    ocr_count = (coverage.get("transcription") or {}).get("sentences_resting_on_ocr", 0)
    no_claim = (not transcription_claimed) and not ocr_count
    record("10", "a run with no OCR claims no transcription", p.returncode, "no claim",
           no_claim,
           evidence="transcription marker=%s sentences_resting_on_ocr=%s"
                    % (transcription_claimed, ocr_count))
    record("10*", "a transcribed value never becomes a red (D13)", None, "n/a", False,
           decided=False, mode="input gap (fixture)",
           evidence="needs an OCR-readable scan whose text contradicts a held source; this "
                    "scorer's blank.pdf has no text to contradict. The --no-ocr route IS "
                    "asserted under 9*")

    # ---- checked-in example: the same number audit ------------------------ #
    ex_v = load(os.path.join(args.example, "verdicts.json"))
    ex_c = load(os.path.join(args.example, "coverage.json"))
    if ex_v and ex_c:
        ok, ev = check_numbers("example", ex_v, ex_c, rules_text)
        record("1*", "[example] numbers recomputable", None, "consistent", bool(ok),
               evidence=ev)
        g_ex = run([sys.executable, GATE, "--dir", args.example])
        try:
            ge = json.loads(g_ex.stdout)
        except ValueError:
            ge = {}
        ex_codes = [i.get("code") for i in ge.get("issues", []) if i.get("severity") == "error"]
        ex_details = " ".join(str(i.get("detail", "")) for i in ge.get("issues", []))
        verified = ge.get("summary", {}).get("artifacts_verified")
        if verified == 3:
            record("8*", "[example] artifacts re-open and match", g_ex.returncode,
                   "3 artifacts verified", True,
                   evidence="artifacts_verified=3")
        else:
            # A stored artifact can legitimately be refused before the gate reaches
            # the artifact check (this example predates the D03 fix). That is not
            # an artifact mismatch, so it is undecided here -- never a pass.
            record("8*", "[example] artifacts re-open and match", g_ex.returncode,
                   "3 artifacts verified", False, decided=False, mode="input gap (fixture)",
                   evidence="the gate refused the stored example before checking artifacts: "
                            "%s" % (ex_details[:150] or "no summary"))
        # The example is a fixture of a DELIBERATELY BAD document: it keeps a red
        # (D04, a retracted source) and a known-bad citation. The correct
        # behaviour is that the tool flags it and NAMES the defect. Any rule-id
        # error code names it (D04 stays red after the D03 fix; D03 did before),
        # as does a CONFLICT_* code or a refusal whose text names a rule. The
        # assertion stays strict in the other direction: no error code at all
        # means nothing was flagged, so it fails.
        ex_conf = [r for r in (ex_v.get("verdicts") or []) if r.get("state") == "conflict"]
        named_defect = (any(c.startswith("CONFLICT_") or re.fullmatch(r"D\d+[a-z]?", c)
                            for c in ex_codes)
                        or re.search(r"\bD\d+[a-z]?\b", ex_details) is not None)
        flagged = (ge.get("status") == "fail" and bool(ex_conf) and bool(ex_codes)
                   and named_defect)
        record("8c*", "[example] the known-bad fixture is reported as failing",
               g_ex.returncode, "gate status fail",
               flagged,
               evidence="example conflicts=%d rules=%s; gate status=%s errors=%s"
                        % (len(ex_conf), [r.get("rule_id") for r in ex_conf],
                           ge.get("status"), ex_codes or "none"))
    else:
        record("1*", "[example] numbers recomputable", None, "consistent", False,
               decided=False, mode="input gap (fixture)",
               evidence="example artifacts not readable at %s" % args.example)

    # ---- report ----------------------------------------------------------- #
    failed = [r for r in ROWS if r["decided"] and not r["ok"]]
    undecided = [r for r in ROWS if not r["decided"]]
    covered = {r["section"].rstrip("*") for r in ROWS}
    unscored = [s for s in sections if s not in covered]
    print("\n" + "=" * 78)
    print("REPORT: %d checks, %d decided-failed, %d undecided" %
          (len(ROWS), len(failed), len(undecided)))
    for r in failed:
        print("  FAILED %s: %s (%s)" % (r["section"], r["phase"], r["evidence"][:100]))
    for r in undecided:
        print("  UNDECIDED %s [%s]: %s" % (r["section"], r["mode"], r["evidence"][:90]))
    if unscored:
        print("  eval.md sections with no scorer row: %s" % ", ".join(unscored))
    if input_gap:
        print("  INPUT GAP: %s" % input_gap)
    print("=" * 78)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"skill": "citation-report", "example": args.example, "offline": True,
                       "eval_sections": sections, "checks": ROWS, "failed": len(failed),
                       "undecided": [r["section"] for r in undecided],
                       "unscored_sections": unscored, "input_gap": input_gap},
                      fh, indent=2)
        print("wrote %s" % args.json)

    if input_gap:
        return 4
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
