#!/usr/bin/env python3
"""Measure the citation-report deterministic channel against hand-labelled sentences.

What is measured, and why it is the thing worth measuring:

* **Trigger precision and recall** — whether a sentence is judged to need attribution
  at all. This is the noisiest decision in the pipeline, because "needs a citation" is
  a judgment about prose. Over-triggering produces orange findings a careful author
  rightly rejects, which costs the report its credibility faster than a miss does.
* **State precision and recall per rule** — whether each sentence lands in the state
  the rule table says it should.
* **Conflict precision, which must be 1.00.** A red finding is an accusation of a
  fabricated citation, a retracted source, or a contradicted value. There is no
  acceptable rate of false accusation here, so the script fails loudly if conflict
  precision drops below 1.0. Narrow the offending rule rather than accepting the
  error rate.

The pipeline is exercised through its real command line, not reimplemented: this
script writes a document and a ledger, runs `report.py report --format json`, and
reads the `verdicts.json` it produces. A benchmark that reimplements the classifier
measures the benchmark.

Ground truth is hand-assigned and printed in full, so a reader can check every label.
Every uncertainty interval is a Wilson 95% interval, because a bare point estimate on
20-odd cases invites more confidence than the sample supports.

Not measured: the advisory channel's accuracy. No calibrated grader ships with this
skill, precisely because the repository's own measurement of a comparable classifier
found chance-level accuracy on a wide choice and a failure on a causality trap
(`skills/medical-narrative-review/references/advisory_decision_plan.md`). The
advisory channel is measured for *inertness* instead, by `scripts/selftest.sh`.

Usage:
    python3 bench_verdicts.py             # human-readable
    python3 bench_verdicts.py --json      # machine-readable
"""

from __future__ import annotations

import csv
import io
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REPORT = REPO / "skills" / "citation-report" / "scripts" / "report.py"
PY = sys.executable

# --------------------------------------------------------------------------- #
# Evidence held for each source
# --------------------------------------------------------------------------- #

# Evidence is not written separately: it is exactly what the ledger columns below
# record, and the pipeline assembles it. The values the labels depend on are
#   S001: HR 0.80, n = 1000, follow-up 24 months, outcome "major adverse cardiovascular events"
#   S002: RR 0.70, retracted
#   S003: no result-bearing field at all, so it is metadata and cannot support a claim
# Anything the labels expect to be found must therefore appear in this CSV, which
# keeps the fixture and the ground truth from drifting apart: if they disagree, the
# benchmark reports the misclassification rather than silently passing.

SOURCES_CSV = """source_id,title,authors,container,year,volume,issue,pages,doi,pmid,pmcid,publication_type,peer_reviewed,study_design,population,intervention,comparator,n_participants,follow_up,key_outcomes,main_finding,effect_estimate,verification_status,verifier,verified_date,locator,retraction_status,inclusion_status,exclusion_reason,retrieval_status,theme,notes
S001,Statin therapy and cardiovascular events,Smith J,Demo Journal,2020,382,5,100-110,10.1056/NEJMoa1234567,12345678,PMC1,randomised_trial,yes,randomised controlled trial,adults with hyperlipidaemia,statin,placebo,1000,24 months,major adverse cardiovascular events,Statin therapy reduced major adverse cardiovascular events,HR 0.80 (95% CI 0.70-0.92),verified,bench,2026-01-01,abstract,clear,included,,returned,treatment,
S002,Retracted vitamin D trial,Doe A,Demo Journal,2019,365,1,1-9,10.1136/bmj.retracted1,99999999,PMC2,randomised_trial,yes,randomised controlled trial,adults,vitamin D,placebo,500,12 months,all-cause mortality,Vitamin D supplementation reduced all-cause mortality,RR 0.70 (95% CI 0.55-0.89),verified,bench,2026-01-01,abstract,retracted,included,,returned,treatment,
S003,Overview of lipid lowering,Roe B,Demo Review,2021,12,3,200-215,10.9999/demo.review.2021,12345670,PMC3,review,yes,narrative review,adults with hyperlipidaemia,not_applicable,not_applicable,not_reported,not_reported,not_reported,not_reported,not_reported,verified,bench,2026-01-01,abstract,clear,cited_for_context,,returned,treatment,
 S005,Metformin and mortality in type 2 diabetes,Lee C,Demo Journal,2022,400,2,50-60,10.1000/demo.s005,,,randomised_trial,yes,randomised controlled trial,adults with type 2 diabetes,metformin,placebo,2400,36 months,all-cause mortality,Metformin reduced all-cause mortality,RR 0.75 (95% CI 0.62-0.91),verified,bench,2026-01-01,abstract,clear,included,,returned,treatment,
 S006,Dexamethasone and ICU admission,Ng D,Demo Journal,2023,411,1,10-20,10.1000/demo.s006,,,cohort_study,yes,prospective cohort,adults with severe infection,dexamethasone,usual care,880,28 days,ICU admission,Dexamethasone was associated with higher ICU admission,OR 1.42 (95% CI 1.10-1.83),verified,bench,2026-01-01,abstract,clear,included,,returned,treatment,
 S007,Exercise and systolic blood pressure,Patel E,Demo Journal,2021,15,4,300-310,10.1000/demo.s007,,,randomised_trial,yes,randomised controlled trial,adults with hypertension,exercise,control,310,12 weeks,systolic blood pressure,Exercise lowered systolic blood pressure,MD 3.20 (95% CI 1.30-5.10),verified,bench,2026-01-01,abstract,clear,included,,returned,treatment,
 S008,Mindfulness and depression score,Kim F,Demo Journal,2020,8,1,1-11,10.1000/demo.s008,,,randomised_trial,yes,randomised controlled trial,adults with depression,mindfulness,waitlist,520,8 weeks,depression score,Mindfulness reduced depression severity,SMD 0.45 (95% CI 0.28-0.62),verified,bench,2026-01-01,abstract,clear,included,,returned,treatment,
 S009,Adjuvant therapy and recurrence,Oka G,Demo Journal,2019,7,3,77-88,10.1000/demo.s009,,,randomised_trial,yes,randomised controlled trial,adults with resected cancer,adjuvant chemotherapy,observation,1800,60 months,cancer recurrence,Adjuvant chemotherapy reduced recurrence,HR 1.25 (95% CI 1.05-1.49),verified,bench,2026-01-01,abstract,clear,included,,returned,treatment,
 S010,Thiazide and incident fractures,Ruiz H,Demo Journal,2018,6,2,120-130,10.1000/demo.s010,,,cohort_study,yes,retrospective cohort,older adults,thiazide,no thiazide,4200,48 months,incident fractures,Thiazide use was associated with fewer fractures,IRR 0.62 (95% CI 0.51-0.75),verified,bench,2026-01-01,abstract,clear,included,,returned,treatment,
 S011,Sleep duration and cognitive score,Ibrahim I,Demo Journal,2024,20,5,400-412,10.1000/demo.s011,,,cohort_study,yes,prospective cohort,older adults,sleep duration,not_applicable,640,24 months,cognitive score,Longer sleep duration predicted a higher cognitive score,beta 0.34 (95% CI 0.12-0.56),verified,bench,2026-01-01,abstract,clear,included,,returned,prognosis,
 S012,Screening and mortality prevalence ratio,Novak J,Demo Journal,2017,4,4,44-52,10.1000/demo.s012,,,cohort_study,yes,cross-sectional survey,adults,screening,no screening,1500,not_reported,mortality,Screen-detected cases had lower mortality prevalence,PR 0.88 (95% CI 0.79-0.98),verified,bench,2026-01-01,abstract,clear,included,,returned,epidemiology,
 S013,Retracted calcium trial,Olsen K,Demo Journal,2016,3,3,33-41,10.1000/demo.s013,,,randomised_trial,yes,randomised controlled trial,adults,calcium,placebo,700,18 months,cardiovascular events,Calcium supplementation reduced cardiovascular events,RR 0.60 (95% CI 0.45-0.80),verified,bench,2026-01-01,abstract,retracted,included,,returned,treatment,
 S014,Retracted antiviral trial,Petrov L,Demo Journal,2015,2,1,5-15,10.1000/demo.s014,,,randomised_trial,yes,randomised controlled trial,adults,antiviral,placebo,400,30 days,mortality,Antiviral therapy reduced mortality,OR 2.10 (95% CI 1.40-3.10),verified,bench,2026-01-01,abstract,retracted,included,,returned,treatment,
"""

# --------------------------------------------------------------------------- #
# Hand labels
# --------------------------------------------------------------------------- #

#: (sentence as it appears in the document, expected rule, why this label)
#:
#: The `why` field is the label's justification, printed in the output so a reader can
#: audit the ground truth rather than take it on trust.
CASES = [
    ("Statin therapy reduced major adverse cardiovascular events (HR 0.80) [src:S001].",
     "D09", "HR 0.80 is recorded for S001"),
    ("A total of 1000 adults were randomised [src:S001].",
     "D09", "1000 is recorded for S001"),
    ("Median follow-up was 24 months [src:S001].",
     "D09", "24 is recorded for S001"),
    ("Statin therapy was studied in a large randomised trial [src:S001].",
     "D10", "cited, resolves, no checkable value"),
    ("Studies suggest that statins are effective [src:S001].",
     "D10", "vague attribution but cited, and no checkable value"),
    ("These findings are consistent with previous work [src:S001].",
     "D10", "vague attribution but cited, and no checkable value"),
    ("Statin therapy reduced mortality by 55% [src:S001].",
     "D07", "55% is absent from S001's evidence"),
    ("The trial enrolled 616 participants [src:S001].",
     "D07", "616 is absent from S001's evidence"),
    ("Statin therapy reduced events (HR 0.50) [src:S001].",
     "D08", "HR 0.50 contradicts the recorded HR 0.80"),
    ("Vitamin D reduced all-cause mortality (RR 0.70) [src:S002].",
     "D04", "S002 is retracted"),
    ("Statin therapy is the first-line treatment [src:S003].",
     "D05", "S003 is identified but holds no evidence"),
    ("An exploratory analysis suggested a benefit [99].",
     "D03", "citation 99 matches no source, and S001-S003 close the apparatus"),
    ("Prevalence was 12.4%.",
     "D02", "a statistic with no citation"),
    ("CPTSD is defined as PTSD plus disturbances in self-organisation.",
     "D02", "a borrowed definition with no citation"),
    ("The largest trial reported a benefit.",
     "D02", "a superlative claim with no citation"),
    ("It is well established that statins reduce events.",
     "D02", "a vague attribution with no citation"),
    ("Statin therapy is known as a lipid-lowering intervention.",
     "D02", "a definitional construction with no citation"),
    ("Low-density lipoprotein cholesterol is a modifiable risk factor.",
     "D01", "no signal, no marker"),
    ("The analysis was cross-sectional.",
     "D01", "a method statement, not an external claim"),
    ("We searched three databases.",
     "D01", "spelled-out number, no signal"),
    ("At least one study examined this.",
     "D01", "'at least one' must not read as a superlative claim, and 'study examined' must not fire "
            "as an attribution: this is the review's own scope, not another author's finding. This is "
            "the case that rejected extending the reporting verbs to address/examine -- see the "
            "trigger-miss experiment in docs/BENCHMARK-RESULTS.md"),
    ("At most three studies were included.",
     "D01", "'at most' must not read as a superlative claim"),
    ("Most participants were female.",
     "D01", "a majority statement without 'the most', folded into D01 by design"),
    # --- Conflict ground truth, widened ----------------------------------------- #
    # The first revision had four conflict positives, which put the Wilson lower bound on
    # conflict precision at 0.51 -- the thinnest number in the README, and the one an
    # accusation has to be able to defend. These cases reach the *same* decision through
    # distinct mechanisms rather than repeating one: eight different effect measures, each
    # contradicted in both directions (over- and under-statement), a contradiction against a
    # value the trial itself records, retraction that outranks a correctly quoted figure, and
    # a fabricated citation number. Every one is a case the rules were designed to catch, so a
    # failure here is a defect rather than a surprise.
    ("Metformin reduced all-cause mortality (RR 0.68) [src:S005].",
     "D08", "RR 0.68 is not the recorded RR 0.75"),
    ("Metformin reduced all-cause mortality (RR 0.90) [src:S005].",
     "D08", "RR 0.90 is not the recorded RR 0.75"),
    ("Dexamethasone was associated with ICU admission (OR 1.15) [src:S006].",
     "D08", "OR 1.15 contradicts the recorded OR 1.42"),
    ("Dexamethasone was associated with ICU admission (OR 1.90) [src:S006].",
     "D08", "OR 1.90 contradicts the recorded OR 1.42"),
    ("Exercise lowered systolic blood pressure (MD 1.10) [src:S007].",
     "D08", "MD 1.10 contradicts the recorded MD 3.20"),
    ("Exercise lowered systolic blood pressure (MD 5.40) [src:S007].",
     "D08", "MD 5.40 contradicts the recorded MD 3.20"),
    ("Mindfulness reduced depression severity (SMD 0.22) [src:S008].",
     "D08", "SMD 0.22 contradicts the recorded SMD 0.45"),
    ("Mindfulness reduced depression severity (SMD 0.70) [src:S008].",
     "D08", "SMD 0.70 contradicts the recorded SMD 0.45"),
    ("Adjuvant chemotherapy reduced recurrence (HR 0.85) [src:S009].",
     "D08", "HR 0.85 reverses the direction of the recorded HR 1.25"),
    ("Adjuvant chemotherapy reduced recurrence (HR 1.60) [src:S009].",
     "D08", "HR 1.60 contradicts the recorded HR 1.25"),
    ("Thiazide use was associated with fewer fractures (IRR 0.80) [src:S010].",
     "D08", "IRR 0.80 contradicts the recorded IRR 0.62"),
    ("Thiazide use was associated with fewer fractures (IRR 0.45) [src:S010].",
     "D08", "IRR 0.45 contradicts the recorded IRR 0.62"),
    ("Longer sleep duration predicted a higher cognitive score (beta 0.15) [src:S011].",
     "D08", "beta 0.15 contradicts the recorded beta 0.34"),
    ("Longer sleep duration predicted a higher cognitive score (beta 0.55) [src:S011].",
     "D08", "beta 0.55 contradicts the recorded beta 0.34"),
    ("Screen-detected cases had lower mortality (PR 0.70) [src:S012].",
     "D08", "PR 0.70 contradicts the recorded PR 0.88"),
    ("Screen-detected cases had lower mortality (PR 0.95) [src:S012].",
     "D08", "PR 0.95 contradicts the recorded PR 0.88"),
    ("Statin therapy reduced cardiovascular events (HR 0.60) [src:S001].",
     "D08", "HR 0.60 contradicts the recorded HR 0.80"),
    ("Statin therapy reduced cardiovascular events (HR 0.95) [src:S001].",
     "D08", "HR 0.95 contradicts the recorded HR 0.80"),
    # Retraction outranks a correctly quoted figure: the sentence reports the recorded value
    # exactly, so there is no contradiction to find -- and it is still a conflict, because
    # the source may not be cited at all.
    ("Calcium supplementation reduced cardiovascular events (RR 0.60) [src:S013].",
     "D04", "S013 is retracted; RR 0.60 is the recorded value, so the defect is the retraction alone"),
    ("Antiviral therapy reduced mortality (OR 2.10) [src:S014].",
     "D04", "S014 is retracted; OR 2.10 is the recorded value"),
    # A citation number the document's own apparatus cannot account for is fabricated.
    ("An exploratory subgroup analysis suggested benefit [98].",
     "D03", "citation 98 matches no source"),
    ("A post hoc analysis reported a larger effect [97].",
     "D03", "citation 97 matches no source"),
]

RULE_STATE = {
    "D01": "no_citation_needed",
    "D02": "unattributed",
    "D03": "conflict",
    "D04": "conflict",
    "D05": "unverifiable",
    "D06": "unverifiable",
    "D07": "unverifiable",
    "D08": "conflict",
    "D09": "attributed",
    "D10": "synthesis",
    # D11/D12 are downgrades: the classifier found a contradiction but the evidence or
    # the link was not good enough to assert it, so the sentence lands on unverifiable.
    "D11": "unverifiable",
    "D12": "unverifiable",
}

#: Rules that need a citation, for trigger scoring.
NEEDS_CITATION = {"D02", "D03", "D04", "D05", "D07", "D08", "D09", "D10", "D11", "D12"}

#: A 40-sentence sample drawn at a fixed interval (`[::25]`) from the narrative sentences of a
#: real 34-page PTSD review, so it is not a set written to fit the rules. Each sentence is
#: hand-labelled for one binary decision: does it assert something that needs attribution?
#: YES covers a reported finding, a figure, a method, a definition, or another author's
#: formulation; NO covers the author's own inference, framing, or a general trend statement.
#: Labelled by reading the sentence, with no rule run first. Counted for the trigger metrics
#: only -- the real document turned up no contradictions, so it cannot measure conflict
#: sensitivity, only the specificity of the accusation path.
REAL_SAMPLE = [
    ("john.doe@thesisai.io john.doe@thesisai.io", False),
    ("In survivors of modern slavery and human trafficking, eligibility criteria have required explicit assessment of CPTSD or related constructs using recognised tools such as the International Trauma Questionnaire (ITQ) or the Structured Interview for Disorders of Extreme Stress (SIDES), with narrative synthesis used because of heterogeneous methods and limited study numbers (5).", True),
    ("Such findings give a framework for thinking about how chronic violence, captivity, or exploitation in ancient contexts might have produced persistent symptom profiles that, in contemporary terms, would map onto complex PTSD rather than acute stress reactions (6,8).", False),
    ("Within this context, met ICD-11 criteria for PTSD and for complex PTSD, yielding a combined prevalence of for post-traumatic stress disorders among students.", True),
    ("Together, conditioning-based models, HPA-focused stress theories, executive-function perspectives, and spectrum conceptualisations linking complex PTSD with psychosis chart a marked evolution from descriptive accounts of trauma reactions toward integrative frameworks that connect symptoms with specific learning mechanisms, endocrine pathways, and cognitive control networks (6,11–13).", False),
    ("By documenting how different clinical samples met PTSD or CPTSD criteria under ICD and DSM-based systems, this body of work demonstrates progressive integration of complex trauma categories into diagnostic practice (3,5).", False),
    ("Among combatants, approximately of soldiers returning from the Vietnam War and of those returning from the Iraq War have been described as suffering PTSD symptoms.", True),
    ("More recently, research on Ukrainians during the Russian invasion has documented substantial mental health strain, with earlier work cited in that analysis noting that of displaced adults met elevated PTSD risk shortly after the 2022 escalation, and that six months after invasion, of parents in Ukraine had PTSD and had complex PTSD.", True),
    ("Sex and gender shape vulnerability to PTSD and associated comorbidities in several ways, spanning prevalence, symptom chronicity, and downstream physical health consequences.", False),
    ("Diagnostic assessment in combat-exposed cohorts has relied heavily on structured instruments.", False),
    ("Within this framework, complex trauma is conceptualised as exposure to severe, prolonged, multiple, or repeated interpersonal events that are difficult or impossible to escape, such as neglect, child abuse, and intimate partner violence.", True),
    ("In Iran, earthquake-related PTSD prevalence has reached in some samples, and studies of populations affected by the Bam earthquake reported rates as high as at months post-event, while other investigations in the same context found much lower estimates around .", True),
    ("In that framework, genetic vulnerability is grouped with psychiatric, psychological, and social influences to explain interindividual differences in PTSD risk after comparable traumatic exposures, underlining that inherited factors form part of a broader multifactorial aetiology (9).", False),
    ("Animal models of prolonged stress similarly show newly acquired cognitive flexibility impairments in association with PTSD-like symptoms, indicating that acute stress exposure can worsen or generate executive deficits.", True),
    ("Among Iranian flood survivors, mean PTSD scores were higher in individuals with lower educational levels and in those reporting lower income.", True),
    ("In war-torn migrants, higher levels of perceived social support correlate negatively with PTSD symptoms, and survivors who report greater support from family, friends, and relatives show fewer post-traumatic complaints and better mental health, quality of life, happiness, and coping with stress.", True),
    ("Nightmares occupy a prominent position within intrusion symptoms.", False),
    ("In one synthesis of clinical observations, individuals with post-traumatic stress disorder were described as suffering from two prominent memory-related disturbances: persistent re-experiencing and deliberate avoidance of the stimuli that caused the trauma, despite knowing that the traumatic event will not recur.", True),
    ("Related investigations of central autonomic and cardiovascular control describe reduced resting heart rate variability (HRV) in PTSD and a lack of effective top–down regulatory capacity of the central autonomic network (CAN) over autonomic nervous system (ANS) functioning at rest.", True),
    ("Developmental trauma research in children and adolescents with childhood maltreatment (CM) histories provides detailed evidence on how emotional dysregulation emerges within this framework.", True),
    ("Developmental trauma research in this cohort provides detailed insight into how CM subtypes and timing shape negative self-beliefs.", True),
    ("One approach interprets scores at or above as indicative of likely PTSD in adult samples, including Ukrainian adults.", True),
    ("Complex PTSD requires that all PTSD criteria are first met, and then that each of these three additional domains is present at clinically significant levels.", True),
    ("Overall PTSD symptom change and core sub-symptoms were consistently operationalised using CAPS.", True),
    ("Several instruments explicitly operationalise DSM-based criteria and have been psychometrically evaluated across diverse populations.", True),
    ("In postpartum women, the PCL-5 is described as the standard self-report measure recommended by the US Veterans Affairs system for provisional PTSD diagnosis, with excellent psychometric properties and strong correspondence to clinician-administered interviews.", True),
    ("In clinical and research samples, a substantial proportion of individuals with PTSD meet criteria for additional psychiatric diagnoses, most commonly depression and other anxiety disorders, and these comorbidities contribute to greater overall symptom burden and functional impairment than seen with single disorders alone (31,40).", True),
    ("Across these strands, evidence indicates that robust differential diagnosis requires: explicit assessment of qualifying traumatic events; use of PTSD-specific tools such as PCL-5 or clinician-administered interviews like CAPS or CIDI; and parallel measurement of depressive and anxiety symptoms with validated instruments (PHQ-8, GAD-7, or equivalent).", True),
    ("According to its original formulation, psychopathology is rooted in maladaptively stored traumatic memories, and EMDR procedures aim to facilitate more adaptive information processing of these memories (42).", True),
    ("PET is widely acknowledged as an effective first-line treatment for PTSD across different trauma types, and is grouped with cognitive behavioural therapy more broadly as a gold-standard intervention (42).", True),
    ("Network meta-analytic evidence positions certain antidepressants as central pharmacological options for adults with post-traumatic stress disorder.", True),
    ("High-dose psilocybin produced marked and sustained improvements in anxiety and anhedonia in treatment-resistant depression, attributed to -HT activation and downstream neuroplastic changes.", True),
    ("Soy isoflavones prevent PTSD-like phenotypes by restoring serotonergic function and exploiting anti-inflammatory and neuroprotective actions.", True),
    ("Both disorders are described as altering monoamine neurotransmission affecting dopamine, norepinephrine, and serotonin within hypothalamic pituitary adrenal and mesocorticolimbic circuits.", True),
    ("A large study of postpartum women addressed this gap by examining the factorial structure of a childbirth-adapted PDI and deriving an optimal cutoff for identifying those likely to endorse CB-PTSD.", True),
    ("Further work in China during the COVID-19 pandemic extended these observations by showing that higher resilience related to lower anxiety, depression, and somatisation in the general population, again supporting a generalisable protective role across event types and diagnostic domains.", True),
    ("Untreated or partially treated PTSD is associated with persistent functional impairment and increased risk of physical disease.", True),
    ("Such tiered approaches are directly relevant to relapse prevention because they allow flexible intensification of care when early, lower-intensity interventions are insufficient (19,37).", False),
    ("These observations indicate that stronger fear conditioning and impaired extinction are accompanied by a shift toward potentiation at BLA–CEm synapses, consistent with persistent hyperactivity of amygdala output pathways.", True),
    ("Pharmacological development increasingly targets glutamatergic and multi-receptor mechanisms.", False),
]


# --------------------------------------------------------------------------- #
# The red bar: the cases that decide whether an accusation is allowed
# --------------------------------------------------------------------------- #

#: A ledger with one source whose value was copied verbatim, and one that records only
#: the extractor's own prose. The first may convict a contradiction; the second may not.
RED_BAR_LEDGER = """source_id,title,authors,container,year,volume,issue,pages,doi,pmid,pmcid,publication_type,peer_reviewed,study_design,population,intervention,comparator,n_participants,follow_up,key_outcomes,main_finding,effect_estimate,verification_status,verifier,verified_date,locator,retraction_status,inclusion_status,exclusion_reason,retrieval_status,theme,notes
S001,Statin trial verbatim,Smith J,Demo,2020,1,1,1-9,10.1056/NEJMoa1234567,,,randomised_trial,yes,RCT,adults,statin,placebo,1000,24 months,events,Statin therapy reduced events,HR 0.80,verified,bench,2026-01-01,abstract,clear,included,,returned,treatment,
S004,Statin trial prose only,Doe A,Demo,2021,2,2,2-9,10.1056/NEJMoa7654321,,,randomised_trial,yes,RCT,adults,statin,placebo,not_reported,not_reported,not_reported,Statin therapy reduced events with HR 0.80,not_reported,verified,bench,2026-01-01,abstract,clear,included,,returned,treatment,
"""

#: (sentence, expected rule, why) -- run against RED_BAR_LEDGER.
RED_BAR_VERBATIM_AND_PROSE = [
    ("Statin therapy reduced events (HR 0.50) [src:S001].",
     "D08", "the ledger copied HR 0.80 verbatim, so the contradiction may convict"),
    ("Statin therapy reduced events (HR 0.50) [src:S004].",
     "D12", "the only disagreement is with the extractor's own prose, which may not convict"),
]

#: A BibTeX entry with no DOI can only be linked to a reference entry by its title, and a
#: guessed link may not convict even when the text itself is primary.
RED_BAR_BIB = """@article{key1,
  title = {Statin therapy trial},
  year = {2020},
  file = {verify.txt}
}
"""
RED_BAR_PDF_TEXT = (
    "Statin therapy reduced major adverse cardiovascular events. "
    "HR 0.80 (95% CI 0.70-0.92).\n"
)
RED_BAR_INFERRED = [
    ("Statin therapy reduced events (HR 0.50) [1].",
     "D11", "the citation resolves only through a title match, so the link is inferred"),
]

RED_BAR_DOCUMENT = """# Red-bar cases

Statin therapy reduced events (HR 0.50) [src:S001].

Statin therapy reduced events (HR 0.50) [src:S004].
"""

RED_BAR_INFERRED_DOCUMENT = """# Red-bar, inferred link

Statin therapy reduced events (HR 0.50) [1].

## References

1. Smith J. Statin therapy trial. Demo Journal. 2020;1(1):1-9.
"""


def wilson(k: int, n: int, z: float = 1.96):
    """Wilson score interval, matching the other benchmarks in this directory."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def _run_cli(name: str, *, document_text: str, extra_args: list) -> list:
    """Write a fixture, run the real CLI, and return its verdicts."""
    workspace = Path(tempfile.mkdtemp(prefix="bench-%s-" % name))
    document = workspace / "cases.md"
    out_dir = workspace / "out"
    document.write_text(document_text, encoding="utf-8")
    completed = subprocess.run(
        [
            PY, str(REPORT), "report",
            "--document", str(document),
            "--offline",
            "--format", "json",
            "--out-dir", str(out_dir),
        ]
        + extra_args,
        capture_output=True, text=True,
    )
    verdicts_path = out_dir / "verdicts.json"
    if not verdicts_path.is_file():
        raise SystemExit(
            "the pipeline produced no verdicts.json for %s\nstdout:\n%s\nstderr:\n%s"
            % (name, completed.stdout[-2000:], completed.stderr[-2000:])
        )
    return json.loads(verdicts_path.read_text(encoding="utf-8"))["verdicts"]



# --------------------------------------------------------------------------- #
# Metrics: a confusion matrix and its four rates, each with a Wilson interval
# --------------------------------------------------------------------------- #


def binary_metrics(pairs: list, positive: str = "positive") -> dict:
    """Accuracy, sensitivity, specificity, precision and F1 for one binary decision.

    `pairs` is a list of `(truth_is_positive, predicted_is_positive)`.

    Sensitivity (recall, true-positive rate) answers "of the cases that really are
    positive, how many did we find?" Specificity (true-negative rate) answers "of the
    cases that really are negative, how many did we leave alone?" They trade against
    each other, and which one matters depends on the decision: for an accusation,
    specificity is the safety property, because a false positive accuses someone. The
    two are therefore always reported together, never as a single accuracy figure --
    accuracy alone hides exactly the asymmetry that matters.

    Every interval is a Wilson 95% interval, so a 4/4 result is not read as proof of
    perfection.
    """
    tp = sum(1 for truth, predicted in pairs if truth and predicted)
    fp = sum(1 for truth, predicted in pairs if not truth and predicted)
    fn = sum(1 for truth, predicted in pairs if truth and not predicted)
    tn = sum(1 for truth, predicted in pairs if not truth and not predicted)
    total = tp + fp + fn + tn

    def rate(numerator, denominator):
        if denominator == 0:
            return float("nan")
        return numerator / denominator

    return {
        "decision": positive,
        "n": total,
        "matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "accuracy": rate(tp + tn, total),
        "accuracy_ci": list(wilson(tp + tn, total)) if total else [float("nan")] * 2,
        "sensitivity": rate(tp, tp + fn),
        "sensitivity_ci": list(wilson(tp, tp + fn)) if (tp + fn) else [float("nan")] * 2,
        "specificity": rate(tn, tn + fp),
        "specificity_ci": list(wilson(tn, tn + fp)) if (tn + fp) else [float("nan")] * 2,
        "precision": rate(tp, tp + fp),
        "precision_ci": list(wilson(tp, tp + fp)) if (tp + fp) else [float("nan")] * 2,
        "f1": (
            2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else float("nan")
        ),
    }


def per_class_metrics(rows: list, classes: list) -> dict:
    """One-vs-rest confusion matrix, sensitivity and specificity for each state."""
    result: dict = {}
    for state in classes:
        pairs = [
            (row["expected_state"] == state, row["actual_state"] == state) for row in rows
        ]
        result[state] = binary_metrics(pairs, positive=state)
    return result


def format_metrics(entry: dict, label: str) -> list:
    matrix = entry["matrix"]
    return [
        "  %s  (n=%d)" % (label, entry["n"]),
        "    confusion           predicted+  predicted-",
        "    actual+          %10d  %10d" % (matrix["tp"], matrix["fn"]),
        "    actual-          %10d  %10d" % (matrix["fp"], matrix["tn"]),
        "    accuracy     %6.3f  95%% CI [%.3f, %.3f]"
        % (entry["accuracy"], entry["accuracy_ci"][0], entry["accuracy_ci"][1]),
        "    sensitivity  %6.3f  95%% CI [%.3f, %.3f]   (of the real positives, how many we found)"
        % (entry["sensitivity"], entry["sensitivity_ci"][0], entry["sensitivity_ci"][1]),
        "    specificity  %6.3f  95%% CI [%.3f, %.3f]   (of the real negatives, how many we left alone)"
        % (entry["specificity"], entry["specificity_ci"][0], entry["specificity_ci"][1]),
        "    precision    %6.3f  95%% CI [%.3f, %.3f]"
        % (entry["precision"], entry["precision_ci"][0], entry["precision_ci"][1]),
        "    F1           %6.3f" % entry["f1"],
    ]

# --------------------------------------------------------------------------- #
# Conflict ground truth from REAL open-access articles
# --------------------------------------------------------------------------- #
#: The same decision as the hand-written set above, but with a ground truth that was NOT
#: written by the author of the rule table. Every value below was copied verbatim out of an
#: open-access article fetched through the skill's own acquisition path, and every sentence is
#: a plausible digit transposition of it -- the kind of error a real author makes. `quote` is
#: the article's own wording, so the pairing can be checked rather than trusted.
#:
#: Kept SEPARATE from the constructed set, and reported on its own line, because it is a
#: different population: merging them would let ten real cases inherit the caveat that the
#: constructed ones were written to fit the rules, and hide the fact that these were not.
#:
#: Yield, stated honestly: 19 of the 60 DOIs in a real clinical bibliography were obtained
#: (31.7%, all from the Europe PMC open-access tier; the OpenAlex PDF tier returned 0, with
#: publishers refusing a non-browser client), and only 4 of those 19 contain a measure in a
#: form the parser accepts, which is what these ten cases come from. The binding constraint on
#: a larger harvest is the parser's format expectations -- `RR` is not equated with "relative
#: risk", and comma, parenthetical and negative forms are invisible -- not network access.
REAL_CONFLICTS = [
    ("S101", "10.1016/j.heliyon.2023.e20289", "PMC10522950", "OR", 1.92,
     "tertiary hospital ( OR = 1.92, 95% CI : 1.12-3.31, p = 0.018)",
     "Working at a tertiary hospital was independently associated with PTSD among nurses (OR 1.29)",
     "the article reports OR 1.92; 1.29 transposes 92 -> 29"),
    ("S102", "10.1016/j.heliyon.2023.e20289", "PMC10522950", "OR", 2.36,
     "OR = 2.36 for the >40 years group",
     "Nurses older than 40 years had higher odds of PTSD than those aged 25 years or younger (OR 2.63)",
     "the article reports OR 2.36 for the >40 group; 2.63 transposes 36 -> 63"),
    ("S103", "10.1016/j.heliyon.2023.e20289", "PMC10522950", "OR", 2.35,
     "level of depression (moderate-to-severe, OR = 2.35, 95% CI : 1.18-4.69, p = 0.004)",
     "Moderate-to-severe depression was independently associated with PTSD among nurses (OR 2.53)",
     "the article reports OR 2.35 for moderate-to-severe depression; 2.53 transposes 35 -> 53"),
    ("S104", "10.1016/j.heliyon.2023.e20289", "PMC10522950", "OR", 18.46,
     "anxiety ( OR = 18.46, 95% CI : 5.35-63.71, p < 0.001)",
     "Anxiety showed the strongest association with PTSD among the nurses studied (OR 18.64)",
     "the article reports OR 18.46 for anxiety; 18.64 transposes 46 -> 64"),
    ("S105", "10.1016/j.heliyon.2023.e20289", "PMC10522950", "OR", 4.15,
     "sleep disorders ( OR = 4.15, 95% CI : 1.98-8.68, p < 0.001)",
     "Sleep disorders were independently associated with PTSD among nurses (OR 4.51)",
     "the article reports OR 4.15 for sleep disorders; 4.51 transposes 15 -> 51"),
    ("S106", "10.1016/j.jmh.2024.100225", "PMC11390179", "beta", 0.67,
     "the history of mental disorder was the only variable affecting PTSD ( beta = 0.67",
     "In the first-stage model, a history of mental disorder was the only variable affecting PTSD (beta = 0.76)",
     "the article reports beta 0.67; 0.76 transposes 67 -> 76"),
    ("S107", "10.1016/j.jmh.2024.100225", "PMC11390179", "beta", 0.16,
     "self-control ( beta = 0.16 ; p < 0.05 )",
     "Self-control was a relatively good predictor of PTSD in the second-stage model (beta = 0.61)",
     "the article reports beta 0.16 for self-control; 0.61 transposes 16 -> 61"),
    ("S108", "10.1016/j.jmh.2024.100225", "PMC11390179", "beta", 0.13,
     "perceived controllability ( beta = 0.13 ; p < 0.05 )",
     "Perceived controllability was a relatively good predictor of PTSD in the second-stage model (beta = 0.31)",
     "the article reports beta 0.13; 0.31 transposes 13 -> 31"),
    ("S109", "10.1016/j.bbih.2023.100631", "PMC10209702", "RR", 8.08,
     "a relative risk = 8.08 for diagnosed stroke in the Pathological Class",
     "Responders in the Pathological Class with cerebrovascular disease had a much higher "
     "relative risk of diagnosed stroke than those in the Normal Class (relative risk = 8.80)",
     "the article reports relative risk 8.08; 8.80 transposes 08 -> 80"),
    ("S110", "10.1016/j.xcrm.2023.101045", "PMC10213980", "HR", 1.47,
     "veterans with PTSD were at increased risk for developing heart failure "
     "(hazard ratio = 1.47; 95% confidence interval = 1.13-1.91)",
     "Veterans with PTSD were at increased risk of developing heart failure compared with "
     "veterans without PTSD (hazard ratio = 1.74)",
     "BORDERLINE: the article is summarising another longitudinal study when it reports HR 1.47, "
     "so the value is real but the attribution is to a secondary report; 1.74 transposes 47 -> 74"),
]


def real_conflict_ledger() -> str:
    """Build the ledger for the real-source cases: one row per case, with the verbatim value.

    One row per case rather than one per article, because a real article reports many measures
    and the classifier pairs a sentence with the first same-label value it finds in a source.
    A ledger holding only the value this case is about is the configuration in which that
    pairing is unambiguous; it is also the configuration a reviewer would use to check a single
    claim by hand.
    """
    fields = SOURCES_CSV.splitlines()[0].split(",")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for source_id, doi, pmcid, measure, value, _quote, _sentence, _why in REAL_CONFLICTS:
        writer.writerow({
            "source_id": source_id, "title": "open-access article %s" % pmcid,
            "authors": "as published", "container": "open-access article", "year": "2023",
            "doi": doi, "pmcid": pmcid, "publication_type": "journal_article",
            "peer_reviewed": "yes", "effect_estimate": "%s %s" % (measure, value),
            "verification_status": "verified", "verifier": "bench",
            "verified_date": "2026-01-01", "locator": pmcid,
            "retraction_status": "clear", "inclusion_status": "included",
            "retrieval_status": "returned",
        })
    return buffer.getvalue()


def run_real_conflicts() -> list:
    """Run the real-source conflict cases through the real CLI.

    Returns (sentence, why, provenance, verdict). This set is the answer to "the labelled set
    was written by the same author as the rules": the values here came from the literature.
    """
    workspace = Path(tempfile.mkdtemp(prefix="bench-realconflict-"))
    ledger = workspace / "sources.csv"
    ledger.write_text(real_conflict_ledger(), encoding="utf-8")
    verdicts = _run_cli(
        "real-conflict",
        document_text="\n\n".join(
            "%s [src:%s]." % (sentence.rstrip("."), source_id)
            for source_id, _d, _p, _m, _v, _q, sentence, _w in REAL_CONFLICTS
        ),
        extra_args=["--sources", str(ledger), "--allow-insufficient"],
    )
    return [
        (sentence, why, "%s %s" % (doi, pmcid), verdict)
        for (source_id, doi, pmcid, _m, _v, _q, sentence, why), verdict
        in zip(REAL_CONFLICTS, verdicts)
    ]


#: Ordinary prose that a measure parser can mistake for a statistic. Every one of these was
#: measured producing a measure token before the guard in `_signals.extract_quantities()`, and
#: the first was measured producing a **CONFLICT** against a source recording `OR 1.42` --
#: a false accusation, from the English conjunction "or" and the number 12.
FALSE_PARSE_PROBES = [
    ("Treatment continued for 6 or 12 weeks at the clinician's discretion [src:S006].",
     "'or' is a conjunction, not the odds ratio; this was a CONFLICT before the guard"),
    ("Fatigue was rated as 0 or 1 on the severity scale [src:S006].",
     "a 0-or-1 rating scale is not an odds ratio"),
    ("Variables OR 95% CI were extracted from each study [src:S006].",
     "a table header where the number carries a percent sign is not an odds ratio of 95"),
    ("Samples were sent to Fort Detrick MD 21702 for analysis [src:S006].",
     "a ZIP code after a state abbreviation is not a mean difference"),
]


def run_false_parse_guard() -> list:
    """Assert that ordinary prose is never accused of contradicting a source.

    This is the safety property that matters most, and it is different in kind from the
    precision figures: a false red asserts that the author cited a source contradicting their
    own sentence. Missing a real measure is a recall cost, reported elsewhere; inventing one is
    an accusation. The benchmark fails if any probe here lands on `conflict`.
    """
    workspace = Path(tempfile.mkdtemp(prefix="bench-falseparse-"))
    ledger = workspace / "sources.csv"
    ledger.write_text(SOURCES_CSV, encoding="utf-8")
    verdicts = _run_cli(
        "false-parse",
        document_text="\n\n".join(sentence for sentence, _ in FALSE_PARSE_PROBES),
        extra_args=["--sources", str(ledger), "--allow-insufficient"],
    )
    return [(sentence, why, verdict)
            for (sentence, why), verdict in zip(FALSE_PARSE_PROBES, verdicts)]


def run_red_bar() -> list:
    """Run the three accusation cases, each in its own source configuration."""
    workspace = Path(tempfile.mkdtemp(prefix="bench-redbar-"))
    ledger = workspace / "sources.csv"
    ledger.write_text(RED_BAR_LEDGER, encoding="utf-8")
    rows: list = []
    for (sentence, expected, why), verdict in zip(
        RED_BAR_VERBATIM_AND_PROSE,
        _run_cli(
            "verbatim",
            document_text=RED_BAR_DOCUMENT,
            extra_args=["--sources", str(ledger), "--allow-insufficient"],
        ),
    ):
        rows.append((sentence, expected, why, verdict))

    bib = workspace / "refs.bib"
    bib.write_text(RED_BAR_BIB, encoding="utf-8")
    pdf_dir = workspace / "pdf"
    pdf_dir.mkdir()
    (pdf_dir / "verify.txt").write_text(RED_BAR_PDF_TEXT, encoding="utf-8")
    for (sentence, expected, why), verdict in zip(
        RED_BAR_INFERRED,
        _run_cli(
            "inferred",
            document_text=RED_BAR_INFERRED_DOCUMENT,
            extra_args=["--bib", str(bib), "--pdf-dir", str(pdf_dir), "--allow-insufficient"],
        ),
    ):
        rows.append((sentence, expected, why, verdict))
    return rows



def run_real_sample() -> list:
    """Run the trigger decision over the real-document sample and pair it with the labels.

    Only the trigger is scored here. The real document produced no contradictions, so it
    cannot measure conflict *sensitivity* -- it measures the specificity of the
    accusation path, which is the half that decides whether the tool accuses people
    wrongly, and it does so on prose the rules were not written against.
    """
    workspace = Path(tempfile.mkdtemp(prefix="bench-real-"))
    document = workspace / "sample.md"
    out_dir = workspace / "out"
    document.write_text(
        "# Real-document sample\n\n## Body\n\n"
        + "\n\n".join(text for text, _ in REAL_SAMPLE)
        + "\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            PY, str(REPORT), "report",
            "--document", str(document),
            "--offline", "--allow-insufficient",
            "--format", "json",
            "--out-dir", str(out_dir),
        ],
        capture_output=True, text=True,
    )
    verdicts_path = out_dir / "verdicts.json"
    if not verdicts_path.is_file():
        raise SystemExit(
            "the real-sample run produced no verdicts.json\nstdout:\n%s\nstderr:\n%s"
            % (completed.stdout[-2000:], completed.stderr[-2000:])
        )
    return json.loads(verdicts_path.read_text(encoding="utf-8"))["verdicts"]

def run_pipeline() -> tuple:
    """Exercise the real CLI and return (per-sentence verdicts, coverage summary)."""
    workspace = Path(tempfile.mkdtemp(prefix="bench-verdicts-"))
    document = workspace / "cases.md"
    ledger = workspace / "sources.csv"
    out_dir = workspace / "out"
    document.write_text(
        "# Hand-labelled cases\n\n## Results\n\n"
        + "\n\n".join(sentence for sentence, _, _ in CASES)
        + "\n",
        encoding="utf-8",
    )
    ledger.write_text(SOURCES_CSV, encoding="utf-8")
    completed = subprocess.run(
        [
            PY, str(REPORT), "report",
            "--document", str(document),
            "--sources", str(ledger),
            "--offline",
            "--format", "json",
            "--out-dir", str(out_dir),
            # The classified set is the question here; the sufficiency policy is tested
            # separately by the harness and by the red-bar section below.
            "--allow-insufficient",
        ],
        capture_output=True, text=True,
    )
    verdicts_path = out_dir / "verdicts.json"
    if not verdicts_path.is_file():
        raise SystemExit(
            "the pipeline produced no verdicts.json\n"
            "stdout:\n%s\nstderr:\n%s" % (completed.stdout[-2000:], completed.stderr[-2000:])
        )
    payload = json.loads(verdicts_path.read_text(encoding="utf-8"))
    return payload["verdicts"], payload["coverage"], completed.returncode


def main() -> int:
    as_json = "--json" in sys.argv
    verdicts, summary, exit_code = run_pipeline()

    if len(verdicts) != len(CASES):
        raise SystemExit(
            "expected %d verdicts, got %d: the document and the label list disagree"
            % (len(CASES), len(verdicts))
        )

    rows: list = []
    for (sentence, expected_rule, why), verdict in zip(CASES, verdicts):
        rows.append(
            {
                "sentence": sentence,
                "expected_rule": expected_rule,
                "expected_state": RULE_STATE[expected_rule],
                "actual_rule": verdict["rule_id"],
                "actual_state": verdict["state"],
                "why": why,
                "rule_ok": verdict["rule_id"] == expected_rule,
                "state_ok": verdict["state"] == RULE_STATE[expected_rule],
                "group": "classification",
            }
        )

    # The red-bar cases join the same scoring, because an accusation the evidence does
    # not support is a wrong verdict like any other -- it just costs more.
    red_bar_rows: list = []
    for sentence, expected_rule, why, verdict in run_red_bar():
        row = {
            "sentence": sentence,
            "expected_rule": expected_rule,
            "expected_state": RULE_STATE[expected_rule],
            "actual_rule": verdict["rule_id"],
            "actual_state": verdict["state"],
            "why": why,
            "rule_ok": verdict["rule_id"] == expected_rule,
            "state_ok": verdict["state"] == RULE_STATE[expected_rule],
            "group": "red bar",
            "evidence_strength": verdict.get("evidence_strength"),
            "link_confidence": verdict.get("link_confidence"),
        }
        red_bar_rows.append(row)
        rows.append(row)

    rule_correct = sum(row["rule_ok"] for row in rows)
    state_correct = sum(row["state_ok"] for row in rows)

    # Per-state precision and recall.
    states = sorted({row["expected_state"] for row in rows})
    per_state: dict = {}
    for state in states:
        tp = sum(1 for row in rows if row["expected_state"] == state and row["actual_state"] == state)
        fp = sum(1 for row in rows if row["expected_state"] != state and row["actual_state"] == state)
        fn = sum(1 for row in rows if row["expected_state"] == state and row["actual_state"] != state)
        precision = tp / (tp + fp) if (tp + fp) else float("nan")
        recall = tp / (tp + fn) if (tp + fn) else float("nan")
        p_lo, p_hi = wilson(tp, tp + fp) if (tp + fp) else (float("nan"), float("nan"))
        r_lo, r_hi = wilson(tp, tp + fn) if (tp + fn) else (float("nan"), float("nan"))
        per_state[state] = {
            "support": tp + fn,
            "tp": tp, "fp": fp, "fn": fn,
            "precision": precision, "precision_ci": [p_lo, p_hi],
            "recall": recall, "recall_ci": [r_lo, r_hi],
        }

    # Trigger agreement: does the sentence get judged as needing a citation?
    trigger_tp = sum(
        1 for row in rows
        if row["expected_rule"] in NEEDS_CITATION and row["actual_rule"] in NEEDS_CITATION
    )
    trigger_fp = sum(
        1 for row in rows
        if row["expected_rule"] not in NEEDS_CITATION and row["actual_rule"] in NEEDS_CITATION
    )
    trigger_fn = sum(
        1 for row in rows
        if row["expected_rule"] in NEEDS_CITATION and row["actual_rule"] not in NEEDS_CITATION
    )
    trigger_tn = sum(
        1 for row in rows
        if row["expected_rule"] not in NEEDS_CITATION and row["actual_rule"] not in NEEDS_CITATION
    )
    trigger_precision = trigger_tp / (trigger_tp + trigger_fp) if (trigger_tp + trigger_fp) else float("nan")
    trigger_recall = trigger_tp / (trigger_tp + trigger_fn) if (trigger_tp + trigger_fn) else float("nan")
    tp_lo, tp_hi = wilson(trigger_tp, trigger_tp + trigger_fp) if (trigger_tp + trigger_fp) else (float("nan"),) * 2
    tr_lo, tr_hi = wilson(trigger_tp, trigger_tp + trigger_fn) if (trigger_tp + trigger_fn) else (float("nan"),) * 2

    conflict = per_state.get("conflict", {})
    conflict_precision = conflict.get("precision", float("nan"))

    # -- metrics, computed before the result dict so they can be reported in it ------ #
    classes = sorted({row["expected_state"] for row in rows})
    per_class = per_class_metrics(rows, classes)
    # The safety-critical binary decision: does the tool accuse this sentence?
    accusation = binary_metrics(
        [
            (row["expected_state"] == "conflict", row["actual_state"] == "conflict")
            for row in rows
        ],
        positive="sentence is contradicted / cites a retracted source / cites nothing",
    )
    constructed_trigger = binary_metrics(
        [
            (row["expected_rule"] in NEEDS_CITATION, row["actual_rule"] in NEEDS_CITATION)
            for row in rows
        ],
        positive="sentence needs attribution (constructed set)",
    )
    real_verdicts = run_real_sample()
    if len(real_verdicts) != len(REAL_SAMPLE):
        raise SystemExit(
            "expected %d real-sample verdicts, got %d" % (len(REAL_SAMPLE), len(real_verdicts))
        )
    real_trigger = binary_metrics(
        [
            (needs, bool(verdict.get("requires_citation")))
            for (_, needs), verdict in zip(REAL_SAMPLE, real_verdicts)
        ],
        positive="sentence needs attribution (real prose)",
    )
    real_accusation = binary_metrics(
        [(False, verdict["state"] == "conflict") for verdict in real_verdicts],
        positive="sentence is contradicted (real prose)",
    )

    # Structural red bar: no conflict in any group may rest on an inferred link or on
    # evidence weaker than primary text or a recorded value. Precision alone would not
    # catch a conflict that fired for the right answer through the wrong door.
    weak_conflicts = [
        row
        for row in rows
        if row["actual_state"] == "conflict"
        and (
            row.get("link_confidence") not in (None, "exact")
            or row.get("evidence_strength") not in (None, "primary", "recorded_estimate")
        )
    ]
    # A false orange accuses an author of failing to cite something they did cite, so
    # the false-positive rate of the trigger is a safety property too, and it is measured
    # on prose the rules were not written against.
    trigger_safety_ok = real_trigger["specificity"] == 1.0
    # ...and the parser may not INVENT a measure: a false red says the author contradicted a
    # source, so ordinary prose must never be accused through a token like the word "or".
    false_parse = run_false_parse_guard()
    accused = [(sentence, verdict["rule_id"])
               for sentence, _, verdict in false_parse if verdict["state"] == "conflict"]
    false_parse_ok = not accused
    # The externally grounded set: real articles, values copied from the fetched text. It is
    # scored on its own so its result cannot be attributed to the constructed set's caveat.
    real_conflicts = run_real_conflicts()
    real_conflict_rows = [
        (sentence, RULE_STATE["D08"], why, provenance, verdict)
        for sentence, why, provenance, verdict in real_conflicts
    ]
    real_missed = [(sentence, verdict["rule_id"], provenance)
                   for sentence, _expected, _why, provenance, verdict in real_conflict_rows
                   if verdict["state"] != "conflict"]
    real_conflict_precision = (
        (len(real_conflict_rows) - len(real_missed)) / len(real_conflict_rows)
        if real_conflict_rows else float("nan")
    )
    real_conflict_ok = bool(real_conflict_rows) and not real_missed
    safety_ok = (
        conflict["support"] > 0
        and conflict_precision == 1.0
        and not weak_conflicts
        and trigger_safety_ok
        and false_parse_ok
        and real_conflict_ok
    )

    result = {
        "cases": len(rows),
        "rule_accuracy": rule_correct / len(rows),
        "state_accuracy": state_correct / len(rows),
        "rule_accuracy_ci": list(wilson(rule_correct, len(rows))),
        "state_accuracy_ci": list(wilson(state_correct, len(rows))),
        "trigger": {
            "tp": trigger_tp, "fp": trigger_fp, "fn": trigger_fn, "tn": trigger_tn,
            "precision": trigger_precision, "precision_ci": [tp_lo, tp_hi],
            "recall": trigger_recall, "recall_ci": [tr_lo, tr_hi],
        },
        "per_state": per_state,
        "conflict_precision_must_be_one": safety_ok,
        "trigger_false_positive_free_on_real_prose": trigger_safety_ok,
        "false_parse_never_accuses": false_parse_ok,
        "real_source_conflict_recall": real_conflict_ok,
        "real_source_conflicts": {
            "cases": len(real_conflict_rows),
            "recall": (1.0 - len(real_missed) / len(real_conflict_rows))
            if real_conflict_rows else float("nan"),
            "caught": ["%s (%s)" % (sentence[:60], provenance)
                       for sentence, _e, _w, provenance, v in real_conflict_rows
                       if v["state"] == "conflict"],
            "missed": ["%s -> %s (%s)" % (sentence[:60], rule, provenance)
                       for sentence, rule, provenance in real_missed],
        },
        "false_parse_probes": [
            {"sentence": sentence, "why": why, "rule": verdict["rule_id"],
             "state": verdict["state"]}
            for sentence, why, verdict in false_parse
        ],
        "metrics": {
            "per_state": per_class,
            "accusation": accusation,
            "trigger_constructed": constructed_trigger,
            "trigger_real_prose": real_trigger,
            "accusation_specificity_real_prose": real_accusation,
        },
        "red_bar_cases": red_bar_rows,
        "conflicts_violating_the_red_bar": weak_conflicts,
        "pipeline_exit_code": exit_code,
        "coverage": summary.get("citation_coverage"),
        "labelled_cases": rows,
        "advisory_channel": (
            "not measured for accuracy: no calibrated grader ships, and the repository's "
            "own measurement of a comparable classifier found chance-level accuracy on a "
            "wide choice and a failure on a causality trap. Advisory inertness is asserted "
            "by scripts/selftest.sh instead."
        ),
    }

    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if safety_ok else 1

    print("=" * 74)
    print("citation-report deterministic channel -- hand-labelled benchmark")
    print("=" * 74)
    print()
    print("Every case, with its label and the label's justification:")
    print()
    print("  #   expected  actual    ok  sentence / why")
    for index, row in enumerate(rows, start=1):
        mark = "OK " if row["rule_ok"] else ">>>"
        print("  %-3d %-9s %-9s %s  %s" % (index, row["expected_rule"], row["actual_rule"], mark, row["sentence"][:64]))
        print("  %-3s %-9s %-9s     %s" % ("", "", "", row["why"]))
        if not row["rule_ok"]:
            print("  %-3s %-9s %-9s     !! expected state %s, got %s"
                  % ("", "", "", row["expected_state"], row["actual_state"]))

    print()
    print("Agreement")
    print("  rule-level  %2d/%2d = %.1f%%  95%% CI [%.1f%%, %.1f%%]"
          % (rule_correct, len(rows), 100 * rule_correct / len(rows),
             100 * result["rule_accuracy_ci"][0], 100 * result["rule_accuracy_ci"][1]))
    print("  state-level %2d/%2d = %.1f%%  95%% CI [%.1f%%, %.1f%%]"
          % (state_correct, len(rows), 100 * state_correct / len(rows),
             100 * result["state_accuracy_ci"][0], 100 * result["state_accuracy_ci"][1]))

    print()
    print("=" * 74)
    print("METRICS: confusion matrices, sensitivity, specificity (Wilson 95% CI)")
    print("=" * 74)

    print()
    print("A. Per state, one against the rest -- %d labelled cases" % len(rows))
    for state in classes:
        for line in format_metrics(per_class[state], "state = %s" % state):
            print(line)
        print()

    print("B. The accusation decision (the safety property)")
    for line in format_metrics(accusation, "accusation"):
        print(line)
    print("      sensitivity counts the sentences that SHOULD be accused; specificity counts")
    print("      the ones that must be left alone. For an accusation, specificity is safety.")
    print()

    print("C. The trigger decision -- does the sentence need attribution?")
    for line in format_metrics(constructed_trigger, "constructed set"):
        print(line)
    print()
    for line in format_metrics(real_trigger, "real prose (40 unseen sentences)"):
        print(line)
    print()

    print("D. Specificity of the accusation path on real prose")
    for line in format_metrics(real_accusation, "real prose"):
        print(line)
    print()

    print("Trigger: does the sentence need attribution?")
    print("  tp=%d fp=%d fn=%d tn=%d" % (trigger_tp, trigger_fp, trigger_fn, trigger_tn))
    print("  precision %.3f  95%% CI [%.3f, %.3f]   (false orange findings must stay rare)"
          % (trigger_precision, tp_lo, tp_hi))
    print("  recall    %.3f  95%% CI [%.3f, %.3f]   (a missed gap costs less than a false one)"
          % (trigger_recall, tr_lo, tr_hi))

    print()
    print("Per state")
    print("  %-19s %7s %5s %5s %5s %10s %10s" % ("state", "support", "tp", "fp", "fn", "precision", "recall"))
    for state in states:
        entry = per_state[state]
        print("  %-19s %7d %5d %5d %5d %10.3f %10.3f"
              % (state, entry["support"], entry["tp"], entry["fp"], entry["fn"],
                 entry["precision"], entry["recall"]))

    print()
    print("Coverage arithmetic from the same run: %d/%d = %.1f%%"
          % (summary["citation_coverage"]["numerator"], summary["citation_coverage"]["denominator"],
             summary["citation_coverage"]["percent"]))
    print("Pipeline exit code: %d (the two deliberate errors in the set fail the gate)"
          % exit_code)

    print()
    print("CONFLICT GROUND TRUTH FROM REAL ARTICLES (values copied from the fetched text):")
    for sentence, _expected, _why, provenance, verdict in real_conflict_rows:
        mark = "caught" if verdict["state"] == "conflict" else "MISSED"
        print("  %-7s %-5s %s" % (mark, verdict["rule_id"], sentence[:62]))
        print("  %-7s %-5s %s" % ("", "", provenance))
    print("  caught %d of %d real-source contradictions (precision %.3f; a miss is a false "
          "negative, not an accusation)"
          % (len(real_conflict_rows) - len(real_missed), len(real_conflict_rows),
             real_conflict_precision))
    print()
    print("FALSE-PARSE GUARD -- ordinary prose that must never be accused:")
    for sentence, why, verdict in false_parse:
        mark = "ACCUSED!" if verdict["state"] == "conflict" else "not accused"
        print("  %-11s %-13s %s" % (mark, verdict["rule_id"], sentence[:58]))
        print("  %-11s %-13s %s" % ("", "", why))
    print("  %d of %d probes were treated as a contradiction; the parser may miss a real"
          % (len(accused), len(false_parse)))
    print("  measure, but it may not invent one.")
    print()
    if safety_ok:
        print("SAFETY PROPERTIES HOLD:")
        print("  conflict precision is 1.000 over %d conflict case(s) -- no false accusation"
              % conflict["support"])
        print("  trigger specificity is %.3f over %d unseen real sentences -- no sentence was"
              % (real_trigger["specificity"], real_trigger["n"]))
        print("    told it needs a citation when it did not")
        print("  %d of %d ordinary-prose probes were accused -- the parser never invented a "
              "measure" % (len(accused), len(false_parse)))
        print("  %d of %d real-source contradictions caught -- no contradiction in the "
              "externally grounded set was missed"
              % (len(real_conflict_rows) - len(real_missed), len(real_conflict_rows)))
    else:
        print("SAFETY PROPERTY VIOLATED: conflict precision is %.3f over %d case(s)."
              % (conflict_precision, conflict.get("support", 0)))
        for sentence, rule in accused:
            print("  ACCUSED %s: %s" % (rule, sentence[:70]))
        for sentence, rule, provenance in real_missed:
            print("  MISSED  %s: %s (%s)" % (rule, sentence[:60], provenance))
        print("A false red is an accusation of fabrication. Narrow the rule that caused it.")
    print()
    print(result["advisory_channel"])
    print()
    print("WHAT THIS DOES AND DOES NOT SHOW")
    print("  The labelled set was written by the same author as the rule table, from the")
    print("  same reading of the requirements. A perfect score therefore shows the rules do")
    print("  what they were designed to do; it does NOT show they generalise to prose the")
    print("  author did not choose. Read the intervals above as a check on the")
    print("  implementation, not as an estimate of field accuracy.")
    print("  The honest complement is the unlabelled distribution over a real document with")
    print("  1,027 graded sentences, which is exactly where the evidence-availability limit")
    print("  shows: most cited sentences come out `unverifiable` when source PDFs are absent.")
    return 0 if safety_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
