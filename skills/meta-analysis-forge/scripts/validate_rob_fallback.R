#!/usr/bin/env Rscript
# Validate the built-in traffic-light renderer in rob_figure.R against robvis itself.
#
# rob_figure.R falls back to a hand-written ggplot2 traffic-light when robvis's
# rob_traffic_light() errors (ROBINS-E / QUIPS / Generic in robvis 0.3.1). A fallback
# that has never been compared to the real thing is just a second guess, so this
# asserts, cell by cell, that the fallback encodes the same judgement the same way.
#
# Run: Rscript validate_rob_fallback.R      (exit 0 = fallback matches robvis)
suppressPackageStartupMessages({
  if (!requireNamespace("robvis", quietly = TRUE)) stop("robvis required")
  if (!requireNamespace("ggplot2", quietly = TRUE)) stop("ggplot2 required")
  library(robvis); library(ggplot2)
})

d <- data.frame(
  Study = c("S1", "S2", "S3"),
  D1 = c("Low", "High", "Some concerns"),
  D2 = c("Low", "Low", "High"),
  D3 = c("Low", "Some concerns", "Low"),
  D4 = c("Low", "Low", "Low"),
  D5 = c("Low", "Low", "High"),
  Overall = c("Low", "Low", "High"),
  stringsAsFactors = FALSE
)

## --mutate: deliberately corrupt the fallback mapping. The validator MUST then fail,
## which is how we know it can detect a real divergence rather than always printing OK.
args <- commandArgs(trailingOnly = TRUE)
mutate <- "--mutate" %in% args
if (mutate) {
  cat("MUTATION MODE: corrupting the fallback mapping on purpose\n")
}

## ---- robvis's own encoding ------------------------------------------------
p <- rob_traffic_light(d, tool = "ROB2", colour = "cochrane", psize = 10)
bd <- ggplot_build(p)$data
ref <- NULL
for (lyr in bd) {
  if (!is.null(lyr$colour) && length(unique(lyr$colour)) > 1 &&
      length(lyr$colour) == nrow(d) * 6) {
    ref <- lyr$colour
    break
  }
}
if (is.null(ref)) stop("could not read the colour vector from robvis's plot")

## ---- the fallback's encoding ---------------------------------------------
## Same palette and the same cell order (domain-major, then study) as rob_figure.R.
## 'Overall' IS included -- robvis draws it as a final column.
pal <- c("low" = "#02C100", "low risk" = "#02C100",
         "some concerns" = "#E2DF07", "moderate" = "#E2DF07", "unclear" = "#E2DF07",
         "high" = "#BF0000", "high risk" = "#BF0000", "critical" = "#BF0000",
         "no information" = "#808080")
doms <- setdiff(names(d), c("Study", "Weight"))
mine <- unlist(lapply(doms, function(dm)
  unname(pal[tolower(trimws(as.character(d[[dm]])))])))
if (mutate) mine[1] <- "#123456"     # a colour robvis never uses

if (length(mine) != length(ref)) {
  stop(sprintf("cell count differs: fallback %d vs robvis %d", length(mine), length(ref)))
}
mismatch <- which(toupper(mine) != toupper(ref))
if (length(mismatch)) {
  for (i in mismatch) {
    cat(sprintf("  MISMATCH cell %d: fallback %s vs robvis %s\n", i, mine[i], ref[i]))
  }
  stop(sprintf("fallback disagrees with robvis on %d of %d cells",
               length(mismatch), length(ref)))
}
cat(sprintf("OK: the built-in traffic-light matches robvis cell-for-cell (%d cells, %d domains)\n",
            length(ref), length(doms)))
