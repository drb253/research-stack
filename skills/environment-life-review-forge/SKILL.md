---
name: environment-life-review-forge
description: Produces domain-adapted review protocols, extraction plans, and audit checklists for environmental, ecological, and life-science evidence questions. Use when a question needs a PECO or PICO framework, an exposure-outcome or dose-response review, an ecosystem-service or biodiversity-stability synthesis, a PLS/VIP indicator audit, an air-quality and crop-yield co-benefit audit, a geospatial or causal machine-learning appraisal, or an irrigation, land-use, and policy trade-off audit. It does not run a search, appraise a study, or pool an effect; it specifies how to do those steps.
---

# Environment Life Review Forge

Use this skill for environmental, ecological, biomedical, and life-science systematic reviews.

This skill adapts a review workflow to the domain. Exposure windows, species, tissues, endpoints, geography, and measurement platforms must be comparable. The output is a protocol, an extraction plan, an audit checklist, or a synthesis plan.

## Terms

Read this list first. Each abbreviation below carries one meaning in this skill.

The normalized difference vegetation index (NDVI) is an optical vegetation indicator. Partial least squares (PLS) is a regression method for correlated predictors. Variable importance in projection (VIP) ranks the predictors of a PLS model.

Geographically weighted regression (GWR) fits a local model at each site. Machine learning (ML) covers the model families below. Sun-induced chlorophyll fluorescence (SIF) is a crop productivity proxy. Soil organic carbon (SOC) is the carbon stock in soil.

An ecosystem-service relationship (ESR) links two ecosystem services. A generalized additive model (GAM) fits a smooth nonlinear response. Double machine learning (DML) estimates a causal parameter from high-dimensional data. A conditional average treatment effect (CATE) is a subgroup effect.

SHapley Additive exPlanations (SHAP) attribute a prediction to its features. A partial dependence plot (PDP) shows a marginal model response. Individual conditional expectation (ICE) shows one observation at a time. Accumulated local effects (ALE) is a local alternative to PDP.

A gradient-boosted decision tree (GBDT) is an ensemble model. Aerosol optical depth (AOD) measures atmospheric aerosol loading. Land surface temperature (LST) is a satellite surface temperature. The surface urban heat island (SUHI) is the urban-to-rural LST difference.

A greenhouse gas (GHG) traps heat in the atmosphere. The root-mean-square error (RMSE) measures a mean model error. The root-mean-square error of prediction (RMSEP) measures a prediction error. A structural equation model (SEM) tests a path model.

A partial least squares path model (PLS-PM) joins a PLS model to a path model. An antibiotic resistance gene (ARG) carries resistance between organisms. A Population, Exposure, Comparator, Outcome (PECO) statement frames an environmental review. A Population, Intervention, Comparator, Outcome (PICO) statement frames a clinical review.

## Preflight and dependencies

Check these items before you start the review.

- Python 3 for `scripts/check_protocol.py`.
- The `references/` and `templates/` files of this skill.
- A review question, a protocol draft, or a framework table.
- The intended product: a narrative, an evidence map, or a meta-analysis.
- The unit of every outcome that the review will compare.

Run the protocol gate on the draft:

```bash
python3 scripts/check_protocol.py --input protocol.json
python3 scripts/check_protocol.py --input protocol.md --json gate-report.json
bash scripts/selftest.sh
```

### Gate script and exit codes

`scripts/check_protocol.py` reads a protocol and decides eight gates. It accepts a JSON object or a Markdown file of `Key: value` lines.

<!-- ste-allow R1, R3: a gate table is data, not prose -->

| Gate | Name | It passes when |
|---|---|---|
| G1 | framework | the protocol names PECO or PICO |
| G2 | exposure | the protocol names the exposure or the intervention |
| G3 | outcome | the protocol gives an outcome unit |
| G4 | design | the protocol names the eligible designs |
| G5 | heterogeneity | the protocol names a heterogeneity source |
| G6 | appraisal | the protocol names a risk-of-bias tool |
| G7 | synthesis | the mode is narrative, evidence map, or meta-analysis |
| G8 | pooling | a meta-analysis plan carries a comparability rationale |

Read the exit code before you read any text.

<!-- ste-allow R1, R3: an exit-code table is data, not prose -->

| Code | Status | Meaning |
|---|---|---|
| 0 | pass | every gate passes |
| 1 | finding | a gate fails |
| 4 | input gap | the input is unreadable |

A gate that cannot fail is not a gate. The suite `scripts/selftest.sh` runs one pass fixture and one fail fixture for each gate. `scripts/check_gate_coverage.py` proves that coverage.

## Core Principle

Domain structure matters. One effect-size workflow can mislead the reader. Exposure windows, species, tissues, endpoints, geography, and platforms may not be comparable. Record each of these dimensions before you pool anything.

A biological or environmental rationale must justify every comparison. State the rationale in the protocol, not in a footnote.

## Intake

Ask for the items below. Mark an unknown item as `missing`, and never guess it.

- domain: environment, ecology, toxicology, epidemiology, life science, molecular biology, or public health.
- population or organism.
- exposure or intervention, with a dose or an intensity where possible.
- comparator.
- outcome families and their units.

- study design.
- spatial scale and temporal scale.
- measurement method and platform.

Record the domain-specific items below when the review needs them.

- ecosystem-service set, pairwise relationship, synergy or trade-off code, and threshold target, for an ecosystem-service review.
- pollutant exposure, crop outcome, food-security endpoint, counterfactual air-quality target, and crop-calorie translation, for an air-quality review.
- biodiversity dimension, stability metric, climate-stress gradient, and moderation target, for a biodiversity-stability review.
- spatial unit and aggregation boundary, for a geospatial prediction.
- minimum mapping unit and detection threshold, for a small-patch system.

- target map variable, resolution, observation inventory, predictor stack, spatial autocorrelation plan, and uncertainty layer, for a map product.
- bidirectional pathways, when impacts and feedbacks are both in scope.
- expected heterogeneity.

Load the reference that matches the domain. Read the reference before you write the extraction plan.

<!-- ste-allow R1, R3: a routing table is data, not prose -->

| Reference | Use it for |
|---|---|
| `references/environmental-life-science.md` | domain heterogeneity |
| `references/cee-alignment.md` | environmental evidence standards |
| `references/pls-vip-environmental-indicators.md` | NDVI, vegetation, soil, climate, and ecological indicator audits; PLS regression; VIP interpretation |
| `references/ecosystem-service-threshold-ml.md` | ecosystem-service relationship mapping; GWR plus ML; nonlinear driver interpretation; thresholds |
| `references/air-quality-food-security.md` | ozone, aerosol, SIF, crop yield, crop calories, and counterfactual air-quality targets |
| `references/soil-biodiversity-aridity-stability.md` | soil biodiversity, aridity gradients, stability, and climate-stress moderation |
| `references/ant-soil-carbon-meta.md` | soil-fauna meta-analysis; SOC stock and CO2 flux; trait moderators |
| `references/small-wetland-methane-scaling.md` | wetland methane; small water bodies; fine-resolution remote sensing; upscaling |
| `references/cryosphere-ground-ice-mapping.md` | permafrost; near-surface ground ice; borehole observations; ensemble ML; map audits |
| `references/agroecosystem-nutrient-meta-analysis.md` | crop yield, soil organic carbon, fertilizer, amendment, and nutrient-management meta-analyses |
| `references/agricultural-ml-yield-prediction.md` | crop-yield prediction from weather, breeding, genomic, remote-sensing, or trial data |
| `references/agricultural-irrigation-optimization.md` | brackish-water irrigation; water-salt-yield-emission trade-offs; GAM; optimization; decision ranges |
| `references/environmental-causal-ml.md` | DML, CATE, AutoML, SHAP-style interpretation, pollutant exposure, and One Health outcomes |
| `references/food-system-bidirectional-nexus.md` | food-system pressure and feedback pathways, trade, diets, crops, livestock, and aquatic foods |
| `references/food-waste-geospatial-ml.md` | county, city, supply-chain, or market food-waste forecasting with geospatial ML |
| `references/environmental-scenario-synthesis.md` | a literature database, a spatial model, or a policy scenario simulation |
| `references/land-use-optimization-tradeoffs.md` | multiobjective optimization, Pareto frontiers, land-use allocation, and food-water-carbon trade-offs |
| `references/system-hub-policy-synthesis.md` | one focal variable linking several environmental, production, health, or policy outcomes |

## Workflow

Follow the steps in order. Each step produces one section of the protocol.

1. Build the framework statement.
2. Define the exposure or the intervention precisely.
3. Define the outcome families and their units.
4. Specify the eligible designs.
5. Identify the heterogeneity sources.
6. Plan the risk-of-bias or quality appraisal.

7. Plan the grey-literature and supplementary search, if relevant.
8. Decide the product: narrative, evidence map, or meta-analysis.
9. Build the domain extraction table.

Use the template that matches the review. Read it before you fill it in.

<!-- ste-allow R1, R3: a routing table is data, not prose -->

| Template | Use it for |
|---|---|
| `templates/peco-framework.md` | the framework statement |
| `templates/pls-vip-environmental-audit.md` | PLS and VIP environmental indicator studies |
| `templates/ecosystem-service-threshold-audit.md`, `templates/ecosystem-service-threshold-schema.csv` | ecosystem-service threshold-management studies |
| `templates/air-quality-food-security-audit.md`, `templates/air-quality-food-security-schema.csv` | air-pollution, crop-yield, SIF, and food-security co-benefit studies |
| `templates/biodiversity-stability-climate-stress-audit.md`, `templates/biodiversity-stability-climate-stress-schema.csv` | soil biodiversity, aridity, stability, and climate-stress moderation |
| `templates/soil-fauna-carbon-meta-audit.md`, `templates/soil-fauna-carbon-schema.csv`, `templates/soil-fauna-carbon-method-stack-schema.csv` | ant, termite, earthworm, or other soil-fauna meta-analyses |
| `templates/wetland-methane-scale-audit.md`, `templates/wetland-methane-geospatial-schema.csv` | small-wetland methane and scale-sensitive upscaling |
| `templates/cryosphere-ground-ice-map-audit.md`, `templates/cryosphere-map-validation-schema.csv` | permafrost, near-surface ground ice, and cryosphere map products |
| `templates/food-environment-bidirectional-audit.md`, `templates/food-environment-pressure-schema.csv` | food-system nexus reviews |
| `templates/food-waste-forecast-audit.md`, `templates/food-waste-geospatial-feature-schema.csv` | geospatial food-waste forecasting |
| `templates/dual-outcome-meta-audit.md`, `templates/nutrient-meta-extraction-schema.csv` | agroecosystem nutrient meta-analysis |
| `templates/nutrient-meta-reproducibility-ledger.csv` | a nutrient meta-analysis with Zenodo, OSF, or GitHub data and code |
| `templates/nutrient-meta-dataset-schema.csv`, `templates/nutrient-meta-r-workflow-blueprint.csv` | data tables and R scripts for nutrient meta-analysis |
| `templates/ml-yield-prediction-audit.md`, `templates/ml-yield-feature-schema.csv` | agricultural ML yield prediction |
| `templates/environmental-causal-ml-audit.md`, `templates/environmental-causal-ml-feature-schema.csv` | environmental causal ML studies |
| `templates/irrigation-optimization-audit.md`, `templates/irrigation-optimization-schema.csv` | brackish-water irrigation and water-salt-yield-emission optimization |
| `templates/scenario-model-audit.md`, `templates/policy-scenario-matrix.csv` | scenario-model evidence synthesis |
| `templates/pareto-frontier-audit.md`, `templates/multi-objective-tradeoff-schema.csv` | multiobjective optimization and land-use trade-offs |
| `templates/system-hub-variable-audit.md`, `templates/system-hub-variable-schema.csv` | a system hub variable, safe boundary, hotspot layer, or policy portfolio |

## Output Modes

Select one mode. Add a mode when the review question spans more than one domain.

### PECO Protocol Memo

Return this memo for a protocol review.

```text
Population:
Exposure:
Comparator:
Outcome families:
Eligible designs:
Heterogeneity:
Risk of bias:
Synthesis plan:
```

### Domain Extraction Plan

Record these fields for every included study.

- species or population.
- site or geography.
- exposure dose or intensity.
- duration or window.
- endpoint and unit.

- assay or measurement method.
- confounders.
- study quality.

### PLS/VIP Environmental Indicator Audit

Use this mode when a study links an ecological indicator to correlated predictors. The study usually applies PLS regression and then ranks predictors with VIP. The indicator can be NDVI, vegetation productivity, soil quality, biodiversity, an ecosystem service, a pollutant, climate, or hydrology.

Check these items:

- outcome indicator and unit.
- predictor families and their expected ecological meaning.
- sample size, time span, site count, and clustering.
- missing-data and scaling decisions.
- component-count selection rule.

- cross-validation design, and whether it respects time, site, or spatial grouping.
- RMSEP, R2 and Q2, residual checks, and influential observations.
- the VIP table, the VIP threshold, and the coefficient direction.
- whether the paper reads VIP as predictive importance, as mechanism, or as a causal effect.
- robustness checks: an alternative component count, leave-one-year or leave-one-site validation, or a baseline regression.

Do not read a VIP ranking as a causal driver. VIP is a model-dependent predictive summary.

### Ecosystem-Service Threshold ML Audit

Use this mode when a study maps ecosystem services or ESRs. The study then uses interpretable ML, GWR, a GAM, XGBoost, a GBDT, SHAP, a PDP, ICE, ALE, or response-curve overlays. The goal is a management threshold or an optimal driver interval.

Check these items:

- ecosystem services and the pairwise ESR definitions.
- spatial unit, resolution, years, and service-assessment models.
- relationship code: synergy, trade-off, co-benefit, competition, or comprehensive-synergy probability.
- driver families: climate, topography, landscape, land use, human pressure, accessibility, and policy.
- the spatial heterogeneity model, such as GWR, with its bandwidth and kernel choices.

- the ML model set, the tuning, the validation, and the spatial-leakage checks.
- the interpretability method, and the source of the thresholds.
- the optimal interval, the probability target, and the uncertainty.
- the zoning or management translation, and whether it is descriptive, predictive, or causal.
- robustness checks against an alternative service model, resolution, model family, or threshold rule.

Do not read a model-derived threshold as a causal ecological tipping point. Ask for experimental, quasi-experimental, mechanistic, or temporal evidence first.

### Air Quality Food-Security Audit

Use this mode when a study estimates an atmospheric effect on crop productivity or food security. The exposure is ozone, fine particulate matter, AOD, diffuse radiation, SIF, temperature, or a related condition. The outcome is yield, SIF, a productivity proxy, calories, self-sufficiency, or food security.

Check these items:

- crops, regions, years, and spatial unit.
- pollutant exposure metrics, such as AOT40, peak-season ozone, fine particulate matter, AOD, or aerosol loading.
- the crop outcome: yield, SIF, a productivity proxy, calorie output, or a supply-demand balance.
- the statistical model, the functional form, the crop fixed effects, the spatial effects, the weather controls, and the trend controls.
- the counterfactual air-quality targets, and whether a policy sets them.

- nonlinear and synergistic pollutant-response claims.
- validation against observed yields or independent productivity data.
- the translation from yield to calories, self-sufficiency, imports, or food security.
- data and code availability, and the uncertainty in crop area, the crop-calorie conversion, and the counterfactual.

Do not read a counterfactual as a realized production gain. Check crop area, weather, management, prices, imports, storage, and policy implementation.

### Biodiversity Stability Climate-Stress Audit

Use this mode when a study evaluates whether biodiversity supports ecosystem stability. The biodiversity dimension is soil biodiversity, microbial diversity, functional diversity, or community composition. The stress gradient is aridity, drought, warming, land use, or a comparable climate pressure.

Check these items:

- biodiversity dimension and measurement platform.
- stability endpoint: temporal stability, resistance, resilience, multifunctionality, productivity variability, or service stability.
- climate-stress gradient and exposure window.
- ecosystem type, spatial domain, sampling design, and temporal depth.
- the interaction or moderation model, and whether aridity weakens, strengthens, or changes the relationship.

- controls for productivity, soil, climate, land use, management, and spatial dependence.
- mechanism evidence from microbes, soil nutrients, plant traits, or food-web structure.
- uncertainty, threshold, nonlinear, and subgroup evidence.
- whether the claims are observational, experimental, manipulative, or causal.

Do not claim that biodiversity stabilizes an ecosystem under aridity without the metric, gradient, scale, and spatial dependence. Name the possible productivity confounder too.

### Soil Fauna Carbon Meta-Analysis Audit

Use this mode when a study synthesizes how soil fauna affects soil carbon. The focal fauna is an ant, a termite, an earthworm, or a comparable organism. The outcome is soil carbon storage, a carbon flux, organic-matter turnover, or stability.

Check these items:

- focal fauna and functional traits.
- the separation of stock, flux, and stability outcomes.
- the effect-size family and the percent-change interpretation.
- climate, latitude, baseline SOC, or ecosystem moderators.
- the dependence plan for multiple endpoints per study.

- whether driver ranking uses random forest or another ML method.
- whether indirect pathways use a partial least squares path model, an SEM, or another path model.
- whether "more storage" and "more emissions" both appear, and how the paper reads that pattern.

Do not flatten a soil-fauna effect into one carbon label. Stock and flux outcomes can move in opposite directions.

### Small-Wetland Methane Scaling Audit

Use this mode when a study estimates emissions from small water bodies. The systems are small wetlands, ponds, or patchy ecosystems. Spatial resolution and the minimum mapping unit change the regional or global budget in these systems.

Check these items:

- wetland or water-body size class.
- mapping resolution and minimum detectable area.
- the forested and non-forested domain boundary.
- the wetland inventory or remote-sensing product.
- the flux model or emission-factor source.

- the annual trend window.
- the contribution to total emissions.
- uncertainty, double-counting, and omission risks.
- the implications for methane budgets and restoration policy.

Do not treat a coarse-resolution wetland product as scale neutral. Audit which small features the product omits.

### Cryosphere Ground-Ice Map Audit

Use this mode when a study creates or reuses a spatial map product. The map variable is permafrost, near-surface ground ice, volumetric ice content, an active-layer property, or a thermokarst hazard.

Check these items:

- target map variable and depth convention.
- spatial domain, permafrost mask, map year or window, resolution, and grid definition.
- field observation type, count, spatial distribution, and measurement comparability.
- the predictor stack: substrate, hydrology, topography, geology, paleoclimate, modern climate, remote sensing, and vegetation.
- model families, the ensemble strategy, the calibration data, and the simulation count.

- the validation design, including independent or spatially blocked validation.
- spatial autocorrelation, sampling bias, and extrapolation checks.
- accuracy, bias, RMSE, R2, the prediction interval, and the uncertainty maps.
- the storage, extent, hazard, infrastructure, climate, hydrology, and ecosystem interpretations.
- the data DOI, the code availability, and the map version.

Do not treat a geospatial map as ground truth. Audit observation density, spatial autocorrelation, the domain mask, the predictor time windows, the uncertainty layer, and the extrapolation zone.

### Agroecosystem Nutrient Meta-Analysis

Use this mode for a fertilizer, manure, compost, liming, biochar, or nutrient-management review. The outcomes are crop, soil, emission, or microbial outcomes.

Check these items:

- the intervention nutrient form and rate.
- the comparator nutrient background.
- the crop or ecosystem.
- the soil baseline status.
- climate and geography.
- experiment duration.

- the yield endpoint and unit.
- the soil-carbon or soil-health endpoint.
- the response-ratio or percent-change metric.
- the moderator plan.
- the dual-outcome trade-off interpretation.

Do not collapse fertilizer form, nutrient rate, baseline limitation, crop type, and climate into one pooled effect. Use moderator or subgroup logic instead.

### Food-System Bidirectional Nexus Review

Use this mode when food production affects environmental pressures and those changes feed back onto food production.

Check these items:

- food-system scope and commodity groups.
- pressure domains: nutrients, water, biodiversity, climate, land use, soil, and pollutants.
- feedback receptors: crops, livestock, blue foods, and food security.
- trade and displacement pathways.
- supply-side strategies.

- demand-side strategies.
- circularity and redesign strategies.
- regional vulnerability and equity concerns.
- evidence certainty and data-source limits.

Do not describe food-system impacts in one direction only when the question is bidirectional. Map both the pressure pathway and the feedback pathway.

### System-Hub Variable Audit

Use this mode when a paper treats one focal variable as a systems connector. A nitrogen, carbon, water, phosphorus, potassium, air-pollution, or biodiversity-pressure variable can serve as the hub. It links environmental burdens, productivity, health, food security, ecosystem function, or policy goals.

Check these items:

- the focal system variable, and why the paper treats it as a hub.
- the coupled outcome families, and which the paper measures rather than translates.
- the boundary, threshold, or target definition.
- the sectors, regions, or layers in scope.
- the hotspot or hidden-layer logic.

- the co-benefit and trade-off pattern.
- the scenario or policy-portfolio structure.
- the uncertainty in the translation from a biophysical result to a policy claim.
- the cross-domain lesson that could transfer to another nexus variable.

Do not present a policy lever as sufficient on its own. Audit the implementation quality and the compensating inputs.

### Food-Waste Geospatial ML Forecast

Use this mode when a study predicts food waste or organic waste. The spatial units are counties, cities, markets, facilities, or supply-chain regions.

Check these items:

- waste stream and supply-chain boundary.
- spatial unit and resolution.
- target estimate source and measurement limits.
- demographic, retail, expenditure, income, policy, and access predictors.
- model families and hyperparameter tuning.

- spatial validation and leakage checks.
- feature importance and uncertainty.
- the logistics, facility-siting, circular-bioeconomy, or waste-to-resource interpretation.
- the limits on translating predicted waste into collectible feedstock.

Do not treat a county-level prediction as directly collectible waste. Check collection participation, contamination, hauling cost, facility capacity, and policy.

Do not read a population count or an income value as a causal driver without a causal design.

### Crop-Yield ML Prediction Audit

Use this mode when a study predicts crop yield. The inputs are weather, genotype, breeding value, trial data, remote sensing, soil, or management.

Check these items:

- crop, region, years, sites, genotypes, and trial design.
- input data families and temporal aggregation.
- target yield definition and unit.
- the model families compared.
- hyperparameter tuning and the validation split.

- leakage risks across site, year, genotype, and repeated trials.
- performance metrics.
- interpretability method.
- extrapolation and future-climate assumptions.
- reproducibility and data-access status.

Do not treat a random train-test result as proof of generalization to new years, sites, or genotypes. Require grouped or out-of-domain validation where the claim needs it.

Do not present a future yield forecast without explicit weather or climate inputs, the scenario assumptions, and the extrapolation checks.

### Environmental Causal ML Audit

Use this mode when a study claims causal effects from high-dimensional data. The data cover an environmental, pollutant, socioeconomic, microbial, omics, health, or infrastructure quantity. DML, causal forests, meta-learners, AutoML plus causal inference, and interpretable ML are the usual estimators.

Check these items:

- unit of observation and sampling frame.
- treatment and exposure definitions.
- outcome endpoint and measurement platform.
- covariate timing and the confounder set.
- the predictive model and the causal estimator.

- nuisance-model, cross-fitting, and overlap checks.
- the interpretability method, and whether it is causal or predictive.
- sensitivity to hidden confounding, spatial dependence, and multiple testing.
- the policy or risk-assessment claim and its limits.

Do not call a DML or CATE estimate causal without treatment timing, adjustment, overlap, and hidden-confounding risk.

Do not treat DML as a generic prediction method. DML estimates a causal parameter only under the stated identification assumptions.

For an urban heat study, add these items:

- the treatment or exposure: a heatwave event, green space, an impervious surface, shade, a cool roof, ventilation, or an adaptation policy.
- the outcome: LST, SUHI intensity, air temperature, heat exposure, nighttime lights, activity, energy use, or health.
- remote-sensing, morphology, meteorology, population, income, activity, and infrastructure confounders.
- spatial autocorrelation, spillover, clustered inference, and the panel or event-study structure.
- whether the claim is an average effect, a heterogeneous effect, or a mediation.

Do not treat spatial DML as solved by adding coordinates. Audit spatial dependence, spillover, clustered inference, and the validation boundaries.

### Irrigation Salinity Optimization Audit

Use this mode when a study combines field trials, statistical response curves, and multiobjective optimization. The aim is an irrigation or nutrient-management window.

Check these items:

- crop, region, irrigation method, and the salinity or nutrient treatments.
- response variables: yield, quality, soil properties, GHG emissions, water use, and salt balance.
- the model used for the nonlinear response, such as a GAM.
- the optimizer used to define the compromise range, such as NSGA-II.

- objectives, constraints, units, and the direction of improvement.
- the decision range, and whether it is site-specific.
- the risks from a short time window, salinity accumulation, unmeasured costs, and extrapolation.

Do not generalize an irrigation decision range across regions without soil, groundwater, climate, crop, and method checks.

### Environmental Scenario Audit

Use this mode when papers combine study extraction, model prediction, spatial extrapolation, and policy scenarios.

Check these items:

- evidence database scope.
- target variable and units.
- model family and validation plan.
- spatial and temporal extrapolation assumptions.
- scenario levers.

- management-quality assumptions.
- uncertainty and sensitivity checks.
- the policy claim and its limits.

Do not treat an ML scenario projection as causal proof without a design that supports causal interpretation.

### Pareto-Frontier Trade-Off Audit

Use this mode when a study optimizes across multiple environmental or ecosystem-service objectives.

Check these items:

- decision unit.
- land-use or management options.
- objectives and units.
- baseline or reference.
- constraints and excluded areas.

- the model used to generate the objective values.
- the optimization algorithm.
- the frontier interpretation.
- priority maps and consensus.
- transition costs, emissions, biodiversity, governance, and realism limits.

Do not treat a Pareto-efficient frontier as a politically feasible pathway without the social, economic, governance, biodiversity, and transition-cost constraints.

Do not collapse a global objective gain into a local welfare claim without supply, trade, livelihood, and justice checks.

## Worked Examples

### Example 1: a protocol that passes every gate

The review question is "does soil fauna change soil carbon storage in drylands".

- framework: PECO.
- population: dryland soil fauna.
- exposure: ant and termite activity.
- comparator: fauna exclusion.
- outcomes: soil organic carbon stock.
- units: grams of carbon per kilogram of soil.

- designs: field exclusion experiment; paired site comparison.
- heterogeneity: climate zone; soil texture; baseline carbon.
- risk of bias: an internal-validity checklist.
- synthesis: meta-analysis.
- comparability: one carbon-stock unit per study after a documented conversion.

Run `python3 scripts/check_protocol.py --input peco.json`. The script reports eight passes and exits 0.

### Example 2: a protocol that fails the pooling gate

Use the Example 1 protocol, and delete the comparability line. The synthesis mode is still meta-analysis.

Run the same command. The script reports `FAIL G8 pooling` and exits 1. The other seven gates still pass, so the finding names the one defect.

### Example 3: a missing input

Run `python3 scripts/check_protocol.py --input no-such-file.json`. The script prints `INPUT GAP`, exits 4, and prints no gate result. An input gap is never a pass and never a finding.

## Failure Modes

Each failure mode below produces one exact status and exit code.

<!-- ste-allow R1, R3: a failure table is data, not prose -->

| Condition | Status | Exit |
|---|---|---|
| the protocol file does not exist | input gap | 4 |
| the protocol file is empty | input gap | 4 |
| the JSON does not parse | input gap | 4 |
| the JSON root is not an object | input gap | 4 |
| a declared gate fails | finding | 1 |
| every declared gate passes | pass | 0 |

Two domain failure modes have no exit code, because a human decides them.

- A pooled effect over incomparable exposures is a review defect. The gate cannot see it; the reviewer must.
- A causal claim from an observational design is a review defect. Record the design label beside every claim.

## Guardrails

### Guardrails: pooling and design

- Do not pool across species, exposure windows, or outcome constructs without a stated rationale.
- Do not collapse mechanistic, observational, and experimental evidence without design labels.
- Do not hide geography, climate zone, tissue type, or measurement platform when these drive heterogeneity.
- Do not use vote-counting as evidence of an effect direction or strength.
- Do not interpret a short-term yield gain as soil-carbon sequestration evidence without duration, baseline SOC, depth, and method checks.
- Do not treat a random train-test result as proof of generalization.

### Guardrails: PLS, thresholds, and maps

- Do not treat PLS VIP rankings as causal drivers of an environmental outcome.
- Do not read a PLS or VIP result without the component count, cross-validation, coefficient direction, and residual checks.
- Do not treat an ESR threshold from a PDP, SHAP, ALE, or response curve as a causal ecological tipping point.
- Do not translate an optimal interval into a zoning rule without the leakage, resolution, uncertainty, and feasibility checks.
- Do not treat a geospatial environmental map as ground truth.
- Do not compare cryosphere maps across products or periods without the target definition, depth convention, boundary, resolution, vintage, and uncertainty.

### Guardrails: air, water, and food

- Do not treat an air-quality food-security counterfactual as a realized production gain.
- Do not treat a SIF or remote-sensing productivity proxy as yield without crop-specific validation and conversion logic.
- Do not treat a coarse-resolution wetland product as scale neutral.
- Do not compare methane budgets without a double-counting check between water-body classes.
- Do not turn methane emissions alone into a wetland management recommendation.
- Do not treat global average food footprints as local risk without trade, geography, vulnerability, and production-system context.

### Guardrails: biodiversity and soil fauna

- Do not claim that biodiversity stabilizes an ecosystem under aridity without the metric, gradient, scale, and spatial dependence.
- Do not interpret biodiversity-stability moderation as causal unless the design supports causal identification.
- Do not flatten soil-fauna effects into one carbon benefit or cost label.
- Do not collapse fertilizer form, nutrient rate, baseline limitation, crop type, and climate into one pooled effect.
- Do not describe food-system impacts in only one direction when the review question is bidirectional.
- Do not use vote-counting as evidence of effect direction or strength.

### Guardrails: causal and predictive claims

- Do not treat SHAP, feature importance, a PDP, or AutoML performance as causal evidence without a separate identification strategy.
- Do not call DML or CATE estimates causal unless treatment timing, adjustment, overlap, and hidden-confounding risk are explicit.
- Do not treat DML as a generic prediction method.
- Do not treat spatial DML as solved by adding coordinates.
- Do not interpret variable importance, a PDP, or a SHAP value causally unless the design supports it.
- Do not present a future yield forecast without explicit weather inputs, scenario assumptions, and extrapolation checks.

### Guardrails: geospatial and scenario claims

- Do not ignore spatial autocorrelation, adjacency leakage, urban-rural imbalance, or high-waste outliers in a geospatial forecast.
- Do not interpret a population count or an income value as a causal driver without a causal design.
- Do not treat county-level predicted food waste as directly collectible waste.
- Do not treat an ML scenario projection as causal proof.
- Do not present a policy lever as sufficient without auditing implementation quality and compensating inputs.
- Do not treat a Pareto-efficient frontier as a politically feasible pathway.

### Guardrails: translation to policy

- Do not collapse global objective gains into local welfare claims without regional supply, trade, livelihood, water-access, and justice checks.
- Do not generalize an irrigation salinity decision range across regions without soil, groundwater, climate, crop, and method checks.
- Do not turn methane emissions alone into a wetland management recommendation without carbon storage, biodiversity, hydrology, and ecosystem-service trade-offs.
- Do not compare methane budgets without a double-counting check between water-body classes.
- Do not treat a geospatial map as ground truth when the observation density is unknown.
- Do not present a policy claim without the uncertainty of the biophysical-to-policy translation.

## What This Does Not Do

- This skill does not run a literature search (use `paper-search`).
- This skill does not appraise a study; it specifies the tool and the domains to record.
- This skill does not pool an effect (use `meta-analysis-forge` for the engine).
- This skill does not resolve a citation (use `citecheck` for that).

- This skill does not prove that a review is complete or correct. The gate covers eight declared protocol fields only.
- This skill does not read a PDF, a map, or a dataset. It plans what to extract from them.
- This skill does not decide a policy question. It records the evidence that a policy claim needs.

## Rubric Coverage

`eval.md` holds the rubric. The table below maps every rubric item to the section that implements it.

<!-- ste-allow R1, R3: a coverage table is data, not prose -->

| Rubric item | Implemented in |
|---|---|
| E1 framework statement | Terms; Gate script and exit codes; PECO Protocol Memo |
| E2 exposure and comparator definition | Intake; Workflow |
| E3 outcome unit | Preflight and dependencies; Domain Extraction Plan |
| E4 eligible designs | Intake; Workflow |
| E5 heterogeneity plan | Intake; Output Modes |
| E6 appraisal plan | Workflow; Output Modes |
| E7 synthesis mode | Workflow; Failure Modes |
| E8 pooling rationale | Gate script and exit codes; Worked Examples; Failure Modes |
| E9 domain extraction table | Workflow; Domain Extraction Plan |
| E10 domain audit checklist | Output Modes (every audit mode) |
| E11 claim bound and design label | Guardrails; What This Does Not Do |
| E12 input-gap handling | Gate script and exit codes; Failure Modes; Worked Examples |
