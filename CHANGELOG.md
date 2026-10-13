# Changelog

All notable changes to **research-stack** are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

_Nothing yet._

## [1.1.0] — 2026-10-13

### Added
- **A conflict ground truth taken from the literature, and the parser defect it found.** Ten
  contradictions whose ground truth is a real open-access article: each value was copied verbatim
  out of the fetched full text, each sentence is a plausible digit transposition of it, and the
  article's own wording is recorded beside it so the pairing can be checked rather than trusted.
  Yield stated plainly: 19 of 60 DOIs from a real clinical bibliography were obtained (31.7%, all
  from the Europe PMC tier), and only 4 of those 19 contain a measure the parser accepts. Scored
  and reported separately from the hand-written set, so ten real cases cannot inherit that set's
  caveat. Building it found that the same measure written long-form on one side and short-form on
  the other was not recognised as the same statistic, which lost two real contradictions; a
  canonical measure vocabulary now maps relative risk / risk ratio / hazard ratio / odds ratio /
  prevalence ratio / rate ratio / standardised mean difference / mean difference / risk difference
  onto their short forms on both sides, and adjusted forms are deliberately *not* conflated with
  unadjusted ones. Result: 8 of 10 -> **10 of 10** caught.
- **A false-parse guard, and the false accusation that motivated it.** The English conjunction "or"
  was being read as the odds-ratio label `OR`, so "Treatment continued for 6 or 12 weeks", cited
  against a source recording `OR 1.42`, was reported as a **conflict** — the tool accused an author
  of contradicting a source using the word "or" and the number 12. Three guards now apply: the
  short labels that are also English words or fragments must be written in upper case (a lower-case
  leading `a` is still allowed, because `aOR` is written that way); a number immediately followed by
  a percent sign is a percentage, not the measure (`OR 95% CI` is a table header); and no effect
  measure reaches 1000, so a larger value after a short label is an identifier (`MD 21702` is a ZIP
  code). Every measured metric is unchanged, and the benchmark now runs four ordinary-prose probes
  through the real CLI and **fails** if any is classified as a contradiction.
- **`--self-test` for `meta-ml-screener` and the originality toolkit**, and a `check_refusal()`
  helper in the meta-analysis golden tests that captures the engine's exit status — the suite had
  discarded it and tested only the happy path. CI now runs the screener self-test, the paper-search
  availability suite, and a byte-identity check that every patch replacement still matches the
  vendored file it mirrors.
- **Evidence acquisition** (`citation-report/scripts/_acquire.py`): when a cited source has no readable
  evidence, three open-access tiers are tried in order — keyless full text from Europe PMC, an
  open-access PDF resolved through OpenAlex, and the vendored `paper-search` package as an optional
  subprocess — with a downloadable-file cache, polite pacing, and bounded IO. Every attempt is recorded
  whether it succeeds or fails, and **text is used only after its identity is confirmed against the
  cited work**; on any disagreement it is discarded and recorded as `mismatch`. Paywalls are never
  bypassed. Measured on a real 60-DOI clinical reference list: **20/60 = 33.3%** yielded usable full
  text, all from the Europe PMC tier, with **zero identity mismatches** — tier C scored 0/60 because
  publisher `/pdf` endpoints answer a non-browser client with 403, and tier D 0/60 because its only
  working route needs a PMCID that tier B established first. Both are kept, reported at zero, and never
  overstated. Flags: `--acquire`, `--no-download`, `--cache-dir`.
- **A transient lookup failure is no longer recorded as absent evidence.** A live run in which Europe
  PMC returned `HTTP 503` for sixty consecutive lookups produced a worklist telling the user to supply
  sixty PDFs; the honest instruction is to retry. DOI resolution is now paced, the failure is stored
  separately (`Resolution.abstract_error`), and the worklist distinguishes "this lookup failed, retry"
  from "this source is not available, supply it". Same class of error as the parent rule: an input
  condition must not be worded as a finding about the artefact.
- **The citation-report benchmark now reports accuracy, sensitivity and specificity**, as a confusion
  matrix with Wilson 95% intervals, instead of a single "agreement" figure — matching the convention of
  the other benchmarks in this directory. It scores two decisions separately, because they fail
  differently: the **accusation** decision (a false positive accuses someone) and the **trigger**
  decision (a false positive tells an author they failed to cite). It also carries a second labelled
  set: **40 sentences drawn at a fixed interval from a real 34-page review**, hand-labelled by reading
  them, so the measurement is not taken only on cases written to fit the rules. Measured: accusation
  accuracy/sensitivity/specificity **1.000/1.000/1.000** on 48 constructed cases and accusation
  specificity **1.000** on 40 unseen real sentences; trigger accuracy **0.900**, sensitivity **0.867**,
  specificity **1.000**. Specificity is now an asserted safety property.
- **The metrics found two real defects, in opposite directions.**
  1. **False negatives:** the trigger scored accuracy **0.475** and sensitivity **0.300** on the real
     sample — it never accused wrongly but missed 70% of sentences needing attribution, because the
     signal list demanded exact phrases ("studies show") and had no association signal. Attribution is
     now recognised as a named body of evidence plus a reporting verb with bounded interpolation
     ("research has documented", "investigations describe", "models of prolonged stress similarly
     show"), association and causation are triggers ("is associated with", "correlate with", "prevents"),
     and a statistical noun carrying a quantity counts even when the digits did not survive extraction.
     Sensitivity rose to **0.867** with no loss of specificity, and on the real document `unattributed`
     rose from 174 to 311 — the old rules had been silently ignoring 132 attribution-requiring sentences.
  2. **False positives in the greens, which matter more:** `ICD-11`, `DSM-5` and `PCL-5` digits were
     read as statistics, and a small bare integer (`metalloproteinase 9`, `Figure 2`, `phase 2`) was
     treated as a measured value. **11 of 12 `attributed` verdicts on the real document rested on a
     label digit and the twelfth on a protein name** — support claimed for a value never checked.
     Numbered labels and structural pointers are now masked, and a bare number must be ≥ 20 or
     fractional before it may serve as a value. The count of greens on that document is now **zero**,
     which is the correct answer for its sources.
- **`docs/EVIDENCE-INVARIANT.md`** — the repository-wide rule that a gap in the inputs must never be
  reported in the same channel, shape or exit status as a finding about the artefact. Stated once, with
  the failure that produced it and the question to ask each remaining gate.
- **Evidence sufficiency and the input/result boundary.** `citation-report` no longer reports a run it
  could not check as though it had. A cited source with no readable evidence now makes the run
  `insufficient_evidence` (**exit 3**) and a document the tool could not parse makes it
  `insufficient_input` (**exit 4**); both block by default, both still write every artifact, and both
  write `evidence_worklist.csv` naming exactly what to supply. `--allow-insufficient` proceeds while
  keeping the status visible. A new `worklist` mode re-checks the list and exits non-zero until every
  gap is closed. Artifacts carry an `INPUT-BOUND — NOT A FINDING` banner in its own colour, and the
  coverage line states the reason beside the figure instead of a bare percentage.
- **A red finding now requires defensible evidence.** `conflict` requires an **identity-verified link**
  (a declared id, a supplied file, or a resolved DOI — never a title match) and **machine-comparable
  evidence** (the source's own text, or a value copied verbatim into a ledger). A prose summary written
  by a human may support a positive claim but may never convict, so rules **D11** and **D12** downgrade
  such a contradiction to `unverifiable` with the reason and with what would confirm it. The gate
  re-checks both bars (`CONFLICT_LINK_INFERRED`, `CONFLICT_EVIDENCE_TOO_WEAK`), and every verdict records
  `evidence_strength`, `evidence_origin` and `link_confidence` so a colour never hides what it rested on.
  Accepted cost: conflict recall falls, and the benchmark reports the change rather than absorbing it.
- **Evidence provenance is enforced.** Evidence text may not appear in a verdict without a record of
  where it came from; a verdict whose evidence cannot be traced is a gate error
  (`EVIDENCE_WITHOUT_PROVENANCE`). Support that rests only on an extractor's prose raises a countable
  `SUMMARY_ONLY_SUPPORT` warning and is separated in the coverage summary
  (`attributed_by_strength`).
- **Four intake preconditions**, because each failure makes findings meaningless rather than merely
  incomplete: `CITATION_STYLE_UNRECOGNISED`, `TRIGGER_LANGUAGE_UNSUPPORTED`, `SENTENCE_SPLIT_SUSPECT`,
  `NO_SOURCE_LIST`. Each records its observed value whether it passes or fails.
- **Superscript numeric citations** (Nature style) are now read from DOCX `w:vertAlign`, where the
  formatting is recorded. Previously every checkable sentence in such a document became `unattributed` —
  an accusation that the author failed to cite, thousands of times over.
- **`citation-report`** — a new skill that grades a document sentence by sentence against the
  sources you supply, and renders the result as a colour-coded citation report in **PDF**
  (painted sentence highlights plus printed margin notes), **DOCX** (exact-colour run shading plus
  real Word comments) and **HTML** (coloured spans, hover notes, coverage bar). Every sentence gets
  one of six states assigned by a **named deterministic rule** from a recorded source registry:
  `attributed`, `synthesis`, `unverifiable`, `unattributed`, `conflict`, `no_citation_needed`.
  - Resolves DOIs through Crossref/OpenAlex/Europe PMC (keyless, and fully disabled by `--offline`),
    reads source PDFs via `pdftotext` or optional `pypdf` with a **legible refusal** rather than
    grading against unreadable evidence, and links sources from a BibTeX `file = {...}` manifest, a
    PDF directory, the document's own numbered reference list, a `sources.csv` ledger, or a DOI list.
  - **Never paints green without evidence** and **never paints red without a quote.** A number merely
    absent from extracted text is a warning, not a contradiction, because extraction loses tables and
    figures. Red is reserved for a citation that resolves to nothing, a retracted source, or a value
    that contradicts the same named measure in a source actually held.
  - The semantic grade is a **separate advisory channel** that can never set, change or veto a
    verdict — matching the existing `ADVISORY_` contract in `medical-narrative-review`. A selftest
    asserts the deterministic verdicts, coverage arithmetic, gate verdict, exit code and painted
    states are identical with the channel on and off.
  - `report_gate.py` recomputes the coverage arithmetic from the verdict list, re-locates every span
    in the document, and **re-opens each artifact** to count what is actually in it — including
    requiring the PDF's notes to be findable in its text layer, so a regression to annotations fails.
  - Measured: **48/48 hand-labelled sentences** correct at rule and state level, trigger precision and
    recall **1.000**, and **conflict precision 1.000 over 26 conflict cases** (the safety property),
    with a Wilson lower bound of 0.871. Caveats, including why
    a hand-labelled set written by the author of the rules cannot show generalisation, are in
    `docs/BENCHMARK-RESULTS.md` §5.
  - Wired into `verify.sh` (harness runs with the other gates) and CI (`lint` job), and picked up
    automatically by `install.sh`.
- GitHub Actions CI (`.github/workflows/ci.yml`): a `lint` job on Ubuntu + macOS
  (shell syntax, Python syntax, offline logic self-tests, the medical-narrative
  selftest) and an `r-tests` job that runs the meta-analysis golden tests and the
  evidence-synthesis gate suite.
- This changelog.
- **`benchmarks/`** — six reproducible harnesses that measure how well the gates
  actually work, against ground truth independent of the tool: retraction detection
  vs NLM-curated publication types (920 real citations), the arithmetic gate, and
  three overlap-detection sets including **real** bioRxiv/medRxiv preprint→published
  pairs and the **US ORI guide's own expert-labelled** paraphrasing exercise.
  Measured: retraction 100%/100% with a **99.17% Wilson lower bound**; overlap 100%
  sensitivity (95% CI 93.4–100%) and 100% specificity on real pairs; 6/6 agreement
  with ORI verdicts; **0 unsafe accepts in 920 citations**.
- `docs/BENCHMARK-RESULTS.md` (method, numbers, caveats) and
  `docs/AUDIT-FINDINGS.md` (code/docs audit: every defect found, fixed and re-verified).
- `originality_check.py --corpus PATH` — compare a draft against **any local text**
  (paywalled PDFs via optional `pypdf`, theses, books, unpublished manuscripts, saved
  web pages), in addition to the five open APIs or alone (`--sources ""`, fully
  offline). Unreadable files are reported, never silently skipped; an empty corpus
  warns loudly.
- Quotation awareness (ORI Guideline 2): a quoted verbatim run returns
  `QUOTED (verbatim; verify the citation)` and is **not** counted as a violation,
  while the same words unquoted remain `QUOTE + CITE (verbatim)`.
- Correction/erratum detection (ORI Guideline 17): `is-corrected-by`, `update-to`
  correction types and `erratum`/`corrigendum` records are reported as a **warning**,
  not a failure. Retraction remains a hard failure.

### Fixed
- **citation-report never read DOCX footnotes or endnotes, read text boxes twice, and refused a scan
  with the wrong reason and the wrong exit code.** A DOCX whose only graded sentence sat in a footnote
  reported zero sentences, `status: pass`, exit 0 — a document the tool could not read presented as a
  document with nothing to check; footnotes and endnotes are now parsed and graded, separators skipped.
  Text boxes were not skipped but duplicated (the paragraph walk descended into `w:txbxContent` while
  the holding run's own iterator reached the inner run), so a box sentence was graded twice; it is now
  read once, and the documents that claimed boxes were unread are corrected. A PDF with no text layer
  was refused with "no PDF text extractor is available" — blaming a missing tool for a document that
  has no text — and exited 1, the finding code, where the skill promises `insufficient_input`; it now
  names the missing text layer, says it is a scan, and exits 4. An **optional OCR tier was deliberately
  not shipped**: tesseract is absent here, so a transcription path would ship unexercised into the
  graded-sentence channel, and an OCR misread becomes an accusation about the author. The refusal half
  is implemented and names the install route; no hard dependency was added. Harness 111 → 125 checks,
  with its scan assertion changed from exit 1 to exit 4, and mutation-probed three ways. The documents
  also said tracked changes are "not read" when insertions (`w:ins`) *are* read and only deletions are
  not.
- **The patch system cried wolf on a good install.** `apply_patches.py` verified the patched files
  by shelling out to `py_compile`, which writes a `.pyc` into the interpreter's cache directory; when
  that directory is not writable — a sandboxed run, a read-only home, a container — a perfectly good
  install was reported as `failed=37` with a `SYNTAX ERROR` per file. It now compiles the patched
  source in memory, which needs no cache file, and the same run reports `applied=0
  already_applied=46 failed=0`. Installer version bumped to 1.1.0 to match the release.
- **Three vendored MCP servers reported a failed lookup as "no results".** `paper-search-mcp`'s
  openaire and unpaywall connectors swallowed every transport error into an empty result — a refused
  connection, a 429 and a 500 were indistinguishable from "nothing matched" (`search_openaire`
  returned `result=[]`, `search_papers(sources="openaire")` reported `status: empty` with no
  warning). `ncbi-mcp-server`'s `search_mesh_terms` turned a descriptor-fetch failure into a note
  saying the term "may not exist in the MeSH controlled vocabulary". `academic-search-mcp` returned
  `{"papers": []}` with no error key when all four providers had failed, and its diagnostic called an
  outage `provider_returned_no_candidates`. All three now distinguish "the API answered and holds no
  such record" from "the API could not be reached", using the `SourceUnavailable` / `_last_request_error`
  machinery already present in each codebase. 21 offline tests added, each stubbing the transport to
  raise and to return 429/500, with a genuine-zero control; the patch system's replacement files were
  brought back in step (37 byte-identical, 0 drifting) and the unreachable openaire snippet was
  replaced by a whole-file copy.
- **A statistical engine dropped the rows it could not use and pooled the rest as if complete.**
  `cochrane_meta.R`, `run_meta_analysis.R` and `forest_funnel.R` filtered out rows with a blank,
  non-numeric or zero effect size or standard error, then printed a pooled estimate in exactly the
  shape and exit code of a complete run — a review's headline number silently computed over a subset.
  They now write a `worklist.json` naming each dropped row and why, print an `INPUT CONDITION` block,
  and exit 3 **before writing any pooled estimate**; `--allow-incomplete` is the logged opt-out. The
  same treatment was applied to `validate_coding_sheet.py`, whose blank/zero rows were a hard error
  in the finding channel, and a missing sheet is now `insufficient_input` (exit 4) there and in the R
  scripts. Two studies with identical effects no longer print `I² = 0.0%`; with `QE <= k-1` the
  heterogeneity is reported as `not estimable`. The golden tests had discarded the engine's exit
  status and tested only the happy path; they now assert five refusal paths (17 → 22 checks).
- **Two guard skills reported an input they could not assess as a clean result.** `humanizerdrb`
  printed `No mechanical problems found.` and exited 0 for a 0-byte draft, a markup-only draft and a
  non-English draft, including one carrying an AI tell — a document it could not analyse reported as
  clean. It now refuses with `insufficient_input` (exit 3) and suppresses the clean wording.
  `meta-ml-screener` reported a screening log with no data rows through the finding channel
  (`Validation failed: 1 error(s)`, exit 1), indistinguishable from a genuine bad row; it is now an
  input condition (exit 3) reported on stderr with a JSON worklist. Both scripts gained a `--self-test`
  that drives `main()` — the humanizer's previous self-test passed even when `main()` was mutated to
  return 0 on a real finding.
- **Four instruction-only skills could not record a source they had not read.** Templates in
  `umbrella-review-skeptic` totalled "unique primary studies" with no field for a review whose list
  was unreadable, and two instructions turned a gap into a datapoint (a failed effect-size conversion
  became "direction and significance" for vote counting; an unavailable duration became a mean). In
  `environment-life-review-forge`, a study's core result was asserted as fact from a third-party
  summary while the source was recorded as abstract-level, and the text then argued that reading was
  "stronger than leaving the stress interaction as a black-box pattern". `paper-search` printed an
  error code in a results cell, contradicted itself on its own source count (27/28/30 — now 28,
  determined by counting its registry), and pointed at an architecture file no repository file
  creates. `meta-analysis` named a script without a path. One audit claim was checked and rejected:
  the `statistical-analysis` reference is an optional upstream skill the installer clones by default,
  not a broken one, and is left in place with the reason recorded.
- **A document in another language was graded and reported clean.** The language precondition tested
  a share of sentences matching any signal, and a bare digit is a signal, so one percentage was enough
  to make a 60-sentence Spanish document "readable" — `pass`, exit 0 — while a three-sentence Spanish
  document was exempted as too short to tell. The precondition now identifies the language from
  evidence independent of the English triggers (function-word share plus Latin-script share), splits
  the short-document exemption into "too short to tell" and "clearly another language", and blocks the
  latter. Citation-report harness 95 → 111 checks.
- **The five sibling gates named in `docs/EVIDENCE-INVARIANT.md` were audited, and all five broke
  the rule.** Each was answered by reading its code path and running it against a fixture where the
  input was missing; each fix ships a pass-and-fail test and is its own commit. The question-by-question
  answer, with the reproduction, is now in that document.
  - **`medical-narrative-review`** — a source row with `retrieval_status=empty`,
    `verification_status=verified`, `inclusion_status=included` and its ten extraction fields written
    as the sanctioned `not_reported` passed `validate_sources --strict`, `audit_citations --strict`
    and `gate.py` (`submission_ready: true`), all exit 0. `retrieval_status` was enum-checked and read
    by no decision path, so an extractor could claim what a paper did not report without anyone
    having obtained the paper. An unread citable source, and a verified claim joined to one, are now
    `insufficient_evidence` (exit 3) with a worklist in `input_gaps[]`; the gate refuses
    `submission_ready` and records the same status in `GATE_REPORT.json`. Harness: 19 → 29 checks.
  - **`sysreview` / PRISMA** — with `source_status=unavailable, hits=0`, the PRISMA-S appendix
    printed `embase … 0` and "reproducibility checks: OK", and the completeness gate printed
    "OK - retrieval and assessment complete", both exit 0. No script read `source_status` at all. The
    appendix now renders `unavailable (not reached)` and never the digit, and both it and the
    completeness gate exit 3 while stating that the identified total is a floor, not a total. A
    searched-and-empty database still renders `0` and still passes: zero is a finding when the source
    answered and unknown when it did not.
  - **`evidence-synthesis-forge` / citation gate** — a non-existent DOI and a resolver that refused
    the connection produced byte-identical stdout, `gate: FAIL`, exit 2 and the same DOI in
    `unresolved[]`/`failures[]`; with `--allow-unresolved` a total outage reported `gate: PASS`,
    exit 0. Transport failure is now a distinct status, a distinct key (`input_gaps[]`), a distinct
    gate word (`INCOMPLETE`) and exit 3, which `--allow-unresolved` cannot waive. `--recheck`
    re-checks only the identifiers a previous run could not check. Harness: 50 → 62 checks.
  - **`originality-check` / toolkit** — with three of four corpus files unreadable the report still
    showed "highest score: 0.813" and a full score table, exit 0; a wholly unreadable corpus or a
    nonexistent path gave "highest score: 0.000" plus the clean verdict shape. The unreadable files
    reached stderr and nothing else. They now appear in the markdown report, in `corpus.not_checked[]`
    in the JSON, and in the exit code (3); a corpus that loaded nothing prints no score line and no
    verdict at all. `sources.py` no longer reports a corpus that could not be read as `empty`. The
    toolkit gained a `--self-test`, wired into CI and into `verify.sh`, which now runs the *deployed*
    toolkit's self-test rather than only checking that the file exists.
  - **`citecheck`** — a draft with one resolvable and one unresolvable identifier wrote a reference
    list with no trace of the second and exited 0; an all-unresolvable draft wrote a one-byte file.
    That is a hard error by the skill's own `eval.md` C2. Every identifier that produced no entry now
    gets an `[UNRESOLVED]` or `[NOT CHECKED]` line in the artifact itself, and the run exits 2 (a
    finding) or 3 (an input gap), each with its own documented opt-out. `--self-test` added.
  - Two consumers inherited the same confusion and are fixed with the gates:
    `benchmarks/bench_accuracy.py` read the citation gate's old generic `error` status as *resolved*,
    so a lookup failure on a retracted paper counted as a missed retraction — the one number the
    920-citation benchmark exists to certify; and `acceptance_test.py` accepted any non-zero exit, so
    a network outage satisfied the adversarial test that exists to catch false greens.
  - README badge, totals and CI labels updated to **220** automated checks.
- **The README's "automated checks by suite" chart had drifted from the numbers it illustrated.** It
  showed four suites summing to 103 under a heading that said 198, and omitted `citation-report`'s 95
  entirely — while the composition chart directly beneath it derived its own counts from `git`
  precisely to avoid that failure. The chart now carries all five suites and **refuses to render** if
  their total disagrees with the README's stated count, so the two cannot drift apart again. Its
  composition chart had also begun refusing to render (`440` categories against `448` tracked files,
  its own guard working as designed): `benchmarks/` was missing from the list. The skills chart said
  12 skills against 13.
- **`verify.sh` reported the originality toolkit as MISSING when it was present in the
  checkout.** The `2b` block tested only the deployed path
  (`~/.research-stack/originality-toolkit`), so a run from a git checkout whose toolkit had not
  been installed yet printed `MISSING -> originality-check cannot run` — a claim about the
  *repository* that was false, when the toolkit was sitting in `tools/originality-toolkit/`. The
  block now separates three conditions, following the same pattern as the `2c`/`2d` harness
  blocks: deployed (PASS), not deployed but present in this checkout (FAIL with the actionable
  `run ./install.sh`, since the skill resolves the deployed path and would still not work), and
  absent from both (FAIL). The stale `12 gated skills` in the usage text and the hard-coded
  `all 13 review skills present` message are now derived from the `SKILLS` list, so the next skill
  added cannot leave a wrong count behind.
- **`install.sh` shipped a stale `__pycache__` with the originality toolkit.** The skills copy
  strips bytecode caches (`find … -name __pycache__ … -exec rm -rf`), but the toolkit copy at
  `install.sh:` did not, and `cp -R` does not preserve mtimes — so the deployed toolkit carried
  `.pyc` files whose recorded source time no longer matched the source beside them. The toolkit
  copy now strips them the same way.
- **Documentation stated a measurement under the wrong conditions.** The real-document
  distribution in `docs/BENCHMARK-RESULTS.md` §5 (`synthesis` 143, `unverifiable` 54, coverage
  28.4%) was labelled "`--offline`, no source PDFs supplied", but that is the
  **acquisition-enabled** run. Re-measured against the committed code: with no sources supplied the
  same document gives `unverifiable` **197**, `synthesis` **0** and coverage **0/503 = 0.0%**; with
  open-access acquisition it gives `synthesis` 143, `unverifiable` 54 and coverage 143/503 = 28.4%,
  still exiting 3 because 12 of 48 citing sources could not be obtained. Both runs are now printed
  side by side in `docs/BENCHMARK-RESULTS.md` and the README, because the difference — a coverage
  figure is a statement about the source bundle, not the manuscript — is the point rather than a
  footnote. Two arithmetic slips in the same section are corrected with it: the trigger fix moved
  `unattributed` 174 → **306** (not 311), so it unmasked **132** attribution-requiring sentences
  (not 137), matching the `no_citation_needed` fall of 656 → 524. The acquisition section's "0 to 32
  checkable citing sources" is likewise corrected to the re-measured end-to-end figure, **36**, with
  the module harness's own 20/60 yield (and the 47 sources holding abstract-or-better evidence) stated
  separately so two different measurements are no longer printed as one. No rule, test or metric
  changed — only the labels and the numbers in the documentation.
- `cross_verify_citations.py` — a DOI that is **not Crossref-registered** took an
  alternative-agency branch that returned *before any retraction check ran*, so a
  retracted paper could be reported `verified`. The three signals now run on both
  paths via a shared `apply_retraction_signals()`. This was the single missed
  retraction in the 920-citation benchmark; fixing it produced zero misses and the
  99% lower bound. Two offline regression guards added (helper + wiring).
- `cross_verify_citations.py` — retracted titles carry a `RETRACTED:`/`RETRACTED
  ARTICLE:` prefix at Crossref that PubMed's title lacks, so identical papers were
  reported as *"DOI resolves to a different paper"* (13 of 15 flagged mismatches).
  Prefixes are now stripped before comparison; flagged mismatches fell 15 → 2, and
  the 2 survivors are genuinely different papers.
- `check_numbers.py` — a significance claim and its p-value on **different lines**
  were downgraded to a warning and the manuscript **passed**. The check now joins a
  wrapped continuation line (only when the line does not end a sentence, so a later
  unrelated p-value is not attached to the claim). Sensitivity 87.5% → 100%.
- `paper-search-mcp` — `NameError` on every CiteSeerX PDF download (`os` never
  imported) and on every Elsevier full-text fetch (`assert_usable_bytes` never
  imported); fixed in the vendored file *and* its patch copy.
- `paper-search-mcp/cli.py` — duplicate `ALL_SOURCES` entries overwrote live
  coroutines (`RuntimeWarning: coroutine '_async_search' was never awaited`) and
  dropped results; `chemrxiv` was missing from the CLI registry entirely (27 vs 28
  sources). Both fixed; CLI and server now agree.
- `ncbi-mcp-server` — `CachedNCBIClient` had no `close()`, so every shutdown raised
  `AttributeError` and leaked the HTTP client; `advanced_search` silently dropped
  one-sided date ranges; analytics lost all data on a single unknown JSON key;
  `progressive_search` returned ~80% duplicate PMIDs.
- `ncbi-mcp-server/requirements.txt` — could not produce a working server: missing
  `python-dotenv`/`aiofiles`, and unconstrained `mcp>=1.0.0` pulled mcp 2.x and broke
  the v1 API. Now pins `mcp>=1.0.0,<2`.
- `install.sh` — an unexpanded glob created a symlink literally named `*` in the
  skills directory when a source list was empty; guarded.
- `academic-search-mcp` — `stats.py` emitted `NaN`, breaking strict-JSON clients.
- `originality_check.py` — default `--threshold` lowered 0.35 → 0.30 from measured
  score separation (independent text ≤ 0.115, copying ≥ 0.319); 0.35 missed light
  edits.
- Seven executable files hardcoded `/Users/drb/...` paths, so they only worked on one
  machine; now resolved relative to the script.
- Documentation accuracy: IEEE/ACM were advertised as working keyed sources but always
  raise `NotImplementedError` even with a key; "77 tools" → 87; "27 sources" → 28
  (27 work with zero config); "49 tests" → 51; `verify.sh --help` documented but
  absent; "each `NOTICE.md`" (3 of 12); "local CLIs make no network calls" (7 use
  `urllib.request`); the composition chart claimed 400 tracked files against 402
  (now derived from `git ls-files` and self-checking).

### Changed
- **The conflict ground truth was four positives wide, which made its interval the weakest number in
  the README.** Conflict precision is the figure an accusation has to be able to defend, and at four
  positives the Wilson lower bound was **0.510** — too small a set to distinguish "the rules work"
  from "the rules worked four times". The labelled set now holds **26** conflict positives, built from
  mechanisms that fail differently rather than repetitions of one: eight effect measures (HR, RR, OR,
  MD, SMD, IRR, PR, beta) each contradicted in both directions, a contradiction that *reverses* the
  direction of the recorded effect, retraction where the quoted figure is correct, and citation
  numbers the reference list cannot account for. All 26 classify correctly, so precision stays 1.000
  and its lower bound moves to **0.871**; whole-set rule and state agreement rose from 26/26 to
  **48/48** (lower bound 0.871 → 0.926). Ten new evidence sources were added to the fixture, each
  carrying a different recorded measure, and the fixture is still the ground truth's only source: if
  the two disagree the benchmark reports the misclassification rather than passing. The set remains
  author-written, which is stated where the numbers are printed — it shows the rules do what they were
  designed to do, not that they generalise.

### Known limitations
- **ORI Guideline 4 (syntactical structure) is not caught.** A paraphrase that changes
  every content word but keeps the source's sentence structure is plagiarism under the
  ORI guide yet scores near zero on lexical overlap. Two stdlib-only frame measures were
  implemented and measured; neither separates frame-copying from unrelated text
  (unrelated reached 0.857 against frame-copies from 0.533), so the frame number is
  reported but drives no verdict. **A clean report does not cover frame-copying.**
- Retraction and resolution benchmarks are live (network-dependent) and were run on one
  day; provider-side changes could move the numbers.

## [1.0.0] — 2026-10-07

First release: reliable literature-review tooling for AI coding agents.

### Added
- **One-command installer** (`install.sh`, `bootstrap.sh`) that wires MCP servers
  and skills into Cline, Claude, OpenCode, Gemini, LM Studio, Trae, Cursor and
  Windsurf (+ Codex skills). Non-destructive — existing configs are backed up and
  only managed keys are merged.
- **5 MCP servers**: `paper-search` (27 free sources), `ncbi`, `academic-search`,
  `consensus`, `google-scholar`.
- **12 review/guard skills**: `sysreview`, `meta-analysis`,
  `evidence-synthesis-forge`, `meta-analysis-forge`, `medical-narrative-review`,
  `umbrella-review-skeptic`, `meta-ml-screener`, `environment-life-review-forge`,
  `paper-search`, `citecheck`, `humanizerdrb`, `originality-check`.
- **Gates** that make a false citation, a number nobody computed, or a
  contradictory PRISMA flow fail loudly instead of passing quietly.
- **Vendored MCP sources** (installed offline, no PyPI / upstream dependency):
  `mcp/paper-search-mcp/` (upstream `v0.1.4` + 43 patched modules),
  `mcp/ncbi-mcp-server/` (patched fork), `mcp/academic-search-mcp/` (`0.8.0+local1`).
- **`originality-toolkit`** (23 files) and `verification_report.py`.
- **103 automated checks**: evidence-synthesis-forge selftest (50),
  meta-analysis-forge golden tests (17), medical-narrative-review selftest (19),
  live adversarial acceptance run (17).
- **Charts** (`assets/*.svg`) and their generator (`scripts/make_readme_charts.py`).

### Fixed
- **MeSH query planner** expanded common words to a *subheading's* entry terms
  (`screening → diagnosis, signs, findings, symptoms`); it now reads NCBI's
  authoritative mapping (`screening → mass screening, early detection of cancer`).
- Vendored `paper-search-mcp` `pyproject.toml` under-constrained `mcp[cli]` (a
  fresh install pulled mcp 2.x and broke import) → pinned `mcp[cli]>=1.27.2,<2`
  and `fastmcp>=3.4.2,<4`, matching the working environment.
- Installer `cp -R` failed when a destination's parent directory did not exist
  (added `mkdir -p`); the `ncbi` install omitted `aiofiles`, required by the server.
- Skills hard-coded `~/.cline/skills` (broke parity on Claude/OpenCode) → made
  location-independent; `ncbi`/`academic-search` were configured but not installed.

### Changed
- `install.sh` installs `paper-search` from the **vendored source** by default;
  `--from-pypi` keeps the legacy PyPI + runtime-patch path.

### Security
- No secrets in the repository (secret-scanned); the vendored forks deliberately
  exclude their `.env*` files; the installer writes configs and `.env` with
  mode `600`.

[Unreleased]: https://github.com/drb253/research-stack/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/drb253/research-stack/releases/tag/v1.1.0
[1.0.0]: https://github.com/drb253/research-stack/releases/tag/v1.0.0
