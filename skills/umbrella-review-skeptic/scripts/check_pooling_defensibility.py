#!/usr/bin/env python3
"""check_pooling_defensibility.py -- can these reviews be pooled at all?

An umbrella review pools the estimates of existing reviews. That pool is defensible
only when the reviews do not reuse the same primary studies too heavily, when their
effects share a metric and a construct, and when the dependence is modelled or
sensitivity-tested. This gate decides those three conditions from two files:

  --effects  a review-level effect table (review_id, effect_metric, outcome_family,
             effect_estimate)
  --overlap  a primary-study by review matrix (first column = primary_study_id,
             one column per review, a truthy mark where the review includes the study)

The overlap rule is the one this project already recorded: a pair of reviews that
shares more than 30% of its primary studies is flagged
(references/agricultural-diversification-second-order-meta.md, rule 9). The share is
shared / min(studies in review A, studies in review B). State that definition in the
report, because a different denominator gives a different number.

Two conditions must never collapse into one another:

  * a review whose primary-study list could not be read, or a review with no column
    in the matrix, is an INPUT GAP. The gate then reports no verdict at all -- a
    pooling recommendation over a partial matrix is a claim about evidence nobody
    read;
  * a pair that shares more than the threshold, or two metrics that cannot be
    compared, is a FINDING about the evidence.

Exit codes (the repository's convention):
  0  the synthesis is defensible (pooling allowed, or narrative synthesis preferred)
  1  usage error
  2  at least one finding -- pooling is NOT defensible as requested
  3  input gap: a primary-study list could not be read (status insufficient_evidence;
     no verdict is emitted). --allow-insufficient lowers the exit code to 0 and
     leaves the status and the gap in the report
  4  insufficient_input: a supplied file is missing or unparseable

Usage:
  python3 check_pooling_defensibility.py --effects effects.csv --overlap overlap.csv
  python3 check_pooling_defensibility.py --effects effects.csv --overlap overlap.csv \
      --pool [--dependence-handled] [--threshold 0.30] [--out report.json]
  python3 check_pooling_defensibility.py --self-test
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import sys
from pathlib import Path

# The project already records this rule; do not change it here without changing the
# reference. See references/agricultural-diversification-second-order-meta.md, rule 9.
DEFAULT_THRESHOLD = 0.30

REQUIRED_EFFECT_COLUMNS = ["review_id", "effect_metric", "outcome_family"]

TRUTHY = {"1", "x", "yes", "y", "true", "present", "included"}
UNREADABLE = {"?", "unreadable", "unknown", "n/a", "na", "tbd"}

VERDICT_POOL = "defensible_pooling"
VERDICT_INDEFENSIBLE = "indefensible_pooling"
VERDICT_NARRATIVE = "narrative_synthesis"


class InsufficientInput(Exception):
    """A supplied file could not be read: exit 4, never a finding."""


def read_csv(path):
    if not Path(path).is_file():
        raise InsufficientInput("file not found: %s" % path)
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise InsufficientInput("could not parse %s: %s" % (path, exc))
    if rows and None in rows[0]:
        raise InsufficientInput("%s has a ragged header row" % path)
    return rows


def load_effects(path):
    """Return (metric_by_review, problems). An empty table is an input gap."""
    rows = read_csv(path)
    if not rows:
        raise InsufficientInput("no data rows in %s" % path)
    columns = set(rows[0].keys())
    missing = [c for c in REQUIRED_EFFECT_COLUMNS if c not in columns]
    if missing:
        raise InsufficientInput("%s is missing column(s): %s" % (path, ", ".join(missing)))
    metrics, families, order = {}, {}, []
    for row in rows:
        rid = (row.get("review_id") or "").strip()
        if not rid:
            raise InsufficientInput("%s has a row with no review_id" % path)
        if rid not in metrics:
            order.append(rid)
            metrics[rid] = set()
            families[rid] = set()
        metric = (row.get("effect_metric") or "").strip()
        if metric:
            metrics[rid].add(metric.lower())
        family = (row.get("outcome_family") or "").strip()
        if family:
            families[rid].add(family.lower())
    return metrics, families, order


def load_overlap(path, reviews):
    """Return (marks, review_columns, unreadable, ragged).

    marks[study][review] is True where the review includes the study.
    unreadable lists (review, reason) for a review we cannot assess.
    """
    rows = read_csv(path)
    if not rows:
        raise InsufficientInput("no rows in %s" % path)
    header = list(rows[0].keys())
    if len(header) < 2:
        raise InsufficientInput("%s needs an id column and at least one review column" % path)
    id_column, review_columns = header[0], header[1:]
    marks = {}
    unreadable = []
    for review in review_columns:
        marked = unreadable_cell = 0
        for row in rows:
            study = (row.get(id_column) or "").strip()
            if not study:
                continue
            cell = (row.get(review) or "").strip().lower()
            if cell in UNREADABLE:
                unreadable_cell += 1
                continue
            if cell in TRUTHY:
                marked += 1
                marks.setdefault(study, set()).add(review)
        if marked == 0 or unreadable_cell:
            unreadable.append((review, "%d marked, %d unreadable cell(s)"
                               % (marked, unreadable_cell)))
    for review in reviews:
        if review not in review_columns:
            unreadable.append((review, "no column in the overlap matrix"))
    return marks, review_columns, unreadable


def pair_overlap(marks, reviews):
    """Return one record per review pair, with the shared-study share."""
    counts = {r: 0 for r in reviews}
    for _study, reviewers in marks.items():
        for r in reviewers:
            if r in counts:
                counts[r] += 1
    pairs = []
    for i, a in enumerate(reviews):
        for b in reviews[i + 1:]:
            shared = 0
            for _study, reviewers in marks.items():
                if a in reviewers and b in reviewers:
                    shared += 1
            smaller = min(counts[a], counts[b])
            share = (shared / smaller) if smaller else None
            pairs.append({"review_a": a, "review_b": b, "shared": shared,
                          "studies_a": counts[a], "studies_b": counts[b],
                          "share": None if share is None else round(share, 4)})
    return pairs, counts


def assess(metrics, families, order, marks, review_columns, unreadable,
           threshold, pool, dependence_handled):
    """Build the full report. Never mixes a gap into the findings."""
    findings, cautions, input_gaps = [], [], []
    for review, reason in unreadable:
        input_gaps.append({
            "review": review,
            "reason": reason,
            "action": "read the primary-study list for %s and re-run; no pooling "
                      "recommendation is made while this list is unknown" % review,
        })
    reviews = [r for r in order if r in review_columns and
               r not in {u for u, _ in unreadable}]
    pairs, counts = pair_overlap(marks, review_columns)
    overlap_pairs = []
    for pair in pairs:
        if pair["share"] is None:
            continue
        if pair["share"] > threshold:
            overlap_pairs.append(pair)
    for pair in overlap_pairs:
        text = ("%s and %s share %d primary stud%s (%.0f%%, above the %.0f%% rule)"
                % (pair["review_a"], pair["review_b"], pair["shared"],
                   "y" if pair["shared"] == 1 else "ies",
                   100 * pair["share"], 100 * threshold))
        if pool and not dependence_handled:
            findings.append({"rule": "overlap", "detail": text,
                             "action": "state the overlap, then model or sensitivity-test "
                                       "the dependence before you pool"})
        else:
            cautions.append({"rule": "overlap", "detail": text})

    mixed = [r for r in order if len(metrics.get(r, set())) > 1]
    family_mix = [r for r in order if len(families.get(r, set())) > 1]
    for review in mixed:
        findings.append({"rule": "metric", "detail": "%s reports more than one effect "
                         "metric" % review,
                         "action": "split the analysis by metric or record a defensible "
                                   "conversion"})
    for review in family_mix:
        cautions.append({"rule": "outcome_family", "detail": "%s reports more than one "
                         "outcome family" % review})

    distinct = set()
    for r in order:
        distinct |= metrics.get(r, set())
    if pool and len(distinct) > 1 and not dependence_handled:
        findings.append({"rule": "metric_mismatch",
                         "detail": "the review-level metrics differ: %s"
                                   % ", ".join(sorted(distinct)),
                         "action": "harmonise the metric with a stated conversion, or "
                                   "prefer narrative synthesis"})
    if pool and len(order) < 2:
        findings.append({"rule": "review_count",
                         "detail": "pooling needs at least two reviews, found %d"
                                   % len(order),
                         "action": "add the missing reviews or drop the pooling request"})

    if input_gaps:
        status, verdict = "insufficient_evidence", None
    elif findings:
        status = "fail"
        verdict = VERDICT_INDEFENSIBLE if pool else VERDICT_NARRATIVE
    else:
        status = "pass"
        verdict = VERDICT_POOL if pool else VERDICT_NARRATIVE
    return {
        "tool": "check_pooling_defensibility",
        "status": status,
        "verdict": verdict,
        "threshold": threshold,
        "share_definition": "shared / min(studies in review A, studies in review B)",
        "pooling_requested": pool,
        "dependence_handled": dependence_handled,
        "reviews": order,
        "studies_per_review": counts,
        "pairs": pairs,
        "overlap_pairs": overlap_pairs,
        "findings": findings,
        "cautions": cautions,
        "input_gaps": input_gaps,
    }


def run(effects_path, overlap_path, threshold, pool, dependence_handled,
        allow_insufficient, out_path):
    try:
        metrics, families, order = load_effects(effects_path)
        marks, review_columns, unreadable = load_overlap(overlap_path, order)
    except InsufficientInput as exc:
        report = {
            "tool": "check_pooling_defensibility",
            "status": "insufficient_input",
            "verdict": None,
            "findings": [],
            "cautions": [],
            "input_gaps": [{"review": None, "reason": str(exc),
                            "action": "supply the file and re-run; no verdict is emitted"}],
        }
        print("insufficient_input: %s" % exc, file=sys.stderr)
        if out_path:
            Path(out_path).write_text(json.dumps(report, indent=1), encoding="utf-8")
        return 4, report

    report = assess(metrics, families, order, marks, review_columns, unreadable,
                    threshold, pool, dependence_handled)
    if out_path:
        Path(out_path).write_text(json.dumps(report, indent=1), encoding="utf-8")

    print("status: %s" % report["status"])
    print("verdict: %s" % report["verdict"])
    for pair in report["overlap_pairs"]:
        print("  overlap: %s x %s  shared=%d  share=%.2f"
              % (pair["review_a"], pair["review_b"], pair["shared"], pair["share"]))
    for f in report["findings"]:
        print("  FAIL [%s] %s" % (f["rule"], f["detail"]))
        print("       action: %s" % f["action"])
    if report["input_gaps"]:
        print("INPUT GAP - the primary-study list of %d review(s) could not be read."
              % len(report["input_gaps"]))
        print("  This is a statement about the supplied matrix, NOT a pooling result.")
        for gap in report["input_gaps"]:
            print("  - %s: %s" % (gap["review"], gap["reason"]))
            print("    action: %s" % gap["action"])
        if not allow_insufficient:
            return 3, report
        print("  --allow-insufficient given: the status stays %s in the report; only the "
              "exit code falls back to the findings." % report["status"])
        return 0, report
    if report["findings"]:
        return 2, report
    return 0, report


# ---- self-test ------------------------------------------------------------
EFFECTS = """review_id,effect_metric,outcome_family,effect_estimate
R1,LnRR,yield,0.10
R2,LnRR,yield,0.12
"""


def _matrix(text, path):
    Path(path).write_text(text, encoding="utf-8")
    return str(path)


def self_test():
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="pooling-selftest-"))
    failures = []
    effects = tmp / "effects.csv"
    effects.write_text(EFFECTS, encoding="utf-8")

    def case(name, matrix, argv, want_code, want_status, want_verdict):
        overlap = _matrix(matrix, tmp / ("m-%s.csv" % name.replace(" ", "-")))
        with contextlib.redirect_stdout(io.StringIO()):
            code, report = run(str(effects), overlap, 0.30, argv[0], argv[1], False, None)
        if code != want_code:
            failures.append("%s: want exit %s, got %s" % (name, want_code, code))
        if report["status"] != want_status:
            failures.append("%s: want status %s, got %s" % (name, want_status, report["status"]))
        if report["verdict"] != want_verdict:
            failures.append("%s: want verdict %s, got %s"
                            % (name, want_verdict, report["verdict"]))

    # A defensible pool: two reviews of five studies that share one (20%).
    case("defensible",
         "primary_study_id,R1,R2\nS1,1,0\nS2,1,0\nS3,1,0\nS4,1,0\nS5,1,1\n"
         "S6,0,1\nS7,0,1\nS8,0,1\nS9,0,1\n",
         (True, False), 0, "pass", VERDICT_POOL)
    # An indefensible pool: 2 of 3 shared (67%), above the 30% rule.
    case("overlapping",
         "primary_study_id,R1,R2\nS1,1,1\nS2,1,1\nS3,1,0\n",
         (True, False), 2, "fail", VERDICT_INDEFENSIBLE)
    # Narrative synthesis is always available when the pool is not defensible.
    case("narrative",
         "primary_study_id,R1,R2\nS1,1,1\nS2,1,1\nS3,1,0\n",
         (False, False), 0, "pass", VERDICT_NARRATIVE)
    # An unreadable primary-study list is a gap, and it emits no verdict.
    case("gap",
         "primary_study_id,R1,R2\nS1,1,\nS2,1,\n",
         (True, False), 3, "insufficient_evidence", None)

    # The declared opt-out keeps the status and the gap; only the exit code changes.
    with contextlib.redirect_stdout(io.StringIO()):
        code, report = run(str(effects),
                           _matrix("primary_study_id,R1,R2\nS1,1,\nS2,1,\n", tmp / "opt.csv"),
                           0.30, True, False, True, None)
    if code != 0 or report["status"] != "insufficient_evidence" or report["verdict"] is not None:
        failures.append("opt-out changed the report: exit %s status %s verdict %s"
                        % (code, report["status"], report["verdict"]))
    if report["findings"]:
        failures.append("the input gap leaked into the findings channel")

    # A missing file is insufficient_input, not a finding.
    with contextlib.redirect_stdout(io.StringIO()):
        code, report = run(str(effects), str(tmp / "absent.csv"), 0.30, True, False, False, None)
    if code != 4 or report["status"] != "insufficient_input":
        failures.append("a missing matrix did not give exit 4 / insufficient_input")

    for msg in failures:
        print("FAIL  %s" % msg)
    print("check_pooling_defensibility self-test: 6 checks, %d failed" % len(failures))
    return 1 if failures else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--effects", help="review-level effect CSV")
    ap.add_argument("--overlap", help="primary-study by review matrix CSV")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--pool", action="store_true",
                    help="the user asks for a review-level statistical pool")
    ap.add_argument("--dependence-handled", action="store_true",
                    help="the plan models or sensitivity-tests the dependence")
    ap.add_argument("--allow-insufficient", action="store_true",
                    help="logged opt-out: keep the gap and lower the exit code")
    ap.add_argument("--out", default=None)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.effects or not args.overlap:
        print("check_pooling_defensibility: give --effects and --overlap (or --self-test)",
              file=sys.stderr)
        return 1
    code, _report = run(args.effects, args.overlap, args.threshold, args.pool,
                        args.dependence_handled, args.allow_insufficient, args.out)
    return code


if __name__ == "__main__":
    sys.exit(main())
