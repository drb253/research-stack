# Statin therapy in hyperlipidaemia: a worked example

## Results

Statin therapy reduced major adverse cardiovascular events in adults with hyperlipidaemia (HR 0.80) [src:S001].

Statin therapy was studied in a large randomised trial [src:S001].

Vitamin D supplementation reduced all-cause mortality in adults (RR 0.70) [src:S002].

Statin therapy reduced mortality by 55% [src:S001].

Prevalence of hyperlipidaemia in this cohort was 12.4%.

Statin therapy is the first-line treatment for hyperlipidaemia [src:S003].

An exploratory analysis suggested that statins may reduce stroke risk [99].

Low-density lipoprotein cholesterol is a modifiable risk factor.

## Discussion

These findings are consistent with previous work [src:S001].

<!--
Shipped example for citation-report, and the pass fixture in scripts/selftest.sh.
This comment is not rendered, so it is not graded: intake strips HTML comments.

Expected states, in document order, with the rule each must fire:

  1  HR 0.80 is recorded for S001                -> attributed          D09
  2  cited, no independently checkable value     -> synthesis           D10
  3  S002 is retracted                           -> conflict  (ERROR)   D04
  4  55% is absent from S001's recorded evidence -> unverifiable (warn) D07
  5  12.4% with no citation at all               -> unattributed (warn) D02
  6  S003 is identified but holds no evidence    -> unverifiable        D05
  7  citation 99 matches no source, and the
     apparatus is closed (S001-S003), so this
     is a finding rather than a gap in inputs    -> conflict  (ERROR)   D03
  8  no signal and no marker                     -> no_citation_needed  D01
  9  "previous work" is a vague attribution,
     S001 has evidence, no checkable value       -> synthesis           D10

Distribution: attributed 1, synthesis 2, unverifiable 2, unattributed 1,
conflict 2, no_citation_needed 1  =  9 sentences.
Requiring a citation: 8. Covered (attributed + synthesis): 3. Coverage 3/8 = 37.5%.
Gate: 2 errors, so the report is a diagnostic and the process exits non-zero.
-->
