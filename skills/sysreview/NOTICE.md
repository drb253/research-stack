# NOTICE — /sysreview skill

This skill (`sysreview`) is original orchestration code plus merged methodology from
open-source projects. It ships under the MIT licence (see the local EvidenceForge
`EvidenceForge-LICENSE.txt`).

## Merged sources

| Source | Licence | What was derived |
|---|---|---|
| AngelChen-HC/systematic-review-skill v8.1 | Apache-2.0 | `references/screening-governance.md` (calibration pilots, κ≥0.60 gate, criteria lock, eligibility-rules registry, audit-log spec, reproducibility honesty) |
| barah123/Claude-Biomedical-Research-Skills | MIT | `references/…/prospero-and-citation-verification.md`; `scripts/prospero_search.py` (verbatim, reattributed) |
| keemanxp/slr-prisma | MIT | `references/prisma-2020-manuscript-reporting.md` (27-item checklist + flow-diagram structure) |
| Aperivue/medsci-skills (check-reporting) | MIT | `references/reporting-guideline-checklists.md` (instrument index; licence tiers preserved) |
| Imbad0202/academic-research-skills-codex | see upstream (MIT-family) | `references/cross-model-verification.md` (consent-gated protocol, condensed) |
| PRISMA 2020 (Page et al., BMJ 2021;372:n71) | CC BY 4.0 | Checklist item text |
| Reporting-guideline checklists (various) | CC BY / CC BY-NC / none | See the licence tiers in the checklists reference — NC and no-licence instruments are own-words summaries only |

## Scripts

- `scripts/…` referenced from `evidence-synthesis-forge/scripts/` — `cross_verify_citations.py`
  (original, MIT) and `prospero_search.py` (from barah123, MIT).

Nothing here is detector-evasion tooling; `humanizerdrb` refuses that by design.
