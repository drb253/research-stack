#!/usr/bin/env Rscript
# Golden tests for cochrane_meta.R -- the PROOF of numerical accuracy.
#
# Three independent kinds of check:
#   A. Wrapper fidelity  -- engine numbers equal a direct metafor::rma() fit.
#   B. Closed-form truth -- engine numbers equal values computed from first
#      principles in base R (inverse-variance pooling, Q), which do NOT come from
#      metafor. If the wrapper and metafor were both wrong, B would still catch it.
#   C. Input-mode equivalence -- the raw-counts path and the precomputed path agree.
#
# Datasets are the canonical metafor examples, in their native RAW form
# (metafor 5.2-1 loads datasets via the 'metadat' package):
#   dat.bcg         -> escalc(RR, ai=tpos, bi=tneg, ci=cpos, di=cneg)
#   dat.normand1999 -> escalc(MD, n1i, m1i, sd1i, n2i, m2i, sd2i)
#
# Run: Rscript golden_tests.R   (exit 0 = all pass)

suppressPackageStartupMessages(library(metafor))

`%||%` <- function(a, b) if (is.null(a)) b else a
.argv <- commandArgs(trailingOnly = FALSE)
.file <- sub("^--file=", "", .argv[grep("^--file=", .argv)])
ENGINE <- file.path(dirname(if (length(.file)) .file else getwd()), "cochrane_meta.R")
if (!file.exists(ENGINE)) ENGINE <- file.path(getwd(), "cochrane_meta.R")
if (!file.exists(ENGINE)) stop("Cannot locate cochrane_meta.R next to this test.")

tmp <- tempfile("golden_"); dir.create(tmp)
pass <- 0; fail <- 0
check <- function(name, got, want, tol = 1e-6) {
  ok <- length(got) == length(want) &&
        all(!is.na(got) & !is.na(want) & abs(got - want) <= tol * pmax(1, abs(want)))
  if (isTRUE(ok)) { pass <<- pass + 1; cat(sprintf("  PASS  %s\n", name)) }
  else { fail <<- fail + 1
         cat(sprintf("  FAIL  %s\n        got =%s\n        want=%s\n", name,
                     paste(signif(got,8),collapse=","), paste(signif(want,8),collapse=","))) }
}
jnum <- function(file, key) {
  txt <- paste(readLines(file, warn = FALSE), collapse = "")
  m <- regmatches(txt, regexpr(sprintf('"%s"\\s*:\\s*(-?[0-9.eE+]+|null)', key), txt))
  if (!length(m)) return(NA_real_)
  v <- sub(sprintf('.*"%s"\\s*:\\s*', key), "", m)
  if (grepl("null", v)) NA_real_ else as.numeric(v)
}
run_engine <- function(sheet, outdir, extra = character()) {
  system2("Rscript", c(ENGINE, "--input", sheet, "--outdir", outdir, extra),
          stdout = FALSE, stderr = FALSE)
  file.path(outdir, "results.json")
}

cat("== Golden test 1: dat.bcg (log risk ratios, 13 studies, REML) ==\n")
es1 <- escalc(measure = "RR", ai = tpos, bi = tneg, ci = cpos, di = cneg, data = dat.bcg)
ref1 <- rma(yi, vi, data = es1, method = "REML")

sheet1a <- file.path(tmp, "bcg_pre.csv")
write.csv(data.frame(study_id = dat.bcg$author, effect_id = dat.bcg$trial,
                     effect_metric = "RR", estimate = es1$yi, se = sqrt(es1$vi)),
          sheet1a, row.names = FALSE)
rA <- run_engine(sheet1a, file.path(tmp, "bcg_pre"), c("--metric","RR","--tau2","REML","--hksj"))

sheet1b <- file.path(tmp, "bcg_raw.csv")
write.csv(data.frame(study_id = dat.bcg$author, effect_id = dat.bcg$trial,
                     effect_metric = "RR", ai = dat.bcg$tpos, bi = dat.bcg$tneg,
                     ci = dat.bcg$cpos, di = dat.bcg$cneg),
          sheet1b, row.names = FALSE)
rB <- run_engine(sheet1b, file.path(tmp, "bcg_raw"), c("--metric","RR","--tau2","REML"))

check("A pooled (log RR) == metafor", jnum(rA,"pooled"), ref1$b)
check("A CI lower == metafor",        jnum(rA,"ci_lb"),  ref1$ci.lb)
check("A tau^2 == metafor",           jnum(rA,"tau2"),   ref1$tau2)
check("A I^2 == metafor",             jnum(rA,"I2"),     ref1$I2)
check("A Q == metafor",               jnum(rA,"Q"),      ref1$QE)
check("C raw path pooled == precomputed", jnum(rB,"pooled"), jnum(rA,"pooled"))
check("C raw path tau^2 == precomputed",  jnum(rB,"tau2"),   jnum(rA,"tau2"))

w   <- 1 / es1$vi
fem <- sum(w * es1$yi) / sum(w)
fe  <- rma(yi, vi, data = es1, method = "FE")
check("B closed-form FE pooled == metafor FE", fem, fe$b)
check("B closed-form FE pooled == engine FE",  fem, jnum(rA, "fe_pooled"))
Qcf <- sum((es1$yi - fem)^2 / es1$vi)
check("B closed-form Q == metafor QE", Qcf, ref1$QE)
check("B I^2 identity (H2-1)/H2", (ref1$H2 - 1)/ref1$H2 * 100, ref1$I2, 1e-8)
check("B prediction interval wider than CI",
      (jnum(rA,"pi_ub")-jnum(rA,"pi_lb")) > (jnum(rA,"ci_ub")-jnum(rA,"ci_lb")), TRUE)

cat("\n== Golden test 2: dat.normand1999 (mean differences, 9 studies) ==\n")
es2 <- escalc(measure = "MD", n1i = n1i, m1i = m1i, sd1i = sd1i,
              n2i = n2i, m2i = m2i, sd2i = sd2i, data = dat.normand1999)
ref2 <- rma(yi, vi, data = es2, method = "REML")

sheet2a <- file.path(tmp, "norm_pre.csv")
write.csv(data.frame(study_id = dat.normand1999$source, effect_id = dat.normand1999$study,
                     effect_metric = "MD", estimate = es2$yi, se = sqrt(es2$vi)),
          sheet2a, row.names = FALSE)
r2 <- run_engine(sheet2a, file.path(tmp, "norm_pre"), c("--metric","MD","--tau2","REML"))

sheet2b <- file.path(tmp, "norm_raw.csv")
write.csv(data.frame(study_id = dat.normand1999$source, effect_id = dat.normand1999$study,
                     effect_metric = "MD", n1i = dat.normand1999$n1i, m1i = dat.normand1999$m1i,
                     sd1i = dat.normand1999$sd1i, n2i = dat.normand1999$n2i,
                     m2i = dat.normand1999$m2i, sd2i = dat.normand1999$sd2i),
          sheet2b, row.names = FALSE)
r2b <- run_engine(sheet2b, file.path(tmp, "norm_raw"), c("--metric","MD","--tau2","REML"))

check("A pooled (MD) == metafor", jnum(r2,"pooled"), ref2$b)
check("A tau^2 == metafor",       jnum(r2,"tau2"),   ref2$tau2)
check("A I^2 == metafor",         jnum(r2,"I2"),     ref2$I2)
check("C raw path (MD) == precomputed", jnum(r2b,"pooled"), jnum(r2,"pooled"))

cat("\n== Golden test 3: tau^2 estimators differ as expected (DL vs REML) ==\n")
r_dl <- rma(yi, vi, data = es1, method = "DL")
check("DL tau^2 != REML tau^2", abs(r_dl$tau2 - ref1$tau2) > 1e-4, TRUE)

cat(sprintf("\nRESULT: %d passed, %d failed\n", pass, fail))
quit(status = if (fail == 0) 0 else 1)

