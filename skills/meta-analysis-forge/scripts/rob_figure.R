#!/usr/bin/env Rscript
# Risk-of-bias figures (traffic-light + summary) via robvis (MIT).
#
# Usage:
#   Rscript rob_figure.R --input rob.csv --outdir figs --tool ROB2 [--palette cochrane]
#
# Input: one row per study.
#   * The study-id column must be named 'Study' (also accepted and normalised:
#     study / study_id / studyid / id) -- robvis requires the exact name.
#   * Then one column per domain, named as robvis expects for the tool
#     (D1, D2, ...), plus an optional 'Overall' column.
#   * 'Weight' is optional: if a numeric Weight column is present it weights the
#     summary bar; if absent the summary is drawn unweighted (robvis otherwise
#     refuses with "number of columns < 8").
# Cell values: Low / Some concerns / High (+, ?, - also accepted; ROBINS-I uses
# Low / Moderate / High / Critical / No information).
#
# Domain columns robvis expects (taken from its own example datasets):
#   ROB2 / ROB2-Cluster  D1..D5 ;  QUADAS-2  D1..D4 ;  ROBINS-I  D1..D7.
#
# Outputs: rob_traffic_light.pdf, rob_summary.pdf (only those actually produced).
# Fails loudly (non-zero exit) if a requested figure cannot be written -- a figure
# that failed must never be reported as written.
#
# robvis supports: ROB2, ROB2-Cluster, ROBINS-I, ROBINS-E, QUADAS-2, QUIPS, Generic.
# Known upstream limitation (robvis 0.3.1): rob_traffic_light() is broken for
# ROBINS-E, QUIPS and Generic -- it errors with "object 'trafficlightplot' not
# found" for any input. This script detects that failure and falls back to a
# built-in ggplot2 traffic-light renderer, so those tools still get a figure; the
# fallback is announced on stdout. An unwritten figure is never reported as written.

suppressPackageStartupMessages({
  if (!requireNamespace("robvis", quietly = TRUE)) stop("Package 'robvis' required.")
  library(robvis)
})
args <- commandArgs(trailingOnly = TRUE)
g <- function(f, d = NULL) { i <- match(f, args); if (is.na(i) || i == length(args)) d else args[[i + 1]] }
input  <- g("--input"); outdir <- g("--outdir", "figs")
tool   <- g("--tool", "ROB2"); palette <- g("--palette", "cochrane")
if (is.null(input) || !file.exists(input)) stop("Provide --input <rob.csv>")
dir.create(outdir, recursive = TRUE, showWarnings = FALSE)

d <- read.csv(input, stringsAsFactors = FALSE, check.names = FALSE)
valid <- c("ROB2","ROB2-Cluster","ROBINS-I","ROBINS-E","QUADAS-2","QUIPS","Generic")
if (!tool %in% valid) stop(sprintf("--tool must be one of: %s", paste(valid, collapse = ", ")))

## robvis requires the study-id column to be named exactly 'Study'; normalise the
## common spellings rather than letting robvis fail with an opaque error.
if (!"Study" %in% names(d)) {
  idx <- which(tolower(names(d)) %in% c("study", "study_id", "studyid", "id"))
  if (length(idx) >= 1L) names(d)[idx[1L]] <- "Study"
}
if (!"Study" %in% names(d))
  stop(sprintf("No study-id column found. Name it 'Study' (columns present: %s).",
               paste(names(d), collapse = ", ")), call. = FALSE)

## Fail early, with a legible message, when the domain columns robvis needs are
## absent -- robvis otherwise reports an opaque "subscript out of bounds".
req <- switch(tool,
    "ROB2" = c("Study", paste0("D", 1:5)),
    "QUADAS-2" = c("Study", paste0("D", 1:4)),
    "ROBINS-I" = c("Study", paste0("D", 1:7))
  )
if (!is.null(req)) {
  miss <- setdiff(req, names(d))
  if (length(miss))
    stop(sprintf("tool=%s needs column(s) %s (have: %s).",
                 tool, paste(miss, collapse = ", "), paste(names(d), collapse = ", ")),
         call. = FALSE)
}

## rob_summary() needs a 'Weight' column unless weighted = FALSE; use weights only
## when a genuinely numeric Weight column is present.
has_weight <- "Weight" %in% names(d) &&
  any(is.finite(suppressWarnings(as.numeric(d$Weight))))

## ---- built-in traffic-light renderer -------------------------------------
## robvis 0.3.1's rob_traffic_light() is broken for ROBINS-E / QUIPS / Generic
## (its internal 'trafficlightplot' object is never created). Rather than leave
## those tools without a figure, draw the equivalent traffic-light natively:
## one row per study, one column per domain, coloured by judgement.
native_traffic_light <- function(d, palette = "cochrane") {
  if (!requireNamespace("ggplot2", quietly = TRUE)) return(NULL)
  ## Include the 'Overall' column: robvis draws it as a final column of the traffic
  ## light, and omitting it silently loses the summary judgement for every study.
  ## validate_rob_fallback.R asserts this cell-for-cell against robvis.
  doms <- setdiff(names(d), c("Study", "Weight"))
  if (!length(doms) || !nrow(d)) return(NULL)
  pal <- c("low" = "#02C100", "low risk" = "#02C100",
           "some concerns" = "#E2DF07", "moderate" = "#E2DF07", "unclear" = "#E2DF07",
           "high" = "#BF0000", "high risk" = "#BF0000", "critical" = "#BF0000",
           "no information" = "#808080")
  long <- do.call(rbind, lapply(doms, function(dm) data.frame(
    Study = as.character(d$Study), Domain = dm,
    Judgement = as.character(d[[dm]]), stringsAsFactors = FALSE)))
  long$col <- unname(pal[tolower(trimws(long$Judgement))])
  long$col[is.na(long$col)] <- "#808080"
  long$Study <- factor(long$Study, levels = rev(unique(long$Study)))
  ggplot2::ggplot(long, ggplot2::aes(x = Domain, y = Study, colour = col)) +
    ggplot2::geom_point(shape = 15, size = 9) +
    ggplot2::scale_colour_identity() +
    ggplot2::labs(x = NULL, y = NULL) +
    ggplot2::theme_minimal(base_size = 11) +
    ggplot2::theme(panel.grid = ggplot2::element_blank(),
                   axis.text.x = ggplot2::element_text(angle = 30, hjust = 1))
}

tl <- tryCatch(rob_traffic_light(d, tool = tool, psize = 10, colour = palette),
               error = function(e) structure(conditionMessage(e), class = "rob_err"))
if (inherits(tl, "rob_err")) {
  native <- native_traffic_light(d, palette)
  if (!is.null(native)) {
    cat(sprintf("NOTE: robvis rob_traffic_light() failed for tool=%s (%s);\n      using the built-in traffic-light renderer instead.\n",
                tool, as.character(tl)))
    tl <- native
  }
}
sm <- tryCatch(rob_summary(d, tool = tool, colour = palette, weighted = has_weight),
               error = function(e) structure(conditionMessage(e), class = "rob_err"))

written <- character(0)
failed  <- character(0)
unsupported <- character(0)

save_rob <- function(p, name) {
  path <- file.path(outdir, name)
  if (inherits(p, "rob_unsupported")) {
    unsupported <<- c(unsupported, sprintf("%s (%s)", name, as.character(p)))
    return(invisible(FALSE))
  }
  if (inherits(p, "rob_err")) {
    failed <<- c(failed, sprintf("%s (%s)", name, as.character(p)))
    return(invisible(FALSE))
  }
  ok <- tryCatch({
    grDevices::pdf(path, width = 9, height = max(3, 0.32 * nrow(d) + 2))
    print(p)
    grDevices::dev.off()
    file.exists(path)
  }, error = function(e) {
    try(grDevices::dev.off(), silent = TRUE)
    conditionMessage(e)
  })
  if (isTRUE(ok)) { written <<- c(written, path); return(invisible(TRUE)) }
  failed <<- c(failed, sprintf("%s (%s)", name, as.character(ok)))
  invisible(FALSE)
}

save_rob(tl, "rob_traffic_light.pdf")
save_rob(sm, "rob_summary.pdf")

if (length(written))
  cat(sprintf("RoB figures written (tool=%s, palette=%s, weighted=%s):\n%s\n",
              tool, palette, has_weight, paste0("  ", written, collapse = "\n")))
if (length(unsupported))
  cat(sprintf("NOTE: %d figure(s) NOT produced -- unsupported by robvis %s for this tool:\n%s\n",
              length(unsupported), as.character(packageVersion("robvis")),
              paste0("  ", unsupported, collapse = "\n")))
if (length(failed))
  stop(sprintf("RoB figure(s) NOT written (%d): %s",
               length(failed), paste(failed, collapse = "; ")), call. = FALSE)
if (!length(unsupported) && length(written))
  cat("OK: all requested RoB figures written.\n")

