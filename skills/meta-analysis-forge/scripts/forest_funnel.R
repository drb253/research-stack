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
if (is.null(input) || !file.exists(input)) stop("Provide --input <coding-sheet.csv>")
dir.create(outdir, recursive = TRUE, showWarnings = FALSE)

d <- read.csv(input, stringsAsFactors = FALSE, na.strings = c("", "NA", "N/A"))
if (!all(c("study_id","estimate","se","effect_metric") %in% names(d)))
  stop("Sheet needs study_id, effect_metric, estimate, se")
if (!is.null(metric)) d <- d[toupper(d$effect_metric) == toupper(metric), , drop = FALSE]
d <- d[is.finite(d$estimate) & is.finite(d$se) & d$se > 0, , drop = FALSE]
if (nrow(d) < 2) stop("Fewer than 2 usable effects.")
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
  sprintf("Heterogeneity: tau^2 = %.4f; I^2 = %.1f%%; Q = %.2f (df = %d, p = %.4g).",
          res$tau2, res$I2, res$QE, res$k - 1, res$QEp),
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
