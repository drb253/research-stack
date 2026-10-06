# Cochrane Handbook map — which chapter governs which decision

**Verified against the source text:** *Cochrane Handbook for Systematic Reviews of
Interventions*, **2nd edition (2019)**, Higgins JPT, Thomas J, Chandler J, Cumpston M, Li T,
Page MJ, Welch VA (eds). © 2019 The Cochrane Collaboration / John Wiley & Sons Ltd.
Section numbers and quoted wording below were checked directly against that edition, not
recalled. The **online version continues to be updated** (it is currently at v6.5, 2024); cite
the version you actually used, and re-verify a section number if the online version differs.

This is a routing map, not a substitute for the chapter. © Cochrane — paraphrase and cite;
do not reproduce the Handbook verbatim.


## Stage → governing chapter → the decision it settles

| Stage | Chapter | Rules to apply |
|---|---|---|
| Scoping the question | 2 | Frame the question; decide the **comparison(s)** the review will address and the outcome set up front. |
| Inclusion criteria & grouping | 3 | Pre-specify inclusion/exclusion; decide which **study designs** are eligible and **how studies will be grouped for synthesis** (this decision precedes and constrains pooling). |
| Search | 4 (+4.S1 tech. supplement) | Search **multiple** sources; design strategies per database; central register + databases + trials registers + grey literature; document the strategy and the date run. |
| Data collection | 5 | Pre-specify and pilot the extraction form; extract **twice** or verify; handle multiple reports of the same study; document decisions. |
| **Effect measures** | 6 | Choose the effect measure per outcome type (dichotomous: OR/RR/RD; continuous: MD/SMD; time-to-event: HR; counts/rates). State the SMD variant; handle direction and scale conversion explicitly. |
| Bias & conflicts of interest | 7 | Assess bias arising from study conduct and from the review process; collect funding/COI data. |
| Risk of bias — RCTs | 8 | **RoB 2**, five domains + overall. Do not apply RoB 2 to non-randomised studies. |
| Preparing for synthesis | 9 | Summarise study characteristics; decide which studies are **comparable enough** to combine; keep the synthesis plan pre-specified. |
| **Meta-analysis** | 10 | Model choice (fixed vs random, and why); weights; **τ² estimator**; **I² and τ² and prediction interval**; subgroup analysis; **meta-regression (≥10 studies)**; sensitivity analysis; dose–response; individual-vs-aggregate. |
| Network meta-analysis | 11 | Only when a connected network exists; assess **transitivity** and **inconsistency**; report network geometry. |
| Synthesis without meta-analysis | 12 | **SWiM** reporting for structured narrative synthesis when pooling is inappropriate. |
| Bias due to missing results | 13 | Assess **reporting bias / missing results** (ROB-ME), not only publication bias; funnel/Egger **need ≥10 studies** to be informative. |
| Certainty & Summary of findings | 14 | **GRADE** certainty per outcome; build **SoF** tables; five downgrade domains, three upgrade reasons. |
| Interpreting results | 15 | Grade the strength of conclusions to the certainty of evidence; do not over-claim. |
| Variants on RCTs | 23 | Cluster, cross-over, multi-arm, factorial — different unit-of-analysis handling. |
| Non-randomised studies | 24–25 | Include with **ROBINS-I / ROBINS-E**; expect confounding control requirements. |
| Individual participant data | 26 | IPD workflows and analysis planning. |
| Figures | **III.S1** | Official guidance on statistical graphs in Cochrane reviews (forest, funnel, etc.). |

## The four "amateur-vs-expert" failure points this map prevents

Each is verified against the 2nd edition (2019) text, with the section cited.

1. **Funnel-plot tests below 10 studies.** *"As a rule of thumb, tests for funnel plot
   asymmetry should be used only when there are at least 10 studies included in the
   meta-analysis, because when there are fewer studies the power of the tests is low"*
   (Ch. 13, reporting Sterne et al. 2011). Our engine warns and omits the plot below k = 10.
2. **Meta-regression on too few studies.** *"Meta-regression should generally not be considered
   when there are fewer than ten studies in a meta-analysis"* (**§10.11.4**). Our engine warns
   below k = 10 and the reference states the rule.
3. **Reporting heterogeneity as a bare I².** *"Thresholds for the interpretation of the I²
   statistic can be misleading, since the importance of inconsistency depends on several
   factors"* (**§10.10.2**); the 0–40/30–60/50–90/75–100% bands are a *rough* guide and
   overlap. Report **τ² and a prediction interval** (**§10.10.4.3**), not I² alone.
4. **Choosing the model by an I²-significance rule.** *"The decision between fixed- and
   random-effects meta-analyses has been the subject of much debate, and we do not provide a
   universal recommendation"* (**§10.10.4**). The choice follows whether the studies'
   intervention effects are plausibly identical — never a heterogeneity test's p-value.

## Verified section index

| Rule | Section |
|---|---|
| Identifying and measuring heterogeneity; I² definition and its threshold caveat | **§10.10.2** |
| Fixed- vs random-effects; no universal recommendation | **§10.10.4** |
| Prediction intervals from a random-effects meta-analysis | **§10.10.4.3** |
| Subgroup analyses | **§10.11.3** |
| Meta-regression; <10-studies caution | **§10.11.4** |
| Hartung–Knapp–Sidik–Jonkman CI adjustment | **§10.10.4.3** (adjacent) |
| Funnel-plot asymmetry tests; ≥10-studies rule | **Ch. 13** |
| RoB 2 domains (randomisation process; deviations from intended interventions; missing outcome
data; measurement of the outcome; selection of the reported result) | **§8.5–8.7 + Ch. 8 opening** |
| GRADE five domains (risk of bias, inconsistency, indirectness, imprecision, publication bias) | **Ch. 14** |


## Software the Handbook assumes

RevMan (Cochrane's own), plus R (`metafor`, `meta`, `netmeta`) and Stata. This skill runs
R (`metafor`/`meta`/`netmeta`/`robumeta`/`clubSandwich`/`robvis`); it produces
RevMan-compatible numbers and GRADEpro-style SoF tables rather than driving those GUIs.
