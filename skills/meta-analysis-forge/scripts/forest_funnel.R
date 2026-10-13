#!/usr/bin/env Rscript
# Publication-grade forest and funnel plots following Cochrane Handbook III.S1.
#
# Conventions applied: log scale for ratio measures; study + estimate + CI columns;
# pooled diamond; model and heterogeneity stated in the caption; funnel only
# interpreted at k >= 10; contour-enhanced funnel for the p=0.10/0.05/0.01 regions.
#
# Usage:
#   Rscript forest_funnel.R --input sheet.csv --outdir figs \
#       [--metric OR|RR|HR|MD|SMD] [--tau2 REML] [--width 8] [--height 0]
#
# Outputs: forest.pdf, funnel.pdf (if k>=10), caption.txt
# Every plotted number comes from the fitted model -- nothing is hand-entered.

suppressPackageStartupMessages(library(metafor))
args <- commandArgs(trailingOnly = TRUE)
g <- function(f, d = NULL) { i <- match(f, args); if (is.na(i) || i == length(args)) d else args[[i + 1]] }
input  <- g("--input"); outdir <- g("--outdir", "figs")
metric <- g("--metric"); tau2 <- g("--tau2", "REML")
width  <- as.numeric(g("--width", "9")); height <- as.numeric(g("--height", "0"))
if (is.null(input)) stop("Provide --input <coding-sheet.csv>")
if (!file.exists(input)) {
  ## A file that could not be read is an input condition, not a finding about the
  ## analysis: exit 4 (insufficient_input).
  cat("Error: Provide --input <coding-sheet.csv>\n", file = stderr())
  quit(save = "no", status = 4)
}
dir.create(outdir, recursive = TRUE, showWarnings = FALSE)

d <- read.csv(input, stringsAsFactors = FALSE, na.strings = c("", "NA", "N/A"))
if (!all(c("study_id","estimate","se","effect_metric") %in% names(d)))
  stop("Sheet needs study_id, effect_metric, estimate, se")
if (!is.null(metric)) d <- d[toupper(d$effect_metric) == toupper(metric), , drop = FALSE]

## ---- input condition: rows supplied vs rows usable -----------------------
## The invariant (docs/EVIDENCE-INVARIANT.md): the analysis of the rows that
## happened to be usable must never be presented as the analysis of the rows
## supplied. Count them, name every row we cannot use and why, and refuse by
## default. --allow-incomplete is the documented opt-out; it still writes the
## worklist and still prints the condition, so the override is logged, not silent.
allow_incomplete <- "--allow-incomplete" %in% args
rows_in <- nrow(d)
est_raw <- d$estimate
se_raw  <- d$se
est_num <- suppressWarnings(as.numeric(est_raw))
se_num  <- suppressWarnings(as.numeric(se_raw))
usable  <- is.finite(est_num) & is.finite(se_num) & se_num > 0
effect_ids <- if ("effect_id" %in% names(d)) as.character(d$effect_id) else as.character(seq_len(nrow(d)))

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
    row = i, study_id = as.character(d$study_id[i]), effect_id = effect_ids[i],
    reason = drop_reason(est_raw[i], se_raw[i], est_num[i], se_num[i]),
    stringsAsFactors = FALSE))
}
d <- d[usable, , drop = FALSE]
d$estimate <- est_num[usable]
d$se <- se_num[usable]
rows_out <- nrow(d)

jstr <- function(x) paste0('"', gsub('"', '\\\\"', as.character(x)), '"')
if (nrow(dropped) > 0) {
  items <- vapply(seq_len(nrow(dropped)), function(i) {
    paste0("{", paste(c(sprintf('"row": %s', jstr(dropped$row[i])),
                        sprintf('"study_id": %s', jstr(dropped$study_id[i])),
                        sprintf('"effect_id": %s', jstr(dropped$effect_id[i])),
                        sprintf('"reason": %s', jstr(dropped$reason[i]))),
                  collapse = ", "), "}")
  }, character(1))
  worklist_path <- file.path(outdir, "worklist.json")
  writeLines(paste0("{\n",
    '  "status": "insufficient_evidence",\n',
    sprintf('  "rows_in": %s,\n', jstr(rows_in)),
    sprintf('  "rows_out": %s,\n', jstr(rows_out)),
    sprintf('  "dropped_count": %s,\n', jstr(nrow(dropped))),
    '  "dropped": [', paste(items, collapse = ", "), "]\n}\n"), worklist_path)
  cat(sprintf(paste0("INPUT CONDITION: insufficient_evidence -- %d of %d supplied row(s) ",
                     "could not be used; any estimate below covers only the %d usable row(s).\n"),
              nrow(dropped), rows_in, rows_out))
  cat(sprintf("  dropped: %s\n",
              paste(sprintf("%s (%s)", dropped$study_id, dropped$reason), collapse = "; ")))
  cat(sprintf("  worklist: %s\n", normalizePath(worklist_path, winslash = "/", mustWork = FALSE)))
}

if (nrow(d) < 2) stop("Fewer than 2 usable effects.")

if (nrow(dropped) > 0) {
  if (!allow_incomplete) {
    cat("  Refusing to present a pooled estimate over a subset of the supplied rows.\n")
    cat(paste0("  Pass --allow-incomplete to pool the usable rows anyway (the worklist is ",
               "still written and this condition still reported).\n"))
    quit(save = "no", status = 3)
  }
  cat("  --allow-incomplete: pooling the usable rows; the input condition stands.\n")
}
metric <- toupper(d$effect_metric[1])
is_ratio <- metric %in% c("OR","RR","HR","IRR")

es <- escalc(measure = "GEN", yi = estimate, vi = se^2, data = d)
res <- rma(yi, vi, data = es, method = tau2)
pi <- tryCatch(predict(res), error = function(e) NULL)

# ---- forest --------------------------------------------------------------
d <- d[order(d$estimate), , drop = FALSE]
es <- escalc(measure = "GEN", yi = estimate, vi = se^2, data = d)
res <- rma(yi, vi, data = es, method = tau2)

h <- if (height > 0) height else max(4, 0.34 * nrow(d) + 2.6)
pdf(file.path(outdir, "forest.pdf"), width = width, height = h)
forest(res,
       atransf = if (is_ratio) exp else NULL,
       at = if (is_ratio) log(c(0.1, 0.25, 0.5, 1, 2, 4, 10)) else NULL,
       refline = if (is_ratio) 0 else 0,   # log scale: refline at 0 == OR/RR 1
       slab = paste(d$study_id, if ("year" %in% names(d)) d$year else "", sep = " "),
       header = c("Study", if (is_ratio) "OR/RR [95% CI]" else "Estimate [95% CI]"),
       xlab = paste0(if (is_ratio) paste0(metric, " (log scale)") else metric,
                     " -- ", tau2, " random effects"),
       mlab = sprintf("Random-effects %s = %s (%s)", metric,
                      if (is_ratio) sprintf("%.2f", exp(res$b)) else sprintf("%.3f", res$b),
                      if (is_ratio) sprintf("%.2f to %.2f", exp(res$ci.lb), exp(res$ci.ub))
                        else sprintf("%.3f to %.3f", res$ci.lb, res$ci.ub)),
       cex = 0.9, col = "darkblue")
dev.off()

# ---- funnel (Handbook ch.13: interpret only at k >= 10) ------------------
k <- res$k
have_funnel <- k >= 10
if (have_funnel) {
  pdf(file.path(outdir, "funnel.pdf"), width = 7, height = 7)
  funnel(res, refline = 0, level = c(90, 95, 99), shade = c("white","gray90","gray75"),
         legend = TRUE, main = "Contour-enhanced funnel plot",
         xlab = paste0(metric, " (log scale, if ratio)"))
  dev.off()
}

# ---- caption (self-contained, states the model) --------------------------
cap <- c(
  sprintf("Figure. Forest plot of %s across %d studies.", metric, k),
  sprintf("Effect measure: %s%s. Model: %s random-effects (tau^2 estimator %s).",
          metric, if (is_ratio) " on the log scale, back-transformed for display" else "",
          tau2, tau2),
  sprintf("Pooled %s = %s (95%% CI %s), p = %.4g.",
          metric,
          if (is_ratio) sprintf("%.2f", exp(res$b)) else sprintf("%.3f", res$b),
          if (is_ratio) sprintf("%.2f to %.2f", exp(res$ci.lb), exp(res$ci.ub))
            else sprintf("%.3f to %.3f", res$ci.lb, res$ci.ub),
          res$pval),
  if (res$QE > res$k - 1)
    sprintf("Heterogeneity: tau^2 = %.4f; I^2 = %.1f%%; Q = %.2f (df = %d, p = %.4g).",
            res$tau2, res$I2, res$QE, res$k - 1, res$QEp)
  else
    "Heterogeneity: not estimable (QE <= df).",
  if (!is.null(pi)) sprintf("Prediction interval: %s.",
          if (is_ratio) sprintf("%.2f to %.2f", exp(pi$pi.lb), exp(pi$pi.ub))
            else sprintf("%.3f to %.3f", pi$pi.lb, pi$pi.ub)) else NULL,
  if (!have_funnel) sprintf("Funnel plot omitted: k = %d < 10 (Handbook ch.13).", k)
    else "Funnel plot (contour-enhanced) shown; asymmetry is not proof of publication bias."
)
writeLines(cap[!vapply(cap, is.null, logical(1))], file.path(outdir, "caption.txt"))
cat(paste(cap[!vapply(cap, is.null, logical(1))], collapse = "\n"), "\n")
cat("\nWrote:", file.path(outdir, "forest.pdf"),
    if (have_funnel) file.path(outdir, "funnel.pdf") else "(no funnel: k<10)",
    file.path(outdir, "caption.txt"), "\n")
