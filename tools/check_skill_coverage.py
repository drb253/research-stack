#!/usr/bin/env python3
"""check_skill_coverage.py -- repo-wide coverage gate for the skills tree.

Every directory under `skills/` must be a real skill, and every claim of skill
coverage must be checkable. Five assertions, per skill:

  1. SKILL.md exists.
  2. Its YAML frontmatter is valid: `name` is kebab-case and equals the
     directory name, and `description` is present and non-empty.
  3. The skill ships a harness AND .github/workflows/ci.yml runs it. A script
     under skills/<name>/scripts/ counts only when its exact path appears in
     ci.yml -- a harness that exists but never runs is a violation, not a pass.
     A HARNESS_ALIAS names a harness that genuinely lives outside the skill
     directory, and the same rule applies: its exact path must be in ci.yml.
     There are no exemptions for this rule: a skill with no script at all is a
     violation (EXEMPT is kept as the documented escape hatch and is empty; any
     future entry must name why the skill cannot have a harness).
  4. Every gate the skill declares has BOTH a passing and a failing path
     fixture. Gates are declared either explicitly in SKILL.md
     (`<!-- gates: a.py, b.py -->`) or derived from `scripts/selftest.sh`:
     a script exercised with a non-zero `expect_exit` (or a manual
     `[ "$x_exit" -ne 0 ]`) is a gate, and it must also be exercised with a
     zero expectation or a `[ "$x_exit" -eq 0 ]` assertion. A script that is
     only ever run expecting success is a setup step, not a gate, and is
     reported as a step rather than counted as covered. A written GATE_EXEMPT
     reason covers a gate that cannot have a one-line fail fixture, and is only
     honoured while the gate is still exercised at all (a stale exemption is a
     violation).
  5. Every item id in the skill's eval.md (C1, H2, S4 ...) appears in SKILL.md,
     which is where the rubric-coverage table lives.

Exit codes:
  0  every assertion holds
  1  at least one violation
  4  an input gap: the repo layout the gate needs is missing or unreadable
     (a gap is never reported as a pass)

Usage:
  python3 tools/check_skill_coverage.py [--repo DIR] [--json OUT]
  python3 tools/check_skill_coverage.py --self-test
"""
import argparse
import json
import os
import re
import sys

# --- fixture / repository layout -------------------------------------------- #
SKILLS_SUBDIR = "skills"
CI_REL = os.path.join(".github", "workflows", "ci.yml")
FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n", re.S)
KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# eval.md item ids: "### C1. ...", "#### H2 ...", "### 8b. ..." are NOT ids
# (numeric citation-report sections are sections, not rubric items).
ITEM_ID = re.compile(r"^#{2,4}[ \t]+([A-Z]{1,3}\d+[a-z]?)\.[ \t]*(.*)$", re.M)

# --- written exemptions ----------------------------------------------------- #
# Rule 3 has no exemptions in this repository: every skill must ship a harness
# and have it registered in ci.yml. The mechanism is kept, empty, so that an
# entry can only be added with a reason that names why the skill cannot have a
# harness at all -- not merely that it does not have one yet.
EXEMPT = {}

# Rule 3, alias form: the harness is real but lives outside skills/<name>/, so
# CI reaches it by another path. The needle must appear in ci.yml.
HARNESS_ALIAS = {
    "paper-search": {
        "needle": "mcp/paper-search-patches/ci_patch_check.py",
        "reason": "the skill documents the paper-search tool; the tool's own gate is the "
                  "patch-system check plus the two vendored-server suites in the mcp-tests job",
    },
    "originality-check": {
        "needle": "tools/originality-toolkit/originality_check.py",
        "reason": "the skill is the interface to the originality toolkit, whose self-test "
                  "is registered under tools/ rather than skills/",
    },
}

# Rule 4. A gate whose fail path genuinely cannot be a one-line CLI fixture.
# Honoured only while the gate is still exercised (stale exemptions fail).
GATE_EXEMPT = {
    "evidence-synthesis-forge/regression_suite.py":
        "meta-suite: it runs one fixture per defect class and fails when any stops being "
        "caught, so its own fail path is exercised by breaking a gate, not by a CLI flag",
    "evidence-synthesis-forge/check_selftest_coverage.py":
        "meta-gate: this is the coverage checker itself; its fail path is exercised by "
        "removing a fixture from selftest.sh, which cannot be done from inside the suite "
        "it is checking",
}

# --- selftest.sh parsing ---------------------------------------------------- #
EXPECT_EXIT = re.compile(r'^\s*expect_exit\s+(\d+)\s+"([^"]*)"\s+(.*)$')
ASSIGN = re.compile(r'^\s*([A-Za-z_]\w*)=')
ASSIGN_PATH_TAIL = re.compile(r'([\w./-]+\.(?:py|R|sh))"?\)?\s*$')
EXIT_CMP = re.compile(r'\[\s*"\$(\w+)"\s*-(eq|ne)\s*0\s*\]')
DECLARED_GATE = re.compile(r"<!--\s*gates:\s*([^>]*?)\s*-->")


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def frontmatter(text):
    m = FRONTMATTER.match(text)
    if not m:
        return None
    fields = {}
    for line in m.group(1).splitlines():
        mm = re.match(r"^([A-Za-z_][\w-]*):[ \t]*(.*)$", line)
        if mm:
            fields[mm.group(1)] = mm.group(2).strip()
    return fields


def declared_gates(skill_md):
    out = []
    for blob in DECLARED_GATE.findall(skill_md):
        out += [p.strip() for p in blob.split(",") if p.strip()]
    return out


def var_map(lines):
    """NAME -> basename of the script it holds (array or scalar assignment)."""
    varmap = {}
    for line in lines:
        m = ASSIGN.match(line)
        if not m:
            continue
        tail = ASSIGN_PATH_TAIL.search(line.split("#", 1)[0].rstrip())
        if tail:
            varmap[m.group(1)] = os.path.basename(tail.group(1))
    return varmap


def resolve_program(cmd, varmap):
    """The script a shell command *invokes* -- never a path that is only an argument.

    `python3 "$COVER" --selftest "$TMP/one_sided.sh"` runs $COVER; one_sided.sh is
    a fixture argument. Resolving the first .py/.sh token in the whole command
    would report the fixture as a gate, so only the invoked program is resolved.
    """
    cmd = cmd.strip()
    m = re.match(r'^(?:python3|bash|sh)\s+(.*)$', cmd)
    rest = m.group(1).strip() if m else cmd
    ma = re.match(r'^"?\$\{(\w+)\[@\]\}"?', rest)
    if ma:
        return varmap.get(ma.group(1))
    mp = re.match(r'^"?\$HERE/([\w./-]+)"?', rest)
    if mp:
        return os.path.basename(mp.group(1))
    # `"$ESF/regression_suite.py"`: the variable holds a directory, the script
    # name is literal after it.
    md = re.match(r'^"?\$\{?(\w+)\}?/([\w./-]+\.(?:py|R|sh))"?', rest)
    if md:
        return os.path.basename(md.group(2))
    ms = re.match(r'^"?\$\{?(\w+)\}?"?(?![\w/])', rest)
    if ms:
        return varmap.get(ms.group(1))
    ml = re.match(r'^"?([\w./-]+\.(?:py|R|sh))"?', rest)
    if ml:
        return os.path.basename(ml.group(1))
    return None


def harness_candidates(d, name):
    """ci.yml-relative paths of every runnable harness script this skill ships."""
    scripts = os.path.join(d, "scripts")
    out = []
    if os.path.isdir(scripts):
        for fn in sorted(os.listdir(scripts)):
            if fn.endswith((".sh", ".py", ".R")) and os.path.isfile(os.path.join(scripts, fn)):
                out.append("skills/%s/scripts/%s" % (name, fn))
    return out


def expected_harness(d, name, ci_text):
    """The one path that must appear in ci.yml for this skill to be covered."""
    cands = harness_candidates(d, name)
    preferred = [p for p in cands if p.endswith("selftest.sh")]
    if preferred:
        return preferred[0]
    registered = [p for p in cands if p in ci_text]
    if registered:
        return registered[0]
    if name in HARNESS_ALIAS:
        return HARNESS_ALIAS[name]["needle"]
    return cands[0] if cands else "(no harness file)"


def gate_paths(selftest_text):
    """script -> {'pass': n, 'fail': n, 'invoked': n} from a selftest harness."""
    lines = selftest_text.splitlines()
    varmap = var_map(lines)
    per = {}

    def bump(script, kind):
        row = per.setdefault(script, {"pass": 0, "fail": 0, "invoked": 0})
        row[kind] += 1
        row["invoked"] += 1

    i = 0
    while i < len(lines):
        line = lines[i]
        m = EXPECT_EXIT.match(line)
        if m:
            code, cmd = m.group(1), m.group(3)
            while lines[i].rstrip().endswith("\\") and i + 1 < len(lines):
                i += 1
                cmd += " " + lines[i].strip()
            script = resolve_program(cmd, varmap)
            if script:
                bump(script, "pass" if code == "0" else "fail")
            i += 1
            continue
        script = resolve_program(line, varmap)
        if script:
            per.setdefault(script, {"pass": 0, "fail": 0, "invoked": 0})["invoked"] += 1
            window = "\n".join(lines[i + 1:i + 8])
            for _var, op in EXIT_CMP.findall(window):
                per[script]["pass" if op == "eq" else "fail"] += 1
        i += 1
    return per


def check_tree(skills_dir, ci_text):
    """Core assertions over a skills directory. Returns (violations, rows)."""
    violations = []
    rows = []
    exemptions = []
    names = sorted(n for n in os.listdir(skills_dir)
                   if os.path.isdir(os.path.join(skills_dir, n)))

    for name in names:
        d = os.path.join(skills_dir, name)
        row = {"skill": name, "checks": {}}

        # 1. SKILL.md exists
        skill_md_path = os.path.join(d, "SKILL.md")
        if not os.path.isfile(skill_md_path):
            violations.append({"skill": name, "rule": "skill-md",
                               "detail": "SKILL.md is missing"})
            row["checks"]["skill-md"] = "FAIL"
            rows.append(row)
            continue
        skill_md = read_text(skill_md_path)
        row["checks"]["skill-md"] = "ok"

        # 2. frontmatter
        fm = frontmatter(skill_md)
        fm_ok = True
        if fm is None:
            fm_ok = False
            violations.append({"skill": name, "rule": "frontmatter",
                               "detail": "SKILL.md has no --- frontmatter block"})
        else:
            fm_name = fm.get("name", "")
            if fm_name != name:
                fm_ok = False
                violations.append({"skill": name, "rule": "frontmatter",
                                   "detail": "frontmatter name %r != directory %r"
                                             % (fm_name, name)})
            if not KEBAB.match(fm_name or ""):
                fm_ok = False
                violations.append({"skill": name, "rule": "frontmatter",
                                   "detail": "frontmatter name %r is not kebab-case" % fm_name})
            if not fm.get("description", "").strip():
                fm_ok = False
                violations.append({"skill": name, "rule": "frontmatter",
                                   "detail": "frontmatter description is empty"})
        row["checks"]["frontmatter"] = "ok" if fm_ok else "FAIL"

        # 3. the skill ships a harness AND ci.yml runs it
        candidates = harness_candidates(d, name)
        registered = [p for p in candidates if p in ci_text]
        alias = HARNESS_ALIAS.get(name)
        alias_hit = bool(alias and alias["needle"] in ci_text)
        if registered:
            row["checks"]["harness"] = "ok (%d registered)" % len(registered)
            row["harness_paths"] = registered
            if len(registered) < len(candidates):
                row["unregistered"] = [p for p in candidates if p not in registered]
        elif alias_hit:
            row["checks"]["harness"] = "ok (alias)"
            row["harness_paths"] = [alias["needle"]]
        elif name in EXEMPT:
            row["checks"]["harness"] = "EXEMPT"
            exemptions.append({"skill": name, "rule": "harness", "reason": EXEMPT[name]})
        elif candidates:
            row["checks"]["harness"] = "FAIL"
            row["harness_paths"] = candidates
            violations.append({"skill": name, "rule": "harness",
                               "detail": "harness exists but is not registered in ci.yml: %s"
                                         % ", ".join(candidates)})
        else:
            row["checks"]["harness"] = "FAIL"
            violations.append({"skill": name, "rule": "harness",
                               "detail": "no harness under skills/%s/scripts/ and no ci.yml "
                                         "registration" % name})

        # 4. every declared gate has both paths
        selftest = os.path.join(d, "scripts", "selftest.sh")
        gates = declared_gates(skill_md)
        if os.path.isfile(selftest):
            per = gate_paths(read_text(selftest))
            invoked = set(per)
            derived = {s for s, c in per.items() if c["fail"] > 0}
            # A GATE_EXEMPT entry is itself a declaration that this script is a
            # gate (the reference suite lists the two meta-suites there). The
            # exemption is honoured only while the gate is still exercised, so a
            # stale entry surfaces as "never exercised".
            meta = {k.split("/", 1)[1] for k in GATE_EXEMPT if k.startswith(name + "/")}
            gate_set = sorted(set(gates) | derived | meta)
            gate_rows = []
            for g in gate_set:
                c = per.get(g, {"pass": 0, "fail": 0, "invoked": 0})
                key = "%s/%s" % (name, g)
                if g not in invoked:
                    status = "FAIL"
                    violations.append({"skill": name, "rule": "gate-paths",
                                       "detail": "declared gate %s is never exercised by "
                                                 "scripts/selftest.sh" % g})
                elif c["pass"] and c["fail"]:
                    status = "OK"
                elif key in GATE_EXEMPT:
                    status = "EXEMPT"
                    exemptions.append({"skill": name, "rule": "gate-paths",
                                       "reason": GATE_EXEMPT[key]})
                else:
                    status = "ONLY"
                    missing = "fail" if c["fail"] == 0 else "pass"
                    violations.append({"skill": name, "rule": "gate-paths",
                                       "detail": "gate %s has no %s-path fixture "
                                                 "(pass=%d fail=%d)"
                                                 % (g, missing, c["pass"], c["fail"])})
                gate_rows.append({"gate": g, "pass": c["pass"], "fail": c["fail"],
                                  "status": status})
            row["gates"] = gate_rows
            row["steps"] = sorted(s for s in invoked
                                  if s not in set(gate_set) and per[s]["fail"] == 0)
            row["checks"]["gate-paths"] = ("FAIL"
                                           if any(v["rule"] == "gate-paths"
                                                  for v in violations if v["skill"] == name)
                                           else "ok")
        else:
            row["checks"]["gate-paths"] = "N/A (no scripts/selftest.sh)"

        # 5. every eval.md item id appears in SKILL.md
        eval_path = os.path.join(d, "eval.md")
        if not os.path.isfile(eval_path):
            row["checks"]["eval-coverage"] = "N/A (no eval.md)"
        else:
            ids = [m.group(1) for m in ITEM_ID.finditer(read_text(eval_path))]
            missing = [i for i in ids if not re.search(r"\b%s\b" % re.escape(i), skill_md)]
            if missing:
                row["checks"]["eval-coverage"] = "FAIL"
                violations.append({"skill": name, "rule": "eval-coverage",
                                   "detail": "eval.md ids absent from SKILL.md: %s"
                                             % ", ".join(missing)})
            elif not ids:
                # AUDIT F-03/F-04: "ok (0 ids)" claimed a clean result for a check that
                # never ran. Two skills (sysreview SR1-SR11, meta-analysis MR1-MR9) use
                # two-letter ids the old regex could not see. The regex now accepts up to
                # three letters; a genuinely numeric-only eval.md (citation-report, by
                # design) is reported as unchecked rather than as ok.
                row["checks"]["eval-coverage"] = ("no ids extracted (%d chars, numeric "
                                                  "headings are not ids)" % len(read_text(eval_path)))
            else:
                row["checks"]["eval-coverage"] = "ok (%d ids)" % len(ids)
        rows.append(row)

    return violations, rows, exemptions


# --- self-test -------------------------------------------------------------- #
FIXROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "e2e-fixtures", "coverage-selftest")


def selftest_skills(case):
    return os.path.join(FIXROOT, case, "skills")


def run_selftest():
    """Prove each assertion can fail, and that a clean tree passes."""
    if not os.path.isdir(FIXROOT):
        print("ERROR: self-test fixtures missing: %s" % FIXROOT, file=sys.stderr)
        return 4
    cases = [
        ("good", None),
        ("bad-skill-md", "skill-md"),
        ("bad-frontmatter", "frontmatter"),
        ("bad-harness", "harness"),
        ("bad-unregistered", "harness"),
        ("bad-one-sided", "gate-paths"),
        ("bad-eval-coverage", "eval-coverage"),
        ("good-two-letter", None),
        ("bad-eval-coverage-two-letter", "eval-coverage"),
        ("bad-declared-gate", "gate-paths"),
    ]
    failures = 0
    for case, want_rule in cases:
        skills = selftest_skills(case)
        if not os.path.isdir(skills):
            print("  MISSING fixture %s" % case)
            failures += 1
            continue
        ci = read_text(os.path.join(FIXROOT, case, "ci.yml"))
        violations, _rows, _ex = check_tree(skills, ci)
        rules = sorted({v["rule"] for v in violations})
        if want_rule is None:
            ok = not violations
            detail = "clean" if ok else "unexpected violations: %s" % rules
        else:
            ok = want_rule in rules
            detail = "caught %s" % want_rule if ok else "did NOT catch %s (got %s)" % (
                want_rule, rules or "none")
        print("  %-20s %s -- %s" % (case, "PASS" if ok else "FAIL", detail))
        failures += 0 if ok else 1
    print("\nself-test: %d/%d assertions proven" % (len(cases) - failures, len(cases)))
    return 0 if failures == 0 else 1


# --- main ------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description="Every skill is covered by a harness and a rubric.")
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    help="repository root (default: the parent of tools/)")
    ap.add_argument("--skills", help="override the skills directory")
    ap.add_argument("--ci", help="override the ci.yml path")
    ap.add_argument("--json", help="write the full report as JSON to this path")
    ap.add_argument("--list-harnesses", action="store_true",
                    help="print, per skill, the exact ci.yml path the gate requires")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return run_selftest()

    skills_dir = args.skills or os.path.join(args.repo, SKILLS_SUBDIR)
    ci_path = args.ci or os.path.join(args.repo, CI_REL)
    for path, what in ((skills_dir, "skills directory"), (ci_path, "ci.yml")):
        if not os.path.exists(path):
            print("INPUT GAP: %s not found: %s" % (what, path), file=sys.stderr)
            return 4
    try:
        ci_text = read_text(ci_path)
        if args.list_harnesses:
            for name in sorted(n for n in os.listdir(skills_dir)
                               if os.path.isdir(os.path.join(skills_dir, n))):
                d = os.path.join(skills_dir, name)
                want = expected_harness(d, name, ci_text)
                state = "REGISTERED" if want in ci_text else "MISSING from ci.yml"
                print("  %-30s %-58s %s" % (name, want, state))
            return 0
        violations, rows, exemptions = check_tree(skills_dir, ci_text)
    except OSError as exc:
        print("INPUT GAP: %s" % exc, file=sys.stderr)
        return 4

    print("skill coverage gate -- %s" % skills_dir)
    print("  %-30s %-9s %-11s %-14s %s" % ("skill", "SKILL.md", "frontmatter",
                                           "harness", "gate-paths / eval"))
    for row in rows:
        c = row["checks"]
        gates = row.get("gates", [])
        gsum = ", ".join("%s:%s(p%d/f%d)" % (g["gate"], g["status"], g["pass"], g["fail"])
                         for g in gates)
        print("  %-30s %-9s %-11s %-14s %s" % (
            row["skill"], c.get("skill-md", "-"), c.get("frontmatter", "-"),
            c.get("harness", "-"), c.get("gate-paths", "-")))
        if gsum:
            print("      gates: %s" % gsum)
        if row.get("steps"):
            print("      steps (pass-path only, not gates): %s" % ", ".join(row["steps"]))
        print("      eval: %s" % c.get("eval-coverage", "-"))

    if exemptions:
        print("\nexemptions (each with a written reason, not a silent skip):")
        for e in exemptions:
            print("  - %s [%s]: %s" % (e["skill"], e["rule"], e["reason"]))

    report = {"skills": len(rows), "violations": violations, "rows": rows,
              "exemptions": exemptions}
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)

    if violations:
        print("\nFAIL - %d violation(s):" % len(violations))
        for v in violations:
            print("  - %s [%s]: %s" % (v["skill"], v["rule"], v["detail"]))
        return 1
    print("\nOK - all %d skills covered" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
