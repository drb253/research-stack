#!/usr/bin/env Rscript
# Cochrane-grade meta-analysis engine (Cochrane Handbook v6.5, ch. 6, 9, 10, 13).
#
# Fits fixed- and random-effects models, reports tau^2 / I^2 / H^2 / Q and a
# PREDICTION INTERVAL (never I^2 alone), optional Hartung-Knapp-Sidik-Jonkman and
# cluster-robust (CR2) standard errors, subgroup analysis, meta-regression, and
# small-study/publication-bias diagnostics -- each with the Handbook's own
# guardrails (>=10 studies for funnel/meta-regression; asymmetry is not proof).
#
# Input modes
#   1. Precomputed (generic inverse variance, Handbook ch.6): columns study_id,
#      effect_id, effect_metric, estimate, se
#   2. Raw counts/means (computes via metafor::escalc): OR/RR/RD need ai,bi,ci,di;
#      MD/SMD need n1i,m1i,sd1i,n2i,m2i,sd2i
#
# Usage
#   Rscript cochrane_meta.R --input sheet.csv --outdir out \
#       [--metric SMD] [--tau2 REML] [--hksj] [--rve] [--subgroup design] \
#       [--moderator dose] [--plots]
#
# Outputs (in --outdir): summary.txt, results.json, sessionInfo.txt,
#   forest.pdf / funnel.pdf (with --plots)
#
# This script COMPUTES; it never invents. Every reported number comes from an
# executed model. Determinism note: seeds are logged, but exact reproducibility
# of *statistics* is the guarantee (locked data + script + library versions).

suppressPackageStartupMessages({
  if (!requireNamespace("metafor", quietly = TRUE)) {
    stop("Package 'metafor' is required. Run scripts/install_r_packages.R", call. = FALSE)
  }
  library(metafor)
})

## ---- arguments -----------------------------------------------------------
args <- commandArgs(trailingOnly = TRUE)
get_arg <- function(flag, default = NULL) {
  i <- match(flag, args)
  if (is.na(i) || i == length(args)) default else args[[i + 1]]
}
has_flag <- function(flag) flag %in% args

input  <- get_arg("--input")
outdir <- get_arg("--outdir", "meta_out")
metric <- get_arg("--metric")            # optional filter/override
tau2   <- get_arg("--tau2", "REML")
use_hksj <- has_flag("--hksj")
use_rve  <- has_flag("--rve")
subgroup  <- get_arg("--subgroup")
moderator <- get_arg("--moderator")
do_plots  <- has_flag("--plots")

if (is.null(input)) stop("Missing --input (coding sheet CSV).", call. = FALSE)
if (!file.exists(input)) {
  ## A file that could not be read is an input condition, not a finding about the
  ## analysis: exit 4 (insufficient_input), the vocabulary used by numbers_provenance.py.
  cat(paste0("Error: Input not found: ", input, "\n"), file = stderr())
  quit(save = "no", status = 4)
}
dir.create(outdir, recursive = TRUE, showWarnings = FALSE)

## ---- tiny JSON writer (no non-base dependency) ---------------------------
jstr <- function(x) {
  if (is.null(x) || length(x) == 0) return("null")
  if (is.character(x)) return(paste0('"', gsub('"', '\\\\"', x), '"'))
  if (is.logical(x)) return(tolower(as.character(x)))
  if (is.numeric(x)) return(ifelse(is.finite(x), formatC(x, digits = 8, format = "g"), "null"))
  "null"
}
jobj <- function(named_list) {
  kv <- vapply(seq_along(named_list), function(i)
    paste0(jstr(names(named_list)[i]), ": ", jstr(named_list[[i]])), character(1))
  paste0("{", paste(kv, collapse = ", "), "}")
}

## ---- read + validate -----------------------------------------------------
dat <- read.csv(input, stringsAsFactors = FALSE, na.strings = c("", "NA", "N/A", "NR"))

compute_from_raw <- function(d) {
  raw_counts <- all(c("ai","bi","ci","di") %in% names(d))
  raw_means  <- all(c("n1i","m1i","sd1i","n2i","m2i","sd2i") %in% names(d))
  m <- toupper(d$effect_metric[1])
  if (m %in% c("OR","RR","RD") && raw_counts) {
    return(escalc(measure = m, ai = ai, bi = bi, ci = ci, di = di, data = d))
  }
  if (m %in% c("MD","SMD") && raw_means) {
    return(escalc(measure = m, n1i = n1i, m1i = m1i, sd1i = sd1i,
                  n2i = n2i, m2i = m2i, sd2i = sd2i, data = d))
  }
  NULL
}

if (!all(c("study_id","effect_metric") %in% names(dat)))
  stop("Sheet must contain at least study_id and effect_metric.", call. = FALSE)

if (!all(c("estimate","se") %in% names(dat))) {
  esc <- compute_from_raw(dat)
  if (is.null(esc)) stop("Need either estimate+se columns, or raw count/mean columns.", call. = FALSE)
  dat$estimate <- esc$yi
  dat$se <- sqrt(esc$vi)
}
if (!("effect_id" %in% names(dat))) dat$effect_id <- seq_len(nrow(dat))

## ---- input condition: rows supplied vs rows usable -----------------------
## The invariant (docs/EVIDENCE-INVARIANT.md): the analysis of the rows that
## happened to be usable must never be presented as the analysis of the rows
## supplied. Count them, name every row we cannot use and why, and refuse by
## default. --allow-incomplete is the documented opt-out; it still writes the
## worklist and still prints the condition, so the override is logged, not silent.
allow_incomplete <- has_flag("--allow-incomplete")
rows_in <- nrow(dat)
est_raw <- dat$estimate
se_raw  <- dat$se
est_num <- suppressWarnings(as.numeric(est_raw))
se_num  <- suppressWarnings(as.numeric(se_raw))
usable  <- is.finite(est_num) & is.finite(se_num) & se_num > 0

drop_reason <- function(est_raw, se_raw, est_n, se_n) {
  is_blank <- function(x) is.na(x) || (is.character(x) && !nzchar(trimws(as.character(x))))
  if (is_blank(est_raw)) return("blank effect size")
  if (is.na(est_n))      return("non-numeric effect size")
  if (!is.finite(est_n)) return("non-finite effect size")
  if (is_blank(se_raw))  return("blank standard error")
  if (is.na(se_n))       return("non-numeric standard error")
  if (!is.finite(se_n))  return("non-finite standard error")
  if (se_n <= 0)         return("se <= 0")
  "unusable effect"
}

dropped <- data.frame(row = integer(0), study_id = character(0),
                      effect_id = character(0), reason = character(0),
                      stringsAsFactors = FALSE)
for (i in which(!usable)) {
  dropped <- rbind(dropped, data.frame(
    row = i, study_id = as.character(dat$study_id[i]),
    effect_id = as.character(dat$effect_id[i]),
    reason = drop_reason(est_raw[i], se_raw[i], est_num[i], se_num[i]),
    stringsAsFactors = FALSE))
}
dat <- dat[usable, , drop = FALSE]
dat$estimate <- est_num[usable]
dat$se <- se_num[usable]
rows_out <- nrow(dat)

write_worklist <- function(rows, n_in, n_out, status) {
  items <- vapply(seq_len(nrow(rows)), function(i) {
    paste0("{",
           paste(c(sprintf('"row": %s', jstr(rows$row[i])),
                   sprintf('"study_id": %s', jstr(rows$study_id[i])),
                   sprintf('"effect_id": %s', jstr(rows$effect_id[i])),
                   sprintf('"reason": %s', jstr(rows$reason[i]))),
                 collapse = ", "),
           "}")
  }, character(1))
  payload <- paste0("{\n",
    '  "status": ', jstr(status), ",\n",
    '  "rows_in": ', jstr(n_in), ",\n",
    '  "rows_out": ', jstr(n_out), ",\n",
    '  "dropped_count": ', jstr(nrow(rows)), ",\n",
    '  "dropped": [', paste(items, collapse = ", "), "]\n}\n")
  path <- file.path(outdir, "worklist.json")
  writeLines(payload, path)
  path
}

worklist_path <- NULL
if (nrow(dropped) > 0) {
  worklist_path <- write_worklist(dropped, rows_in, rows_out, "insufficient_evidence")
  cat(sprintf(paste0("INPUT CONDITION: insufficient_evidence -- %d of %d supplied row(s) ",
                     "could not be used; any estimate below covers only the %d usable row(s).\n"),
              nrow(dropped), rows_in, rows_out))
  cat(sprintf("  dropped: %s\n",
              paste(sprintf("%s (%s)", dropped$study_id, dropped$reason), collapse = "; ")))
  cat(sprintf("  worklist: %s\n", normalizePath(worklist_path, winslash = "/", mustWork = FALSE)))
}

if (nrow(dat) < 2) stop("Fewer than 2 usable effects after cleaning.", call. = FALSE)

if (nrow(dropped) > 0) {
  if (!allow_incomplete) {
    cat("  Refusing to present a pooled estimate over a subset of the supplied rows.\n")
    cat(paste0("  Pass --allow-incomplete to pool the usable rows anyway (the worklist is ",
               "still written and this condition still reported).\n"))
    quit(save = "no", status = 3)
  }
  cat("  --allow-incomplete: pooling the usable rows; the input condition stands.\n")
}

if (!is.null(metric)) dat <- dat[toupper(dat$effect_metric) == toupper(metric), , drop = FALSE]
if (nrow(dat) < 2) stop("Fewer than 2 effects after metric filter.", call. = FALSE)

metrics <- unique(toupper(dat$effect_metric))
if (length(metrics) > 1) {
  ## A warning is not enough here: pooling different estimands is a Handbook ch.6 error,
  ## and continuing produces a pooled number that LOOKS authoritative while being
  ## methodologically invalid. Refuse unless the user explicitly says the estimates are
  ## already on a common scale.
  if (!has_flag("--allow-mixed-metrics")) {
    stop(sprintf(paste0("Sheet mixes %d effect metrics (%s). Pooling different estimands is a ",
                        "Handbook ch.6 error. Either filter with --metric <X>, convert them to one ",
                        "family first, or pass --allow-mixed-metrics if the estimates are ALREADY ",
                        "on a common scale."),
                 length(metrics), paste(metrics, collapse = ", ")), call. = FALSE)
  }
  warning(sprintf(paste0("Multiple effect metrics present (%s); pooling anyway because ",
                         "--allow-mixed-metrics was passed explicitly."),
                  paste(metrics, collapse = ", ")))
}
metric <- metrics[1]
k <- nrow(dat)
es <- escalc(measure = "GEN", yi = estimate, vi = se^2, data = dat)

## ---- model fitting -------------------------------------------------------
re_fit <- rma(yi, vi, data = es, method = tau2)
fe_fit <- tryCatch(rma(yi, vi, data = es, method = "FE"), error = function(e) NULL)

hksj_fit <- NULL
if (use_hksj) {
  hksj_fit <- tryCatch(rma(yi, vi, data = es, method = tau2, test = "knha"),
                       error = function(e) NULL)
}
rve_fit <- NULL
if (use_rve && "cluster" %in% names(es)) {
  if (requireNamespace("clubSandwich", quietly = TRUE)) {
    rve_fit <- tryCatch(robust(re_fit, cluster = es$cluster, clubSandwich = TRUE),
                        error = function(e) NULL)
  } else warning("clubSandwich not installed; RVE skipped.")
}

## ---- heterogeneity (Handbook ch.10: never I^2 alone) ---------------------
het <- list(Q = re_fit$QE, Q_df = re_fit$k - 1, Q_p = re_fit$QEp,
            tau2 = re_fit$tau2, I2 = re_fit$I2, H2 = re_fit$H2)
## With QE <= df, I^2 = 0% and H^2 = 1 are what the estimator returns when there is
## no signal to estimate, not a measurement of "no heterogeneity" in the literature.
## Report them as not estimable rather than as numbers a reader could read as a finding.
het_estimable <- isTRUE(het$Q > het$Q_df)
pi <- tryCatch(predict(re_fit), error = function(e) NULL)

## ---- subgroup analysis ---------------------------------------------------
sub_res <- NULL
if (!is.null(subgroup) && subgroup %in% names(es)) {
  sub_res <- tryCatch(rma(yi, vi, data = es, method = tau2,
                          mods = ~ factor(es[[subgroup]])), error = function(e) NULL)
}

## ---- meta-regression (Handbook ch.10: typically >=10 studies) ------------
mr_res <- NULL
if (!is.null(moderator) && moderator %in% names(es)) {
  if (k < 10) warning(sprintf("Meta-regression on k=%d; Handbook advises >=10 studies.", k))
  mr_res <- tryCatch(rma(yi, vi, data = es, method = tau2,
                         mods = ~ es[[moderator]]), error = function(e) NULL)
}

## ---- small-study / publication bias (Handbook ch.13: need >=10) ----------
pb <- list()
if (k >= 10) {
  pb$egger <- tryCatch(regtest(re_fit), error = function(e) NULL)
  pb$begg  <- tryCatch(ranktest(re_fit), error = function(e) NULL)
  pb$trimfill <- tryCatch(trimfill(re_fit), error = function(e) NULL)
} else {
  pb$note <- sprintf("k=%d < 10: funnel/Egger/trim-and-fill are uninformative (Handbook ch.13).", k)
}

## ---- sensitivity ---------------------------------------------------------
loo <- tryCatch(leave1out(re_fit), error = function(e) NULL)

## ---- back-transform for display if ratio measure -------------------------
bt <- function(x) if (isTRUE(has_flag("--log-scale"))) exp(x) else x

## ---- outputs -------------------------------------------------------------
out <- list(
  input = normalizePath(input), metric = metric, k = k,
  status = if (nrow(dropped) > 0) "insufficient_evidence" else "pass",
  rows_in = rows_in, rows_out = rows_out, dropped_count = nrow(dropped),
  model = tau2, hksj = use_hksj, rve = !is.null(rve_fit),
  pooled = as.numeric(bt(re_fit$b)), ci_lb = as.numeric(bt(re_fit$ci.lb)),
  ci_ub = as.numeric(bt(re_fit$ci.ub)), p = as.numeric(re_fit$pval),
  fe_pooled = if (!is.null(fe_fit)) as.numeric(bt(fe_fit$b)) else NA_real_,
  tau2 = het$tau2,
  I2 = if (het_estimable) het$I2 else NA_real_,
  H2 = if (het_estimable) het$H2 else NA_real_,
  Q = if (het_estimable) het$Q else NA_real_,
  Q_p = if (het_estimable) het$Q_p else NA_real_,
  pi_lb = if (!is.null(pi)) as.numeric(bt(pi$pi.lb)) else NA_real_,
  pi_ub = if (!is.null(pi)) as.numeric(bt(pi$pi.ub)) else NA_real_
)
if (!is.null(hksj_fit)) {
  out$hksj_ci_lb <- as.numeric(bt(hksj_fit$ci.lb)); out$hksj_ci_ub <- as.numeric(bt(hksj_fit$ci.ub))
  out$hksj_p <- as.numeric(hksj_fit$pval)
}

## ---- surface the optional analyses ---------------------------------------
## These were previously computed and then dropped, so `--rve` printed
## "RVE(CR2)" in the header while reporting the CONVENTIONAL interval -- a
## materially misleading output. Every requested analysis is now written out.
if (!is.null(rve_fit)) {
  out$rve_ci_lb <- as.numeric(bt(rve_fit$ci.lb))
  out$rve_ci_ub <- as.numeric(bt(rve_fit$ci.ub))
  out$rve_p <- as.numeric(rve_fit$pval)
  out$rve_df <- as.numeric(rve_fit$dfs)
  out$rve_clusters <- length(unique(es$cluster))
  ## RVE is itself unreliable at very few clusters: the CR2 interval can be
  ## extremely wide (df ~ 1 with 2 clusters). Say so rather than let the user
  ## read a 2-cluster interval as if it were well estimated.
  out$rve_small_cluster_warning <- isTRUE(out$rve_clusters < 10)
}

sub_lines <- character(0)
if (!is.null(sub_res)) {
  out$subgroup_var <- subgroup
  out$subgroup_QM <- as.numeric(sub_res$QM)
  out$subgroup_QM_df <- as.numeric(sub_res$QMdf[1])
  out$subgroup_QM_p <- as.numeric(sub_res$QMp)
  sub_lines <- sprintf("Subgroup analysis by '%s' -- omnibus test for differences: QM = %.3f (df = %d, p = %.4g)",
                       subgroup, out$subgroup_QM, out$subgroup_QM_df, out$subgroup_QM_p)
  for (g in unique(as.character(es[[subgroup]]))) {
    idx <- !is.na(es[[subgroup]]) & as.character(es[[subgroup]]) == g
    if (sum(idx) < 2) {
      sub_lines <- c(sub_lines, sprintf("  %s: k = %d (too few to pool)", g, sum(idx)))
      next
    }
    f <- tryCatch(rma(yi, vi, data = es[idx, , drop = FALSE], method = tau2),
                  error = function(e) NULL)
    if (!is.null(f))
      sub_lines <- c(sub_lines, sprintf("  %s: k = %d, pooled = %.4f (95%% CI %.4f to %.4f), I^2 = %.1f%%",
                                        g, f$k, bt(f$b), bt(f$ci.lb), bt(f$ci.ub), f$I2))
  }
}

mr_lines <- character(0)
if (!is.null(mr_res)) {
  out$moderator <- moderator
  out$moderator_QM <- as.numeric(mr_res$QM)
  out$moderator_QM_df <- as.numeric(mr_res$QMdf[1])
  out$moderator_QM_p <- as.numeric(mr_res$QMp)
  mr_lines <- sprintf("Meta-regression on '%s' (coefficients on the ANALYSIS scale, not back-transformed)",
                      moderator)
  if (length(mr_res$b) == 2L) {
    out$moderator_slope <- as.numeric(mr_res$b[2])
    out$moderator_slope_ci_lb <- as.numeric(mr_res$ci.lb[2])
    out$moderator_slope_ci_ub <- as.numeric(mr_res$ci.ub[2])
    out$moderator_slope_p <- as.numeric(mr_res$pval[2])
    mr_lines <- c(mr_lines, sprintf("  slope = %.4f (95%% CI %.4f to %.4f), p = %.4g",
                                    out$moderator_slope, out$moderator_slope_ci_lb,
                                    out$moderator_slope_ci_ub, out$moderator_slope_p))
  } else {
    mr_lines <- c(mr_lines, sprintf("  %d moderator coefficient(s); see the omnibus test below.",
                                    length(mr_res$b) - 1L))
  }
  mr_lines <- c(mr_lines,
                sprintf("  Omnibus moderator test: QM = %.3f (df = %d, p = %.4g)",
                        out$moderator_QM, out$moderator_QM_df, out$moderator_QM_p))
  if (k < 10)
    mr_lines <- c(mr_lines,
                  sprintf("  CAUTION: k = %d < 10 -- Handbook advises >=10 studies for meta-regression.", k))
}

## publication-bias numbers, also surfaced for numeric-provenance tracing
if (!is.null(pb$egger))    { out$egger_p <- as.numeric(pb$egger$pval) }
if (!is.null(pb$begg))     { out$begg_p <- as.numeric(pb$begg$pval) }
if (!is.null(pb$trimfill)) { out$trimfill_k0 <- as.numeric(pb$trimfill$k0) }

## ---- leave-one-out sensitivity (was computed and then discarded) ----------
loo_lines <- character(0)
if (!is.null(loo)) {
  loo_est <- as.numeric(bt(loo$estimate))
  out$loo_k <- length(loo_est)
  out$loo_min <- min(loo_est)
  out$loo_max <- max(loo_est)
  sig_full <- isTRUE(out$p < 0.05)
  flips <- sum((loo$pval < 0.05) != sig_full)
  out$loo_significance_flips <- flips
  loo_lines <- sprintf("Leave-one-out: pooled estimate ranges %.4f to %.4f across %d refits (full model %.4f)",
                       out$loo_min, out$loo_max, out$loo_k, out$pooled)
  if (flips > 0)
    loo_lines <- c(loo_lines, sprintf("  NOTE: omitting a single study changes the p<0.05 conclusion in %d of %d refits -- the finding is fragile.",
                                      flips, out$loo_k))
  else
    loo_lines <- c(loo_lines, sprintf("  Omitting no single study changes the p<0.05 conclusion (%d refits).",
                                      out$loo_k))
}

lines <- c(
  sprintf("Cochrane-grade meta-analysis -- metric=%s, k=%d, model=%s%s%s",
          metric, k, tau2, if (use_hksj) " + HKSJ" else "", if (!is.null(rve_fit)) " + RVE(CR2)" else ""),
  sprintf("Pooled effect: %.4f (95%% CI %.4f to %.4f), p = %.4g", out$pooled, out$ci_lb, out$ci_ub, out$p),
  if (het_estimable)
    sprintf("Heterogeneity: tau^2 = %.4f | I^2 = %.1f%% | H^2 = %.2f | Q = %.2f (df = %d, p = %.4g)",
            het$tau2, het$I2, het$H2, het$Q, het$Q_df, het$Q_p)
  else
    "Heterogeneity: not estimable (QE <= df)",
  if (!is.null(pi)) sprintf("Prediction interval: %.4f to %.4f", out$pi_lb, out$pi_ub) else "Prediction interval: n/a",
  if (!is.null(fe_fit)) sprintf("Fixed-effect pooled (for comparison): %.4f", out$fe_pooled) else "",
  if (!is.null(hksj_fit)) sprintf("HKSJ-adjusted CI: %.4f to %.4f (p = %.4g)", out$hksj_ci_lb, out$hksj_ci_ub, out$hksj_p) else "",
  if (!is.null(rve_fit)) sprintf("RVE (CR2) cluster-robust CI: %.4f to %.4f (p = %.4g, Satterthwaite df = %.1f, %d cluster(s)) -- this is the RVE interval",
                                 out$rve_ci_lb, out$rve_ci_ub, out$rve_p, out$rve_df, out$rve_clusters) else "",
  if (!is.null(rve_fit) && isTRUE(out$rve_small_cluster_warning))
    sprintf("  CAUTION: RVE with only %d cluster(s) -- the cluster-robust interval is itself poorly estimated at this few clusters; treat it as indicative, not definitive.",
            out$rve_clusters) else "",
  if (length(sub_lines)) c("", sub_lines) else "",
  if (length(mr_lines)) c("", mr_lines) else "",
  if (length(loo_lines)) c("", loo_lines) else "",
  "",
  if (!is.null(pb$note)) pb$note else sprintf("Publication-bias diagnostics run (k=%d): Egger/Begg/trim-and-fill.", k),
  if (!is.null(pb$egger)) sprintf("  Egger: p = %.4g", pb$egger$pval) else "",
  if (!is.null(pb$begg)) sprintf("  Begg: p = %.4g", pb$begg$pval) else "",
  if (!is.null(pb$trimfill)) sprintf("  Trim-and-fill: %d imputed studies (this is a SENSITIVITY check, not proof).", pb$trimfill$k0) else "",
  "",
  "NOTE: asymmetry in a funnel plot is not proof of publication bias (Handbook ch.13)."
)
lines <- lines[nzchar(lines)]
writeLines(lines, file.path(outdir, "summary.txt"))

json_fields <- c(
  sprintf('  "metric": %s', jstr(metric)),
  sprintf('  "k": %s', jstr(k)),
  sprintf('  "status": %s', jstr(out$status)),
  sprintf('  "rows_in": %s', jstr(out$rows_in)),
  sprintf('  "rows_out": %s', jstr(out$rows_out)),
  sprintf('  "dropped_count": %s', jstr(out$dropped_count)),
  sprintf('  "model": %s', jstr(tau2)),
  sprintf('  "pooled": %s', jstr(out$pooled)),
  sprintf('  "ci_lb": %s', jstr(out$ci_lb)),
  sprintf('  "ci_ub": %s', jstr(out$ci_ub)),
  sprintf('  "p": %s', jstr(out$p)),
  sprintf('  "fe_pooled": %s', jstr(out$fe_pooled)),
  sprintf('  "tau2": %s', jstr(out$tau2)),
  sprintf('  "I2": %s', jstr(out$I2)),
  sprintf('  "H2": %s', jstr(out$H2)),
  sprintf('  "Q": %s', jstr(out$Q)),
  sprintf('  "Q_p": %s', jstr(out$Q_p)),
  sprintf('  "heterogeneity": %s',
          jstr(if (het_estimable) "estimable" else "not estimable (QE <= df)")),
  sprintf('  "pi_lb": %s', jstr(out$pi_lb)),
  sprintf('  "pi_ub": %s', jstr(out$pi_ub)),
  sprintf('  "hksj": %s', jstr(use_hksj)),
  sprintf('  "rve": %s', jstr(!is.null(rve_fit)))
)
## every optional analysis that actually ran is written, never dropped
for (nm in c("hksj_ci_lb", "hksj_ci_ub", "hksj_p",
             "rve_ci_lb", "rve_ci_ub", "rve_p", "rve_df",
             "subgroup_var", "subgroup_QM", "subgroup_QM_df", "subgroup_QM_p",
             "moderator", "moderator_slope", "moderator_slope_ci_lb",
             "moderator_slope_ci_ub", "moderator_slope_p",
             "moderator_QM", "moderator_QM_df", "moderator_QM_p",
             "egger_p", "begg_p", "trimfill_k0",
             "loo_k", "loo_min", "loo_max", "loo_significance_flips",
             "rve_clusters", "rve_small_cluster_warning")) {
  if (!is.null(out[[nm]]))
    json_fields <- c(json_fields, sprintf('  "%s": %s', nm, jstr(out[[nm]])))
}
if (!is.null(worklist_path))
  json_fields <- c(json_fields, sprintf('  "worklist": %s', jstr(worklist_path)))
json_fields <- c(json_fields,
  sprintf('  "metafor_version": %s', jstr(as.character(packageVersion("metafor")))))
writeLines(paste0("{\n", paste(json_fields, collapse = ",\n"), "\n}"),
           file.path(outdir, "results.json"))
writeLines(capture.output(sessionInfo()), file.path(outdir, "sessionInfo.txt"))

if (do_plots) {
  pdf(file.path(outdir, "forest.pdf"), width = 8, height = max(4, 0.35 * k + 2))
  forest(re_fit, main = paste0("Forest plot (", metric, ", ", tau2, "-random effects)"),
         xlab = metric)
  dev.off()
  pdf(file.path(outdir, "funnel.pdf"), width = 6, height = 6)
  if (k >= 10) funnel(re_fit, refline = 0, main = "Funnel plot") else
    plot.new()
  dev.off()
}

cat(paste(lines, collapse = "\n"), "\n")
written <- file.path(outdir, c("summary.txt", "results.json", "sessionInfo.txt"))
if (!is.null(worklist_path)) written <- c(written, worklist_path)
cat("\nWrote:", paste(written, collapse = ", "), "\n")

