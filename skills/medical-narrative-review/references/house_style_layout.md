# House style — the designed critical-review edition

The skill ships two exports. The **baseline** (`export_document.py`) is the format guarantee: DOCX,
PDF and HTML with no third-party packages. The **designed edition** (`house_style_build.py` plus
`house_style_render.py`) is the reader-facing artifact: a cover-led, print-laid-out critical review.
Both read the same verified ledgers. Neither writes prose.

## When to use which

| Situation | Export |
|---|---|
| Journal submission needing Word | Baseline DOCX from `export_document.py` |
| Circulation, preprint, report, or client delivery | Designed PDF from `house_style_render.py` |
| No Chromium available | Designed HTML from `house_style_build.py`; baseline PDF |
| Gate run | Baseline exports, because `gate.py --require-exports` inspects `final/` |

## Document structure

The builder emits, in order: cover, abstract, contents, numbered body sections, declarations,
appendices, references. Every section starts on a new page.

1. **Cover.** Full-bleed navy-to-teal gradient, a 26 px grid at 14% opacity, two soft glows, an
   eyebrow in uppercase with wide tracking, the title at 29 pt with one gold-accented phrase, a
   subtitle at 13 pt, a 96 px gold rule, a meta block, pill badges, and a footer rule with the
   preparation line and date.
2. **Abstract.** A tinted, rounded box containing labelled paragraphs (Background, Objective,
   Methods, Key findings, Conclusions) and a keywords line. An optional key box below carries the
   one-line verdict.
3. **Contents.** Dotted leaders, section number in teal, page number right-aligned in tabular
   figures. Page numbers are resolved from the rendered PDF, so they are true pages, never estimated.
4. **Body.** Numbered sections: a navy rounded badge holding the number, then the heading at 17 pt.
   Subsections are numbered `2.1`, `2.2` in teal at 12.4 pt. Prose is justified Palatino at 10.3 pt
   with 1.5 line height.
5. **Callouts.** Four kinds, each a left-ruled tinted box: `key` teal, `warn` amber, `crit` red,
   `good` green. Used for the definition, the scope limits, a contested finding, a commons problem,
   and what working integration looks like.
6. **Tables.** Navy header row, 7.9 pt white header text, hairline rules, zebra striping at #F5F9FC,
   caption above in 8.9 pt with a bold table number. Certainty pills: high green, moderate amber,
   low red.
7. **Figure.** The screening flow is embedded as inline SVG, so it stays vector and never depends on
   a rasteriser.
8. **References.** Hanging indent, number in navy, DOI in teal with word breaking.
9. **Footer.** On every page except the cover: a hairline rule, the short title at 6.6 pt grey, and
   `n / N` right-aligned in navy bold. Chromium cannot emit CSS page counters, so the footer is
   overlaid with reportlab after printing.

## Design tokens

| Token | Value | Use |
|---|---|---|
| `--navy` | `#0B3D6B` | Headings, table headers, badges |
| `--teal` | `#0E7C7B` | Section numbers, subsection headings, key boxes |
| `--amber` | `#C4820F` | Warnings, moderate certainty |
| `--red` | `#B3261E` | Critical boxes, low certainty |
| `--green` | `#1E7A46` | Good-practice boxes, high certainty |
| `--ink` | `#16212b` | Body text |
| `--muted` | `#5B6B7C` | Captions, footer, small print |
| `--line` | `#CBD5E1` | Table rules, hairlines |
| `--bg`, `--bg2` | `#F1F6FA`, `#E7F0F7` | Abstract box, key box, sub-rows |
| Page | A4, 16 mm top/bottom, 13 mm left/right, cover margin 0 | Print geometry |
| Body face | Palatino Linotype / Book Antiqua / Palatino / Times New Roman | Serif prose |
| Display face | Segoe UI / Helvetica Neue / Helvetica / Arial | Headings, tables, cover |

## Command line

```bash
python3 scripts/house_style_build.py --workspace <review-dir> \
  --out final/house_style.html --config house_style.json --toc toc_pages.json

python3 scripts/house_style_render.py --workspace <review-dir> \
  --html final/house_style.html --out "<Review_Title>_Critical_Review.pdf"
```

`house_style_build.py` prints a JSON report with the output path, manifest path, section count,
reference count, and table and figure counts. It exits non-zero only when the manuscript is missing.

`house_style_render.py` runs the builder twice (pass 1 to locate headings, pass 2 to print true
contents page numbers), overlays the footer, then verifies. It prints a verification block and exits
non-zero on any layout failure.

## Presentation config

Write `house_style.json` in the workspace. Unknown keys are ignored; missing keys fall back to a
derived value. `assets/house_style_template.json` is a complete starting point.

| Key | Type | Default | Notes |
|---|---|---|---|
| `title` | string | manuscript H1 | Cover headline |
| `short_title` | string | title before the colon | Running footer |
| `accent` | string | none | Phrase inside the title rendered in gold |
| `eyebrow` | string | `Critical Review` | Uppercase tracked line |
| `subtitle` | string | neutral sentence | Accepts inline HTML |
| `meta` | list of strings | article type, citation style, evidence base | Accepts inline HTML |
| `badges` | list of strings | `keywords` or two generic badges | Cover pills |
| `footer_left`, `footer_right` | string | preparation line, blank | Cover footer |
| `verdict`, `verdict_heading` | string | empty | Key box under the abstract |
| `callouts` | list of objects | empty | `section` must match the H2 title, the displayed heading, or the section number |
| `callout.kind` | enum | `key` | `key`, `warn`, `crit`, `good` |
| `display_titles` | object | empty | Maps an H2 title to a longer contents label |
| `table_captions` | object | empty | Maps a section title to a list of captions, applied in order |
| `figure_caption` | string | empty | Inserted into Appendix B's figure |
| `abbreviations` | object | empty | Appended as Table 3 to Appendix D |
| `evidence_table_caption`, `certainty_table_caption` | string | neutral text | Captions for Tables 1 and 2 |
| `search_caption` | string | neutral text | Caption for Table A1 |

## Invariants

1. **Content comes only from the ledgers.** The builder reads `final/manuscript_cited.md`, the three
   CSVs, the reference list and the figure. It never invents a sentence, a row, or a number.
2. **Tables are generated, not typed.** Table 1 groups `sources.csv` by theme; Table 2 renders
   `claims.csv` with its certainty pills; Table A1 renders `search_log.csv`.
3. **A section with no data is skipped, not faked.** An empty ledger produces no table.
4. **Appendix E is skipped.** It duplicates the generated Tables 1 and 2 inside the manuscript.
5. **Verification is part of rendering.** A missing heading, a blank page, a reference with no entry,
   or an out-of-range citation fails the render.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| All contents page numbers show `\u2014` | Pass 1 could not locate headings | Check that every H2 begins its page; re-run the renderer |
| Contents numbers all identical | A cross-reference matched before the heading | Headings are matched at the top of a page only; ensure sections break before |
| Literal `%s` or `&mdash;` in the PDF | Unescaped config string | Fix the string in `house_style.json` |
| Table splits leaving two rows on a page | A long table with no keep rule | Accept, or shorten the table; the abbreviations table carries `keep` |
| Renderer exits with an import error | Playwright, pypdf or reportlab absent | Install them in a venv, or deliver the HTML and the baseline PDF |
| Duplicate evidence tables | Appendix E was not skipped | Keep the `evidence tables` hint in `SKIP_TITLE_HINTS` |
