#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)

usage <- function() {
  cat(
    "Usage:\n",
    "  Rscript run_meta_analysis.R --input coding-sheet.csv --outdir output [--metric SMD]\n\n",
    "Required input columns:\n",
    "  study_id, effect_id, effect_metric, estimate, se\n\n",
    "Outputs:\n",
    "  meta-summary.txt, model-results.csv, forest-plot.pdf, funnel-plot.pdf\n",
    sep = ""
  )
}

get_arg <- function(flag, default = NULL) {
  idx <- match(flag, args)
  if (is.na(idx) || idx == length(args)) {
    return(default)
  }
  args[[idx + 1]]
}

input_path <- get_arg("--input")
out_dir <- get_arg("--outdir", "meta_output")
metric_filter <- get_arg("--metric")

if (is.null(input_path)) {
  usage()
  stop("Missing --input.", call. = FALSE)
}

if (!requireNamespace("metafor", quietly = TRUE)) {
  stop("Package 'metafor' is required. Install it with install.packages('metafor').", call. = FALSE)
}

if (!file.exists(input_path)) {
  ## A file that could not be read is an input condition, not a finding about the
  ## analysis: exit 4 (insufficient_input).
  cat(paste0("Error: Input file not found: ", input_path, "\n"), file = stderr())
  quit(save = "no", status = 4)
}

dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

dat <- read.csv(input_path, stringsAsFactors = FALSE, na.strings = c("", "NA", "N/A"))
required <- c("study_id", "effect_id", "effect_metric", "estimate", "se")
missing <- setdiff(required, names(dat))

if (length(missing) > 0) {
  stop(paste("Missing required columns:", paste(missing, collapse = ", ")), call. = FALSE)
}

if (!is.null(metric_filter)) {
  dat <- dat[dat$effect_metric == metric_filter, , drop = FALSE]
}

## ---- input condition: rows supplied vs rows usable -----------------------
## The invariant (docs/EVIDENCE-INVARIANT.md): the analysis of the rows that
## happened to be usable must never be presented as the analysis of the rows
## supplied. Count them, name every row we cannot use and why, and refuse by
## default. --allow-incomplete is the documented opt-out; it still writes the
## worklist and still prints the condition, so the override is logged, not silent.
allow_incomplete <- "--allow-incomplete" %in% args
rows_in <- nrow(dat)
est_raw <- dat$estimate
se_raw  <- dat$se
dat$estimate <- suppressWarnings(as.numeric(dat$estimate))
dat$se <- suppressWarnings(as.numeric(dat$se))
usable <- is.finite(dat$estimate) & is.finite(dat$se) & dat$se > 0

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
    reason = drop_reason(est_raw[i], se_raw[i], dat$estimate[i], dat$se[i]),
    stringsAsFactors = FALSE))
}
dat <- dat[usable, , drop = FALSE]
rows_out <- nrow(dat)

jstr <- function(x) paste0('"', gsub('"', '\\\\"', as.character(x)), '"')
if (nrow(dropped) > 0) {
  items <- vapply(seq_len(nrow(dropped)), function(i) {
    paste0("{", paste(c(sprintf('"row": %s', jstr(dropped$row[i])),
                        sprintf('"study_id": %s', jstr(dropped$study_id[i])),
                        sprintf('"effect_id": %s', jstr(dropped$effect_id[i])),
                        sprintf('"reason": %s', jstr(dropped$reason[i]))),
                  collapse = ", "), "}")
  }, character(1))
  worklist_path <- file.path(out_dir, "worklist.json")
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

if (nrow(dat) < 2) {
  stop("At least two valid effects with positive standard errors are required.", call. = FALSE)
}

if (nrow(dropped) > 0) {
  if (!allow_incomplete) {
    cat("  Refusing to present a pooled estimate over a subset of the supplied rows.\n")
    cat(paste0("  Pass --allow-incomplete to pool the usable rows anyway (the worklist is ",
               "still written and this condition still reported).\n"))
    quit(save = "no", status = 3)
  }
  cat("  --allow-incomplete: pooling the usable rows; the input condition stands.\n")
}

metric_values <- unique(dat$effect_metric)
if (length(metric_values) > 1) {
  stop(
    paste(
      "Multiple effect metrics found:",
      paste(metric_values, collapse = ", "),
      "- filter with --metric or harmonize before pooling."
    ),
    call. = FALSE
  )
}

dat$vi <- dat$se^2
model <- metafor::rma.uni(yi = estimate, vi = vi, data = dat, method = "REML")

summary_path <- file.path(out_dir, "meta-summary.txt")
sink(summary_path)
cat("EvidenceForge minimal meta-analysis run\n")
cat("=======================================\n\n")
cat("Input:", normalizePath(input_path, winslash = "/", mustWork = FALSE), "\n")
cat("Effects included:", nrow(dat), "\n")
cat("Studies represented:", length(unique(dat$study_id)), "\n")
cat("Effect metric:", metric_values[[1]], "\n\n")
print(summary(model))
cat("\nQuality notes:\n")
cat("- This script assumes the input effects are already comparable.\n")
cat("- It does not solve within-study dependence; inspect dependency_group before relying on pooled results.\n")
cat("- Risk of bias and certainty judgments remain human review tasks.\n")
sink()

results <- data.frame(
  effect_metric = metric_values[[1]],
  k = model$k,
  estimate = as.numeric(model$b[1]),
  se = model$se,
  ci_low = model$ci.lb,
  ci_high = model$ci.ub,
  tau2 = model$tau2,
  I2 = model$I2,
  H2 = model$H2,
  p_value = model$pval,
  stringsAsFactors = FALSE
)

write.csv(results, file.path(out_dir, "model-results.csv"), row.names = FALSE)

pdf(file.path(out_dir, "forest-plot.pdf"), width = 8, height = 6)
metafor::forest(model, slab = paste(dat$study_id, dat$effect_id, sep = ":"))
dev.off()

pdf(file.path(out_dir, "funnel-plot.pdf"), width = 7, height = 6)
metafor::funnel(model)
dev.off()

cat("Wrote outputs to:", normalizePath(out_dir, winslash = "/", mustWork = FALSE), "\n")
