# ICMR Beginner's Guide for Systematic Reviews — India-relevant conduct guidance

*Beginner's Guide for Systematic Reviews: A step by step guide to conduct systematic reviews
and Meta-Analysis* — **An ICMR Publication** (Indian Council of Medical Research). Authors:
Anju Sinha, Geetha R. Menon, Denny John. Foreword by Dr Balram Bhargava (then Director
General, ICMR). 106 pp. Verified against the source PDF.

This is a **national (Government of India) guidance document**, written for public-health and
social-science researchers in India and low- and middle-income settings. Use it *alongside*
the Cochrane Handbook: Cochrane gives the methodological standard, the ICMR guide gives the
practical, resource-constrained, India-facing route to it. Where they differ, **Cochrane
governs the method** and the ICMR guide governs local feasibility and framing.

## Contents (verified)

| Ch. | Title | Covers |
|---|---|---|
| 1 | Introduction | why systematic reviews; evidence hierarchy; role in policy |
| 2 | Getting Started | framing the question, protocol, team, timeline |
| 3 | Steps in a systematic review | the end-to-end workflow, including a **data extraction form** template |
| 4 | Meta-Analysis | quantitative pooling for the beginner |
| 5 | Systematic review and Meta-Analysis software | software landscape (RevMan, CMA, R) |
| 6 | Disseminating Systematic Review Findings | reporting and communication to policy |

## Why it matters for our reviews

- **Indian policy framing.** It is written for evidence-to-policy translation in India — useful
  when a review's audience is ICMR, HTAIn, or a state health department (as in the
  agentic-AI-in-PHC-India work).
- **Data-extraction form.** Chapter 3 ships a structured extraction form (general information;
  eligibility; population and setting; methods; risk-of-bias assessment; results; other) that
  maps cleanly onto our `templates/` coding sheets — a good default when none is pre-specified.
- **LMIC feasibility.** It is explicit about practical constraints (access, cost, capacity),
  which the Cochrane Handbook assumes away.

## How to use it in the pipeline

- **Stage 1 (question and protocol)**: use Ch. 2 for framing when the audience is Indian policy.
- **Stage 7 (extraction)**: use the Ch. 3 extraction form as a starting coding sheet if the
  team has none, then add the fields `meta-analysis-forge` requires (effect metric, estimate, SE).
- **Stage 10 (reporting and dissemination)**: Ch. 6 for the policy-facing summary and briefing.

## Limitations to state honestly

- It is a **beginner's** guide: it is not a methods authority for contested decisions (model
  choice, τ² estimation, NMA). For those, cite **Cochrane** and **GRADE**.
- It predates several current instruments (e.g. the 2019 RoB 2 and later GRADE Book updates);
  check instrument versions against `rob-tool-selection.md` and `grade-certainty.md`.
- It is guidance, not a reporting checklist — reporting still follows **PRISMA 2020**.
