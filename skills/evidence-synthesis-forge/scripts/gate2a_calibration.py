#!/usr/bin/env python3
"""Gate 2a - screening calibration: pilot + BLIND second pass + agreement gate.

screening-governance.md requires a calibration pilot before the full screen. In autonomous
mode the agent performs the blind second pass itself; the metrics, the criteria lock and the
audit log are identical either way - only the identity of the auditor changes. Reporting
kappa as "not constructible in autonomous mode" is therefore incorrect, and this gate exists
so that claim cannot be made silently.

Reports ALL metrics, never kappa alone: Cohen's kappa (3-category and binary), raw %
agreement, PABAK in both forms, the marginal distributions with the kappa-paradox base-rate
caveat, and the direction of disagreement.

  python3 gate2a_calibration.py --pilot pilot/pilot_slice.csv --out ledgers/gate2a_calibration.json
  python3 gate2a_calibration.py --selftest

Pilot CSV columns: record_id, pass1, pass2 [, stratum]
  pass1 = decision under test;  pass2 = blind second-pass decision.
Exits non-zero when kappa < --threshold (default 0.60) or the pilot is under --min-n.
"""
import argparse
import csv
import json
import os
import sys

INCLUDE, EXCLUDE, UNCERTAIN = "INCLUDE", "EXCLUDE", "UNCERTAIN"
_ALIASES = {"INC": INCLUDE, "YES": INCLUDE, "Y": INCLUDE, "1": INCLUDE,
            "EXC": EXCLUDE, "EXCL": EXCLUDE, "NO": EXCLUDE, "N": EXCLUDE, "0": EXCLUDE,
            "?": UNCERTAIN, "UNK": UNCERTAIN, "DEFER": UNCERTAIN, "": UNCERTAIN}


def _norm(v):
    return _ALIASES.get((v or "").strip().upper(), (v or "").strip().upper())


def cohen_kappa(a, b, cats):
    """(kappa, po). kappa is None when the chance term is degenerate (pe == 1)."""
    n = len(a)
    if not n:
        return None, None
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    if pe >= 1.0:
        return (1.0 if po >= 1.0 else None), po
    return (po - pe) / (1.0 - pe), po


def pabak(po):
    return None if po is None else 2 * po - 1


def _r(x):
    return None if x is None else round(x, 4)


def analyse(rows, threshold=0.60, min_n=50):
    probs, notes = [], []
    n = len(rows)
    if n < min_n:
        probs.append("PILOT: %d record(s); governance requires >= %d fresh, stratified records"
                     % (n, min_n))
    p1 = [_norm(r.get("pass1")) for r in rows]
    p2 = [_norm(r.get("pass2")) for r in rows]
    unknown = sorted({v for v in p1 + p2 if v not in (INCLUDE, UNCERTAIN, EXCLUDE)})
    if unknown:
        probs.append("PILOT: unrecognised decision label(s): %s" % unknown)

    cats3 = [INCLUDE, UNCERTAIN, EXCLUDE]
    k3, po3 = cohen_kappa(p1, p2, cats3)
    # Binary collapse: UNCERTAIN -> INCLUDE, i.e. the sensitive direction. Stated, not implied.
    b1 = [EXCLUDE if v == EXCLUDE else INCLUDE for v in p1]
    b2 = [EXCLUDE if v == EXCLUDE else INCLUDE for v in p2]
    kb, pob = cohen_kappa(b1, b2, [INCLUDE, EXCLUDE])

    pe3 = sum((p1.count(c) / n) * (p2.count(c) / n) for c in cats3) if n else None
    if pe3 is not None and pe3 > 0.80:
        notes.append("base-rate caveat: chance agreement is %.2f (high), so kappa is depressed "
                     "by prevalence - a low kappa here reflects skewed marginals as much as "
                     "disagreement; read it with PABAK and the marginals below" % pe3)

    dis = [(a, b) for a, b in zip(p1, p2) if a != b]
    ie = sum(1 for a, b in dis if a == INCLUDE and b == EXCLUDE)
    ei = sum(1 for a, b in dis if a == EXCLUDE and b == INCLUDE)

    strata = {}
    for r in rows:
        s = (r.get("stratum") or "unspecified").strip() or "unspecified"
        strata[s] = strata.get(s, 0) + 1

    if k3 is not None and k3 < threshold:
        probs.append("PILOT: 3-category kappa %.3f < threshold %.2f - extract the disagreement-"
                     "derived rules, re-lock the criteria, and run a NEW pilot on fresh records"
                     % (k3, threshold))
    if kb is not None and kb < threshold:
        probs.append("PILOT: binary kappa %.3f < threshold %.2f" % (kb, threshold))

    return {
        "tool": "gate2a_calibration",
        "n": n, "min_n": min_n, "threshold": threshold,
        "kappa_3cat": _r(k3), "pct_agreement_3cat": _r(po3), "pabak_3cat": _r(pabak(po3)),
        "kappa_binary": _r(kb), "pct_agreement_binary": _r(pob), "pabak_binary": _r(pabak(pob)),
        "chance_agreement_3cat": _r(pe3),
        "marginals": {"pass1": {c: p1.count(c) for c in cats3},
                      "pass2": {c: p2.count(c) for c in cats3}},
        "disagreements": {"n": len(dis),
                          "pass1_INCLUDE_pass2_EXCLUDE": ie,
                          "pass1_EXCLUDE_pass2_INCLUDE": ei,
                          "dominant_direction": ("pass1 over-includes" if ie > ei else
                                                 "pass1 over-excludes" if ei > ie else "balanced")},
        "strata": strata,
        "notes": notes,
        "failures": probs,
        "gate": "FAIL" if probs else "PASS",
    }


def _load(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rd = csv.DictReader(fh)
        lower = {(k or "").lower(): k for k in (rd.fieldnames or [])}
        miss = [c for c in ("pass1", "pass2") if c not in lower]
        if miss:
            sys.exit("FAIL - pilot CSV is missing column(s): %s" % miss)
        return [{"record_id": r.get(lower.get("record_id", ""), ""),
                 "pass1": r.get(lower["pass1"], ""),
                 "pass2": r.get(lower["pass2"], ""),
                 "stratum": r.get(lower.get("stratum", ""), "")}
                for r in rd]


def selftest():
    ok, n, passed = True, 0, 0

    def case(label, got, expect):
        nonlocal ok, n, passed
        good = got == expect
        ok &= good
        n += 1
        passed += good
        print("%-4s %s (%s)" % ("OK" if good else "BAD", label, got))

    # hand-computable: 5 INCLUDE / 5 EXCLUDE, perfect agreement -> kappa 1.0
    perfect = [{"pass1": "INCLUDE", "pass2": "INCLUDE"} for _ in range(5)] + \
              [{"pass1": "EXCLUDE", "pass2": "EXCLUDE"} for _ in range(5)]
    r = analyse(perfect, min_n=0)
    case("perfect agreement -> kappa 1.0", r["kappa_3cat"], 1.0)
    case("perfect agreement -> PABAK 1.0", r["pabak_3cat"], 1.0)
    case("perfect agreement PASSES", r["gate"], "PASS")

    # total disagreement -> po 0, pe 0.5 -> kappa -1.0
    opposite = [{"pass1": "INCLUDE", "pass2": "EXCLUDE"} for _ in range(5)] + \
               [{"pass1": "EXCLUDE", "pass2": "INCLUDE"} for _ in range(5)]
    r = analyse(opposite, min_n=0)
    case("total disagreement -> kappa -1.0", r["kappa_3cat"], -1.0)
    case("total disagreement FAILS", r["gate"], "FAIL")
    case("disagreement direction balanced", r["disagreements"]["dominant_direction"], "balanced")

    # an under-sized pilot fires even at perfect agreement
    case("under-sized pilot FAILS", analyse(perfect, min_n=50)["gate"], "FAIL")

    # kappa-paradox note fires when the marginals are skewed
    skewed = [{"pass1": "EXCLUDE", "pass2": "EXCLUDE"} for _ in range(48)] + \
             [{"pass1": "INCLUDE", "pass2": "INCLUDE"}] + \
             [{"pass1": "INCLUDE", "pass2": "EXCLUDE"}]
    case("skewed marginals emit base-rate caveat", bool(analyse(skewed, min_n=0)["notes"]), True)

    print("\nSELFTEST: %d/%d assertions pass" % (passed, n))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", help="pilot CSV with pass1/pass2 columns")
    ap.add_argument("--out", default="ledgers/gate2a_calibration.json")
    ap.add_argument("--threshold", type=float, default=0.60)
    ap.add_argument("--min-n", type=int, default=50)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.pilot:
        ap.error("provide --pilot (or --selftest)")
    rep = analyse(_load(a.pilot), a.threshold, a.min_n)
    d = os.path.dirname(a.out)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=2, ensure_ascii=False)
    print("gate2a: n=%d  kappa3=%.3f  kappa_bin=%.3f  agree3=%.1f%%  PABAK3=%.3f  threshold=%.2f"
          % (rep["n"], rep["kappa_3cat"] or 0, rep["kappa_binary"] or 0,
             100 * (rep["pct_agreement_3cat"] or 0), rep["pabak_3cat"] or 0, rep["threshold"]))
    for nt in rep["notes"]:
        print("  note:", nt)
    for p in rep["failures"]:
        print("  FAIL:", p)
    print("gate: %s -> %s" % (rep["gate"], a.out))
    return 2 if rep["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
