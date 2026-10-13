#!/usr/bin/env python3
"""ste_lint.py -- mechanical ASD-STE100 (Simplified Technical English) checks.

The skills are instructions a model reads before it acts. Simplified Technical
English is the standard for that job: one word for one meaning, one instruction
per sentence, short sentences, active voice, a controlled vocabulary. This file
enforces the rules that a program can decide on its own. It does NOT ship or
reproduce the ASD-STE100 dictionary -- that standard is copyrighted. The project
keeps its own glossary (ste-glossary.yml) for terminology.

What is checked (all mechanical, no part-of-speech model needed):

  R1  sentence length      instruction <= 20 words, descriptive <= 25
  R2  one instruction      two imperatives joined by "and"/"then"/";" in one sentence
  R3  paragraph length     more than 6 sentences in one paragraph
  R4  contractions         don't, isn't, we're, ...
  R5  progressive verb     "is running" (use the simple tense)
  R6  passive voice        "is written" (allowlisted technical exceptions only)
  R7  noun cluster         REPORTED AS A DIAGNOSTIC ONLY -- see below
  R8  abbreviation         an undefined abbreviation used repeatedly, or one this
                           file defines but uses before the definition
  R9  terminology          a term the glossary marks as "avoid" is used
  R10 list candidate       three or more instructions in one comma sentence

Severity: R1-R6 and R8-R9 are errors. R10 is a warning. R7 is a diagnostic: it
is written to the JSON report and never fails a run. A noun cluster cannot be
decided without a part-of-speech model -- "report", "record", "list", "check"
and "search" are nouns and instruction verbs in this repository -- so the first
version of this rule produced 281 hits, almost all of them legitimate prose. A
rule that flags legitimate writing is worse than the gap.

Allow an exception where the standard's own rule does not apply:
  * inline:  <!-- ste-allow R6: "is required" is a state, not an action -->
  * file:    tools/ste-allowlist.yml  ->  {path: {rule: "reason"}}

Exit codes (the repository's convention):
  0  no errors
  1  at least one error
  4  input gap -- nothing to check (never a pass)

Usage:
  python3 tools/ste_lint.py skills/*/SKILL.md
  python3 tools/ste_lint.py --json out.json skills/citecheck/SKILL.md
  python3 tools/ste_lint.py --self-test
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALLOWLIST_FILE = HERE / "ste-allowlist.yml"

# Words that do not count as nouns for the noun-cluster rule.
FUNCTION_WORDS = frozenset("""
a an the this that these those and or but nor so yet for of in on at by with from to
into during after before while when where which who whom whose if whether than then
as is are was were be been being am do does did done have has had having will would
shall should can could may might must not no there here it its their his her our your
my we they he she you i them us him one such other more most much many few all both
each every any some only own same very also however therefore thus hence although
because since unless until about above below between among within without across
""".split())

# Imperative verbs this project uses to give an instruction. A sentence that
# starts with one of these is an instruction, so the 20-word limit applies.
IMPERATIVE_VERBS = frozenset("""
add append apply ask assert audit build calculate call check choose cite classify clear
collect combine compare compile complete confirm connect convert copy count create
decide declare define delete describe detect determine disable display do document
download draft drop emit enable ensure enter estimate exclude execute exit expand
export extract fail fetch filter find flag fix follow format gather generate give
group handle identify import include inspect install keep label list load locate log
look make map mark match measure merge move name normalize note number open order
output parse pass perform pick place plan populate post prepare print process produce
provide publish pull push query rank rate read re-check re-run rebuild recompute
record reduce refetch refresh regenerate reject reload remove rename render reorder
repeat replace report request require reset resolve restart restore resume return
review rewrite round run save scan score search select send separate set show skip
sort split start state stop store strip submit subtract summarize supply switch
take test tokenize trace track transform trim truncate try turn uninstall unwrap
update upload use validate verify view wait warn wrap write yield
""".split())

# Verb forms that carry no instruction on their own.
STOP_IMPERATIVES = frozenset("""
see note notes example examples caution warning important tip source sources
""".split())

CONTRACTIONS = re.compile(
    r"\b(?:don|doesn|isn|aren|wasn|weren|can|won|couldn|shouldn|wouldn|hasn|haven|hadn"
    r"|mustn|ain|shan)['’]t\b"
    r"|\b(?:it|that|there|here|they|we|you|he|she|who|what|let|this|these|those)"
    r"['’](?:s|re|ve|ll|d)\b",
    re.I,
)

PROGRESSIVE = re.compile(r"\b(?:is|are|was|were|be|been|being)\s+([a-z]+ing)\b", re.I)

PASSIVE = re.compile(
    r"\b(?:is|are|was|were|be|been|being)\s+(?:[a-z]+ly\s+)?([a-z]+(?:ed|en))\b", re.I
)

# Past participles that are ordinary adjectives or states here, not passive
# actions. "the file is written" is passive; "the value is required" is a state.
PASSIVE_STATE_ALLOW = frozenset("""
required needed used allowed expected based limited defined given taken hidden
written read set closed open done known unknown present absent available
unavailable enabled disabled supported unsupported affected selected
""".split())

ABBREVIATION = re.compile(r"\b([A-Z][A-Z0-9]{1,5})\b")
DEFINITION = re.compile(r"\(([A-Z][A-Z0-9]{1,5})\)")

# All-caps words that are ordinary English here, not abbreviations.
COMMON_CAPS = frozenset("""
WHAT WHEN WHERE WHY HOW NOTE NOTES STEP STEPS MUST SHOULD SHALL DO DOES NOT AND OR THE
PASS FAIL OK ERROR ERRORS WARNING WARNINGS RULE RULES GATE GATES STATUS INPUT OUTPUT
FILE FILES TABLE TABLES LIST LISTS TEST TESTS ALL ANY TRUE FALSE READY DONE NEXT FIRST
LAST ONLY NOW THEN WITH FROM INTO OVER MORE LESS NULL NONE EMPTY YES RUN USE ADD SET GET
PUT POST NEW OLD TOP BOTTOM LEFT RIGHT START END OPEN CLOSED HERE THERE THIS THAT THESE
THOSE ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN EVERY EACH SOME BOTH SAME OTHER
""".split())

# Abbreviations a reader is expected to know; they need no definition.
KNOWN_ACRONYMS = frozenset("""
OK NA ID PDF HTML JSON YAML MCP API URL DOI PMID PMC CSV TXT MD AI LLM CLI OS PC STE ORI
XML HTTP HTTPS SQL UTF DOCX XLSX PPTX GB MB KB MS UTC GMT IEEE ACM APA MLA NLM ISO ORCID
""".split())

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
# A period that does not end a sentence.
PROTECTED_PERIOD = re.compile(
    r"\b(?:e\.g|i\.e|vs|etc|no|fig|eq|al|approx|cf|resp|pp|dr|st|mr|ms|inc|ltd)\.",
    re.I,
)

TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’/_.\-]*")


class Violation:
    def __init__(self, rule, line, message, severity="error"):
        self.rule = rule
        self.line = line
        self.message = message
        self.severity = severity

    def as_dict(self):
        return {
            "rule": self.rule,
            "line": self.line,
            "severity": self.severity,
            "message": self.message,
        }


def _load_glossary():
    """Read the small project glossary without a YAML dependency."""
    avoid, prefer = {}, {}
    path = HERE / "ste-glossary.yml"
    if not path.exists():
        return avoid, prefer
    section = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if re.match(r"^[a-z_]+:\s*$", line):
            section = line.strip().rstrip(":")
            continue
        m = re.match(r"^\s+([^:]+):\s*(.*)$", line)
        if not m or section is None:
            continue
        key, value = m.group(1).strip().strip("'\""), m.group(2).strip().strip("'\"")
        if section == "avoid":
            # "term: preferred" -- using `term` for the concept is an error.
            avoid[key.lower()] = value.lower()
        elif section == "prefer":
            prefer[key.lower()] = value
    return avoid, prefer


def _load_allowlist():
    """Read ste-allowlist.yml: {path-substring: {rule: reason}} (stdlib parse)."""
    entries = {}
    if not ALLOWLIST_FILE.exists():
        return entries
    current = None
    for raw in ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith(" ") and line.rstrip().endswith(":"):
            current = line.strip().rstrip(":").strip("'\"")
            entries.setdefault(current, {})
            continue
        m = re.match(r"^\s+([A-Z0-9]+):\s*(.*)$", line)
        if m and current:
            entries[current][m.group(1)] = m.group(2).strip().strip("'\"")
    return entries


def _strip_code(text):
    """Remove fenced and inline code and YAML frontmatter. Keep line numbers."""
    out, in_fence = [], False
    lines = text.splitlines()
    # Skip the YAML frontmatter: it is metadata (name, description), not prose.
    start = 1 if lines and lines[0].strip() == "---" else 0
    end = start
    if start:
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i + 1
                break
    for i, line in enumerate(lines):
        if start and i < end:
            out.append("")
            continue
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append("")
            continue
        if in_fence:
            out.append("")
            continue
        # A lowercase placeholder: an uppercase one would look like an abbreviation.
        out.append(re.sub(r"`[^`]*`", "code", line))
    return "\n".join(out)


def _inline_allows(lines):
    """Map line number -> set of rule ids allowed by the nearest marker above."""
    allows, pending = {}, set()
    for i, line in enumerate(lines, start=1):
        m = re.findall(r"<!--\s*ste-allow\s+([A-Z0-9, ]+):", line)
        if m:
            for chunk in m:
                pending |= {r.strip() for r in chunk.split(",") if r.strip()}
        if line.strip() and not line.strip().startswith("<!--"):
            if pending:
                allows[i] = set(pending)
                pending = set()
    return allows


def _sentences(paragraph):
    """Split a paragraph into sentences, protecting common abbreviations."""
    guard = PROTECTED_PERIOD.sub(lambda m: m.group(0).replace(".", "\x00"), paragraph)
    parts = [p.replace("\x00", ".") for p in SENTENCE_SPLIT.split(guard)]
    return [p.strip() for p in parts if p.strip()]


def _is_instruction(sentence):
    first = TOKEN.findall(sentence)
    if not first:
        return False
    head = first[0].lower()
    if re.search(r"\b(MUST|MUST NOT|SHALL|DO NOT|NEVER)\b", sentence):
        return True
    return head in IMPERATIVE_VERBS and head not in STOP_IMPERATIVES


def _verb_forms():
    forms = set(IMPERATIVE_VERBS)
    for v in IMPERATIVE_VERBS:
        forms |= {v + "s", v + "ed", v + "ing"}
    return forms


_VERB_FORMS = _verb_forms()


def _noun_cluster(sentence):
    """Longest run of noun-ish tokens. A WARNING signal, not a decision.

    Without a part-of-speech model a noun cluster cannot be decided exactly, so
    this counts only tokens that are not function words, not adverbs, not known
    verb forms and not numbers. The threshold is 5, not 4: at 4 the rule fired on
    ordinary prose, and a rule that flags legitimate writing is worse than no
    rule.
    """
    best, run = 0, 0
    for raw in TOKEN.findall(sentence):
        w = raw.lower().strip(".,;:()[]")
        is_nounish = (
            w
            and w not in FUNCTION_WORDS
            and not w.endswith("ly")
            and w not in _VERB_FORMS
            and not w.isdigit()
        )
        if is_nounish:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def check_file(path, glossary=None, allowlist=None):
    """Return (violations, stats) for one markdown file."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    body = _strip_code(text)
    lines = body.splitlines()
    inline_allows = _inline_allows(lines)
    avoid, _prefer = glossary if glossary else _load_glossary()
    file_allows = {}
    for key, rules in (allowlist or {}).items():
        if key in str(path):
            file_allows = rules
            break

    violations = []
    sentences = 0
    words_total = 0
    defined = set(DEFINITION.findall(body))
    defined_line = {}
    for i, raw in enumerate(body.splitlines(), start=1):
        for abbr in DEFINITION.findall(raw):
            defined_line.setdefault(abbr, i)
    caps_count = {}
    for abbr in ABBREVIATION.findall(body):
        # A token with a digit is a label (A1, S3, R2), not an abbreviation.
        if re.search(r"\d", abbr):
            continue
        if abbr not in COMMON_CAPS and abbr not in KNOWN_ACRONYMS:
            caps_count[abbr] = caps_count.get(abbr, 0) + 1
    seen_abbrev = set()
    diagnostics = {"noun_cluster_max": 0}

    def allowed(rule, line):
        return rule in inline_allows.get(line, set()) or rule in file_allows

    paragraph, para_start = [], 1
    blocks = []
    for i, line in enumerate(lines, start=1):
        if not line.strip():
            if paragraph:
                blocks.append((para_start, paragraph))
                paragraph = []
            continue
        if not paragraph:
            para_start = i
        paragraph.append((i, line))
    if paragraph:
        blocks.append((para_start, paragraph))

    for start, block in blocks:
        joined = " ".join(re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", l) for _n, l in block)
        if joined.strip().startswith("#"):
            continue
        sents = _sentences(joined)
        line_of = {s: block[0][0] for s in sents}
        if len(sents) > 6 and not allowed("R3", start):
            violations.append(
                Violation("R3", start, "paragraph has %d sentences (limit 6)" % len(sents))
            )
        for s in sents:
            line = line_of.get(s, start)
            n = len(TOKEN.findall(s))
            sentences += 1
            words_total += n
            instruction = _is_instruction(s)
            limit = 20 if instruction else 25
            if n > limit and not allowed("R1", line):
                kind = "instruction" if instruction else "descriptive"
                violations.append(
                    Violation(
                        "R1",
                        line,
                        "%s sentence has %d words (limit %d): %s"
                        % (kind, n, limit, s[:70] + ("..." if len(s) > 70 else "")),
                    )
                )
            if instruction:
                heads = [
                    t.lower()
                    for t in TOKEN.findall(s)
                    if t.lower() in IMPERATIVE_VERBS and t.lower() not in STOP_IMPERATIVES
                ]
                # "Build and validate the registry" is one instruction with a
                # compound verb, not two instructions. Fire only when the sentence
                # sequences two actions: a semicolon, "then", or a comma between
                # two imperative verbs.
                sequenced = bool(re.search(r";|\bthen\b", s, re.I)) or bool(
                    re.search(r",\s*\w+\s+(?:and\s+)?(?:\w+ing\b|\w+ed\b)", s, re.I)
                )
                if len(heads) >= 2 and sequenced and not allowed("R2", line):
                    violations.append(
                        Violation("R2", line, "two instructions in one sentence: %s" % s[:70])
                    )
                elif len(heads) >= 3 and not allowed("R10", line):
                    violations.append(
                        Violation(
                            "R10",
                            line,
                            "three or more instructions in one sentence; use a vertical list",
                            severity="warning",
                        )
                    )
            if CONTRACTIONS.search(s) and not allowed("R4", line):
                violations.append(Violation("R4", line, "contraction: %s" % s[:60]))
            m = PROGRESSIVE.search(s)
            if m and not allowed("R5", line):
                # "is missing" and "be misleading" are states, not progressive
                # verbs. Only a known verb form counts.
                word = m.group(1).lower()
                stem = word[:-3]
                if {stem, stem + "e", stem[:-1]} & IMPERATIVE_VERBS:
                    violations.append(Violation("R5", line, "progressive verb '%s'" % m.group(0)))
            for m in PASSIVE.finditer(s):
                participle = m.group(1).lower()
                if participle in PASSIVE_STATE_ALLOW:
                    continue
                if allowed("R6", line):
                    continue
                violations.append(Violation("R6", line, "possible passive voice '%s'" % m.group(0)))
            # R7: reported, never decided. See the module docstring.
            diagnostics["noun_cluster_max"] = max(diagnostics["noun_cluster_max"], _noun_cluster(s))
            for abbr in ABBREVIATION.findall(s):
                if abbr in COMMON_CAPS or abbr in KNOWN_ACRONYMS or abbr in seen_abbrev:
                    continue
                if allowed("R8", line):
                    seen_abbrev.add(abbr)
                    continue
                if abbr in defined:
                    # The file defines it: an earlier use is the error.
                    if line < defined_line.get(abbr, 0):
                        violations.append(
                            Violation(
                                "R8",
                                line,
                                "abbreviation '%s' is used here but defined on line %d"
                                % (abbr, defined_line.get(abbr, 0)),
                            )
                        )
                    seen_abbrev.add(abbr)
                    continue
                # Not defined anywhere. One mention is usually a label; a repeated
                # one is jargon the reader has to decode.
                if caps_count.get(abbr, 0) >= 2:
                    violations.append(
                        Violation(
                            "R8",
                            line,
                            "abbreviation '%s' is used %d times and never defined"
                            % (abbr, caps_count[abbr]),
                        )
                    )
                    seen_abbrev.add(abbr)
            for term, preferred in avoid.items():
                if re.search(r"\b%s\b" % re.escape(term), s, re.I) and not allowed("R9", line):
                    violations.append(
                        Violation(
                            "R9", line, "use '%s' instead of '%s'" % (preferred or "the glossary term", term)
                        )
                    )
    return violations, {
        "sentences": sentences,
        "words": words_total,
        "lines": len(lines),
        "diagnostics": diagnostics,
    }


def run(paths, json_out=None, quiet=False, summary=False):
    glossary = _load_glossary()
    allowlist = _load_allowlist()
    report = {"files": {}, "errors": 0, "warnings": 0, "by_rule": {}}
    for p in paths:
        path = Path(p)
        if not path.is_file():
            continue
        violations, stats = check_file(path, glossary, allowlist)
        errors = [v for v in violations if v.severity == "error"]
        warnings = [v for v in violations if v.severity != "error"]
        report["files"][str(p)] = {
            "stats": stats,
            "errors": [v.as_dict() for v in errors],
            "warnings": [v.as_dict() for v in warnings],
        }
        report["errors"] += len(errors)
        report["warnings"] += len(warnings)
        for v in violations:
            report["by_rule"][v.rule] = report["by_rule"].get(v.rule, 0) + 1
        if not quiet:
            status = "PASS" if not errors else "FAIL"
            print("%-6s %-52s %4d sentences  %3d errors  %3d warnings"
                  % (status, p, stats["sentences"], len(errors), len(warnings)))
            for v in errors[:12]:
                print("        line %-4d %-3s %s" % (v.line, v.rule, v.message))
            if len(errors) > 12:
                print("        ... %d more errors" % (len(errors) - 12))
    if summary:
        print("\nby rule:", ", ".join("%s=%d" % kv for kv in sorted(report["by_rule"].items())))
    if json_out:
        Path(json_out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


SELF_TEST_CASES = [
    # (text, rule that must fire, or None for clean)
    ("Run the checker.\n", None),
    ("Run the checker and then write the report to the disk file.\n", "R2"),
    ("The checker reads the file that the user supplied and it writes a report that "
     "contains every sentence and every verdict and every note for the reader today.\n", "R1"),
    ("Don't write the file.\n", "R4"),
    ("The tool is writing the report.\n", "R5"),
    ("The file is deleted by the tool.\n", "R6"),
    # R8: an abbreviation used twice with no definition.
    ("The QZX value must be set. Read the QZX file.\n", "R8"),
    # R8: defined later in the file, used earlier.
    ("The QZX value must be set.\n\nDefine the field (QZX) in the schema.\n", "R8"),
    ("We utilize the toolkit.\n", "R9"),
    ("First line.\nSecond line.\nThird line.\nFourth line.\nFifth line.\nSixth line.\n"
     "Seventh line.\n", "R3"),
]


def self_test():
    """Prove each rule fires, and that a clean sentence stays clean."""
    failures = []
    tmp = Path(os.environ.get("TMPDIR", "/tmp")) / "ste-lint-selftest"
    tmp.mkdir(parents=True, exist_ok=True)
    for i, (text, expected) in enumerate(SELF_TEST_CASES):
        f = tmp / ("case%d.md" % i)
        f.write_text(text, encoding="utf-8")
        violations, _stats = check_file(f)
        rules = {v.rule for v in violations}
        if expected is None:
            if rules:
                failures.append("case %d expected clean, got %s" % (i, sorted(rules)))
        elif expected not in rules:
            failures.append("case %d expected %s, got %s" % (i, expected, sorted(rules)))
    # The allowlist marker must suppress a rule.
    f = tmp / "allow.md"
    f.write_text("<!-- ste-allow R2: this is one action with a qualifier -->\n"
                 "Run the checker and then write the report.\n", encoding="utf-8")
    violations, _stats = check_file(f)
    if any(v.rule == "R2" for v in violations):
        failures.append("inline ste-allow did not suppress R2")
    # A code fence must not be linted.
    f = tmp / "fence.md"
    f.write_text("```\nThis is a very long line of code that would otherwise be reported by "
                 "the sentence length rule and by several other rules as well today.\n```\n",
                 encoding="utf-8")
    violations, _stats = check_file(f)
    if violations:
        failures.append("code fence was linted: %s" % [v.rule for v in violations])
    # R7 must stay a diagnostic: reported, and never in the violation list.
    f = tmp / "cluster.md"
    f.write_text("The machine readable citation report artifact file remains.\n", encoding="utf-8")
    violations, stats = check_file(f)
    if any(v.rule == "R7" for v in violations):
        failures.append("R7 became a violation; it must stay a diagnostic")
    if stats["diagnostics"]["noun_cluster_max"] < 1:
        failures.append("the R7 diagnostic was not computed")
    for msg in failures:
        print("FAIL  %s" % msg)
    print("ste_lint self-test: %d checks, %d failed" % (len(SELF_TEST_CASES) + 3, len(failures)))
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", help="markdown files to check")
    ap.add_argument("--json", dest="json_out", default=None, help="write a JSON report here")
    ap.add_argument("--quiet", action="store_true", help="no per-file output")
    ap.add_argument("--summary", action="store_true", help="print a per-rule count")
    ap.add_argument("--self-test", action="store_true", help="check this checker")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.paths:
        print("ste_lint: no input files (input gap, not a pass)", file=sys.stderr)
        return 4
    report = run(args.paths, args.json_out, args.quiet, args.summary)
    print("ste_lint: %d errors, %d warnings across %d file(s)"
          % (report["errors"], report["warnings"], len(report["files"])))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
