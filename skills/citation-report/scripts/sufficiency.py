"""Sufficiency: decide whether the inputs can support the findings at all.

This module exists because of a real failure. A 1,027-sentence document was graded
against 62 identified sources while holding readable evidence for **none** of them,
and the run reported `0/371 = 0.0%` in the same shape as a run that had checked every
sentence. Zero percent is a statement about *our inputs* printed where a statement
about *the document* belongs, and a reader cannot tell the two apart.

The fix is not a better number. It is a separate channel:

* A missing input is reported as `insufficient_evidence` or `insufficient_input`,
  never as a coverage figure a reader could mistake for a result.
* It **blocks by default** (exit 3 or 4). `--allow-insufficient` is the documented
  opt-out, and it keeps the status in the JSON so the opt-out is logged, not silent.
* It produces a **worklist**: one row per source we could not read, with the reason
  and the affected sentences, which is the artefact that closes the loop. Drop the
  files in, re-run, and the gaps close.

Two policies are offered. `strict` (the default) requires every source the document
actually cites to be checkable. A share threshold is available for teams that prefer
one, but it is not the default: a report that checked 90% of its citations and says
"pass" is exactly the reassurance this repository refuses to give.
"""

from __future__ import annotations

from pathlib import Path

import _common

WORKLIST_COLUMNS = (
    "source_id",
    "citation_number",
    "citekey",
    "doi",
    "pmid",
    "title",
    "sentences_referencing",
    "sentences_needing_evidence",
    "retrieval_status",
    "evidence_strength",
    "evidence_availability",
    "attempts",
    "reason",
    "suggested_action",
    "worklist_key",
    "resolved",
)


def evaluate(verdicts, summary, bundle, *, policy: str = "strict", share: float = 1.0,
             transcription: dict | None = None) -> dict:
    """Decide the run's status from the input side, and build the worklist.

    Returns a dict with `status` (one of the run statuses), `blocking` (bool), the
    counts that justify it, the per-source worklist rows, and a human-readable
    `reason` list. It never decides anything about the *document*: findings are the
    classifier's business, and conflating the two is the failure this module exists to
    prevent.

    `transcription` carries how many sentences rest on OCR. A transcription is weaker
    evidence than a text layer -- it is a machine's reading of an image -- so by default it
    makes the run input-bound, and `--allow-insufficient` is how a caller proceeds anyway.
    """
    result = _evaluate_base(verdicts, summary, bundle, policy=policy, share=share)
    return _apply_transcription_policy(result, transcription)


def _apply_transcription_policy(result: dict, transcription: dict | None) -> dict:
    """A run whose evidence came from OCR is input-bound unless the caller says otherwise.

    The rule the OCR tier is built on is that a transcription may never *convict* (rule
    D13). This is the other half: it may not be presented as if it were a text layer
    either. A reader comparing a green coverage figure across two documents should be able
    to tell that one of them was read by a machine, and a gate that treats "read" and
    "transcribed" as the same input is the confusion this module exists to prevent.

    A run already input-bound for missing evidence keeps its status; the transcription
    reason is added to the list so the banner says both things.
    """
    count = int((transcription or {}).get("sentences_resting_on_ocr") or 0)
    if not count:
        return result
    engine = (transcription or {}).get("document_transcription") or "OCR"
    reason = (
        "%d sentence(s) rest on an OCR transcription (%s) rather than on the document's "
        "own text layer, so the evidence behind them is a machine's reading" % (count, engine)
    )
    updated = dict(result)
    updated["transcription_sentences"] = count
    if result.get("blocking"):
        updated["reason"] = list(result.get("reason") or []) + [reason]
        return updated
    updated.update(
        {
            "status": "insufficient_evidence",
            "blocking": True,
            "reason": [reason],
            "detail": "the document or its evidence was read by OCR, not from a text layer",
        }
    )
    return updated


def _evaluate_base(verdicts, summary, bundle, *, policy: str = "strict", share: float = 1.0) -> dict:
    """The evidence assessment itself, before the transcription policy is applied."""
    by_id = {source.source_id: source for source in bundle.sources}
    cited: dict = {}
    for verdict in verdicts:
        for record in verdict.sources:
            source_id = record.get("source_id")
            if not source_id:
                continue
            entry = cited.setdefault(
                source_id,
                {
                    "sentences": 0,
                    "needing_evidence": 0,
                    "sentence_ids": [],
                    "numeric_sentence_ids": [],
                },
            )
            entry["sentences"] += 1
            entry["sentence_ids"].append(verdict.sentence_id)
            # A sentence only *needs* evidence if it asserts something checkable. A
            # cited conclusion that carries no number can still be reported as
            # synthesis without any source text, so it must not inflate the gap.
            if verdict.requires_citation and verdict.quantities:
                entry["needing_evidence"] += 1
                entry["numeric_sentence_ids"].append(verdict.sentence_id)

    checkable = []
    unreadable = []
    for source_id, entry in sorted(cited.items()):
        source = by_id.get(source_id)
        if source is not None and source.checkable:
            checkable.append(source_id)
        else:
            unreadable.append((source_id, entry, source))

    total = len(cited)
    if total == 0:
        return {
            "status": "pass",
            "blocking": False,
            "policy": policy,
            "share_required": share,
            "citing_sources": 0,
            "citing_sources_checkable": 0,
            "unverifiable_sentences": 0,
            "undecided_sentences": 0,
            "worklist": [],
            "reason": [],
            "detail": "no sentence in this document resolves to a source, so there is "
            "no evidence to require",
        }

    required = total if policy == "strict" else max(1, int(round(total * share)))
    decided = len(checkable)
    undecided_sentences = sum(entry["needing_evidence"] for _, entry, _ in unreadable)
    unverifiable_sentences = sum(entry["sentences"] for _, entry, _ in unreadable)

    rows = [
        _worklist_row(source_id, entry, source)
        for source_id, entry, source in unreadable
    ]

    reasons: list = []
    if decided < required:
        reasons.append(
            "%d of %d cited source(s) have no readable evidence, and the policy "
            "requires %d" % (total - decided, total, required)
        )
        transient = sum(
            1 for row in rows if "lookup failed" in (row.get("reason") or "")
        )
        if transient:
            # Leading with "supply the files" when the failures were transient sends a
            # user hunting for papers that a retry would obtain.
            reasons.append(
                "%d of those failed transiently rather than being absent from the "
                "literature; retry before supplying files" % transient
            )
        if unverifiable_sentences:
            reasons.append(
                "%d sentence(s) cite those sources and could not be verified%s"
                % (
                    unverifiable_sentences,
                    (
                        "; %d of them assert a checkable value" % undecided_sentences
                        if undecided_sentences
                        else "; none of them assert a checkable value, so supplying the "
                        "sources would move them from `unverifiable` to `synthesis` "
                        "rather than to a checked result"
                    ),
                )
            )
        reasons.append(
            "supply the missing sources (see the worklist), or pass "
            "--allow-insufficient to proceed without them"
        )
        return {
            "status": "insufficient_evidence",
            "blocking": True,
            "policy": policy,
            "share_required": share,
            "citing_sources": total,
            "citing_sources_checkable": decided,
            "unverifiable_sentences": unverifiable_sentences,
            "undecided_sentences": undecided_sentences,
            "worklist": rows,
            "reason": reasons,
            "detail": "the document was readable; the sources were not",
        }

    return {
        "status": "pass",
        "blocking": False,
        "policy": policy,
        "share_required": share,
        "citing_sources": total,
        "citing_sources_checkable": decided,
        "unverifiable_sentences": unverifiable_sentences,
        "undecided_sentences": undecided_sentences,
        "worklist": rows,
        "reason": [],
        "detail": "every cited source has evidence strong enough to check it",
    }


def _worklist_row(source_id: str, entry: dict, source) -> dict:
    """One row per source we could not read, phrased as something to act on.

    The instruction depends on *why* the source is unreadable. A transient lookup
    failure is retried; a genuinely unavailable source needs a file from the user.
    Telling someone to go and find sixty PDFs because an API returned 503 is a false
    instruction, and it is the same class of error as reporting a gap as a finding.
    """
    if source is None:
        return {
            "source_id": source_id,
            "citation_number": "",
            "citekey": "",
            "doi": "",
            "pmid": "",
            "title": "",
            "sentences_referencing": entry["sentences"],
            "sentences_needing_evidence": entry["needing_evidence"],
            "retrieval_status": "error",
            "evidence_strength": "none",
            "evidence_availability": "unavailable",
            "attempts": "",
            "reason": "the citation resolved to a source id that is not in the registry",
            "suggested_action": "re-run without --verdicts so the registry is rebuilt",
            "worklist_key": source_id,
            "resolved": "no",
        }

    attempts = "; ".join(
        "%s %s=%s" % (item.get("method", "?"), item.get("endpoint", "?")[:60], item.get("retrieval_status", "?"))
        for item in source.attempts[-4:]
    )
    failures = [
        item for item in source.attempts if item.get("retrieval_status") == "error"
    ]
    if failures and not any(
        item.get("retrieval_status") == "returned" for item in source.attempts
    ):
        # Nothing succeeded and something errored: the honest instruction is to retry.
        detail = failures[-1].get("detail") or "a lookup failed"
        reason = "a lookup failed rather than the source being absent: %s" % detail
        action = (
            "retry the run first; if the failure repeats, supply the source file "
            "with --pdf-dir"
        )
    elif source.evidence_strength == "none" and source.evidence_text:
        reason = (
            "a ledger row was found but holds no extracted finding, so it describes the "
            "study rather than reporting it"
        )
        action = (
            "add the verbatim effect estimate, participant count or follow-up to the "
            "ledger, or supply the source file with --pdf-dir"
        )
    elif source.retraction_status == "retracted":
        reason = "the source is retracted"
        action = "replace the citation with a current source"
    else:
        reason = "no readable evidence was obtained"
        action = (
            "drop the source file into --pdf-dir (named as the DOI or the title), or "
            "allow acquisition so an open-access copy can be fetched"
        )
    return {
        "source_id": source.source_id,
        "citation_number": source.citation_number,
        "citekey": source.citekey,
        "doi": source.doi,
        "pmid": source.pmid,
        "title": (source.title or source.title_claimed)[:200],
        "sentences_referencing": entry["sentences"],
        "sentences_needing_evidence": entry["needing_evidence"],
        "retrieval_status": source.retrieval_status,
        "evidence_strength": source.evidence_strength,
        "evidence_availability": source.evidence_availability,
        "attempts": attempts,
        "reason": reason,
        "suggested_action": action,
        "worklist_key": source.doi or source.pmid or source.source_id,
        "resolved": "no",
    }


def write_worklist(path, rows: list) -> Path:
    """Write the worklist as CSV. Deterministic order, stable keys."""
    import csv
    import io

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(WORKLIST_COLUMNS), extrasaction="ignore")
    writer.writeheader()
    for row in sorted(rows, key=lambda item: (item.get("citation_number") or "~", item["source_id"])):
        writer.writerow(row)
    return _common.write_text_lf(path, buffer.getvalue())


def read_worklist(path) -> list:
    _fields, rows = _common.read_csv(Path(path))
    return rows


def recheck_worklist(path, bundle) -> dict:
    """Report how many previously missing sources can now be read.

    This is the remediation loop: the worklist names what is missing, the user adds
    the files, and this says what closed. A gap that silently stayed open would be the
    same failure as the original silent degradation, one step later.
    """
    rows = read_worklist(path)
    if not rows:
        return {"checked": 0, "closed": 0, "remaining": 0, "closed_keys": [], "remaining_keys": []}
    by_id = {source.source_id: source for source in bundle.sources}
    by_doi = {source.doi: source for source in bundle.sources if source.doi}
    by_pmid = {source.pmid: source for source in bundle.sources if source.pmid}
    closed: list = []
    remaining: list = []
    for row in rows:
        source = (
            by_id.get(row.get("source_id", ""))
            or by_doi.get((row.get("doi") or "").strip().lower())
            or by_pmid.get((row.get("pmid") or "").strip())
        )
        if source is not None and source.checkable:
            closed.append(row.get("worklist_key") or row.get("source_id"))
        else:
            remaining.append(
                {
                    "source_id": row.get("source_id"),
                    "doi": row.get("doi"),
                    "title": row.get("title"),
                    "reason": (
                        "still no readable evidence"
                        if source is not None
                        else "the source is no longer in the registry"
                    ),
                    "suggested_action": row.get("suggested_action"),
                }
            )
    return {
        "checked": len(rows),
        "closed": len(closed),
        "remaining": len(remaining),
        "closed_keys": closed,
        "remaining_keys": [row["source_id"] for row in remaining],
        # Named `remaining_rows`, not `remaining`: a duplicate key here once let the
        # list overwrite its own count, so the summary reported a list where a number
        # belonged and the check silently compared the wrong thing.
        "remaining_rows": remaining,
    }


def coverage_caveat(result: dict) -> str:
    """One sentence stating why coverage is what it is. Never a bare percentage.

    It names both counts, because they differ and the difference matters: a citation
    whose source we cannot read is unverifiable either way, while only the ones
    asserting a value would become a checked result if the source arrived.
    """
    if not result.get("blocking"):
        return ""
    unreadable = result["citing_sources"] - result["citing_sources_checkable"]
    text = (
        "%d of %d cited source(s) had no readable evidence. %d sentence(s) citing them "
        "could not be verified" % (unreadable, result["citing_sources"], result["unverifiable_sentences"])
    )
    if result["undecided_sentences"]:
        text += "; %d of those assert a checkable value" % result["undecided_sentences"]
    else:
        text += (
            "; none of those assert a checkable value, so supplying the sources would "
            "move them to a synthesis judgement rather than to a checked result"
        )
    return text + ". This is a limit of the inputs, not a property of the document."


def banner(result: dict) -> str:
    """The INPUT-BOUND banner text, deliberately distinct from the gate banner."""
    if not result.get("blocking"):
        return ""
    if result["status"] == "insufficient_input":
        return (
            "INPUT-BOUND \u2014 THE DOCUMENT COULD NOT BE READ WELL ENOUGH. "
            "Findings below are provisional and must not be quoted."
        )
    if result.get("transcription_sentences"):
        # Not the same condition as missing source evidence, and the banner must not say
        # it is: here the sources may be complete and the *text* is a machine's reading.
        return (
            "INPUT-BOUND \u2014 TRANSCRIBED EVIDENCE. %d sentence(s) rest on an OCR "
            "transcription rather than on the document's own text layer. Findings below "
            "are provisional and must not be quoted."
            % result["transcription_sentences"]
        )
    return (
        "INPUT-BOUND \u2014 NOT A FINDING. Source evidence was insufficient to check "
        "every cited sentence. See the worklist."
    )
