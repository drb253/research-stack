#!/usr/bin/env python3
"""Reconcile the source ledger against the retrieval records that were actually returned.

The skill's central failure mode is a citation that resolves but describes a different paper.
Judging that by eye is the weakest link in the chain, so this command compares the ledger with
saved tool output field by field and refuses to let a mismatch pass silently.

Inputs
  sources.csv            the ledger (required)
  records/ or a file     saved retrieval records: JSON, JSONL, or a directory of them

Record shape: whatever the retrieval tool returned. Crossref, Europe PMC, PubMed and OpenAlex
keys are all recognised (title, authors, container_title/journal, issued/published_date,
volume, page/pages, doi, pmid, abstract, is_retracted), including a stringified ``extra``
object as returned by the paper-search MCP server.

Checks
  RECORD_MISSING           no saved record for the source's DOI or PMID
  DOI_MISMATCH             the record carries a different DOI
  TITLE_MISMATCH           normalised title similarity below --min-title-similarity
  YEAR_MISMATCH            publication year differs
  VOLUME_MISMATCH          volume differs (skipped when either side is not_reported)
  PAGES_MISMATCH           first page or range differs
  FIRST_AUTHOR_MISMATCH    the ledger's first-author surname is not the record's
  RETRACTION_CONFLICT      the record says retracted and the ledger does not
  NUMBER_NOT_IN_RECORD     a number in effect_estimate is absent from title/abstract

Usage
  python3 scripts/verify_records.py --sources sources.csv --records records/
  python3 scripts/verify_records.py --sources sources.csv --records records/ --require-all
"""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import re
from pathlib import Path

from _common import (
    InputError,
    emit_report,
    issue,
    normalize_doi,
    normalize_title,
    read_csv,
    read_text,
    run,
)

TOOL = "verify_records"
TAG_RE = re.compile(r"<[^>]+>")
NUM_RE = re.compile(r"\d+(?:\.\d+)?")
NOT_REPORTED = {"not_reported", "not reported", "nr", "none", "not_applicable", "n/a", "na", ""}


def clean(value) -> str:
    text = TAG_RE.sub(" ", str(value or ""))
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", text).strip()


def flatten(data):
    if isinstance(data, dict):
        for key in ("records", "results", "papers", "items", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        return [data]
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def load_records(path: Path):
    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.suffix.lower() in (".json", ".jsonl"))
    elif path.is_file():
        files = [path]
    else:
        raise InputError("records path does not exist: %s" % path)
    if not files:
        raise InputError("no .json or .jsonl records under: %s" % path)
    records = []
    for file_path in files:
        raw = read_text(file_path, {".json", ".jsonl"})
        if file_path.suffix.lower() == ".jsonl":
            for line in raw.splitlines():
                if line.strip():
                    records.extend(flatten(json.loads(line)))
        else:
            records.extend(flatten(json.loads(raw)))
    return records


def extra_of(record: dict) -> dict:
    extra = record.get("extra")
    if isinstance(extra, str) and extra.strip().startswith("{"):
        try:
            parsed = ast.literal_eval(extra)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, SyntaxError):
            return {}
    return extra if isinstance(extra, dict) else {}


def field(record: dict, names):
    for name in names:
        value = record.get(name)
        if value not in (None, "", []):
            return value
    extra = extra_of(record)
    for name in names:
        value = extra.get(name)
        if value not in (None, "", []):
            return value
    return ""


def rec_doi(record: dict) -> str:
    value = field(record, ["doi", "DOI"])
    if not value:
        paper_id = str(field(record, ["paper_id", "paperId"]))
        if paper_id.lower().startswith("10."):
            value = paper_id
    return normalize_doi(str(value)) if value else ""


def rec_pmid(record: dict) -> str:
    value = field(record, ["pmid", "PMID"])
    if not value:
        paper_id = str(field(record, ["paper_id", "paperId"]))
        if paper_id.isdigit():
            value = paper_id
    return str(value).strip()


def rec_title(record: dict) -> str:
    return clean(field(record, ["title", "article_title"]))


def rec_year(record: dict) -> int:
    value = field(record, ["year", "publication_year", "pub_year"])
    if not value:
        value = field(record, ["published_date", "publication_date", "issued", "published"])
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    if isinstance(value, dict):
        value = value.get("date-parts") or value.get("value") or ""
        if isinstance(value, list) and value and isinstance(value[0], list):
            value = value[0][0] if value[0] else ""
    match = re.search(r"(19|20)\d{2}", str(value))
    return int(match.group(0)) if match else 0


def rec_volume(record: dict) -> str:
    return clean(field(record, ["volume", "journal_volume"]))


def rec_pages(record: dict) -> str:
    return clean(field(record, ["page", "pages", "first_page", "page_range"]))


def rec_authors(record: dict):
    value = field(record, ["authors", "author", "authorString"])
    if isinstance(value, list):
        return [clean(v.get("name", "") if isinstance(v, dict) else v) for v in value]
    return [part.strip() for part in re.split(r";", str(value)) if part.strip()]


def rec_abstract(record: dict) -> str:
    return clean(field(record, ["abstract", "abstractText", "summary"]))


def rec_retracted(record: dict):
    flag = record.get("is_retracted")
    if isinstance(flag, bool):
        return flag
    status = str(field(record, ["retraction_status", "retractionStatus"])).strip().lower()
    return status in {"retracted", "expression_of_concern", "expression of concern"}


def surname_tokens(name: str):
    tokens = re.findall(r"[A-Za-z\u00c0-\u024f'\-]+", clean(name))
    while tokens and len(tokens[-1]) <= 2:      # drop initials: "Bray F" -> ["Bray"]
        tokens.pop()
    return [token.lower() for token in tokens]


def surname_matches(ledger_author: str, record_author: str) -> bool:
    wanted = surname_tokens(ledger_author)
    offered = surname_tokens(record_author)
    if not wanted or not offered:
        return True
    if " ".join(wanted) in " ".join(offered):
        return True
    return offered[-len(wanted):] == wanted


def similarity(left: str, right: str) -> float:
    a, b = normalize_title(left), normalize_title(right)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def page_head(value: str) -> str:
    match = re.search(r"[A-Za-z]?\d+", value or "")
    return match.group(0).lower() if match else ""


def absent(value: str) -> bool:
    return clean(value).lower() in NOT_REPORTED


def check_row(row, record, min_similarity, check_numbers, strict_numbers):
    source_id = row.get("source_id", "?")
    found = []

    ledger_doi = row.get("doi", "")
    record_doi = rec_doi(record)
    if ledger_doi and not absent(ledger_doi) and record_doi and normalize_doi(ledger_doi) != record_doi:
        found.append(issue("error", "DOI_MISMATCH", item_id=source_id,
                           detail="ledger %s vs record %s" % (ledger_doi, record_doi)))

    ledger_title, record_title = row.get("title", ""), rec_title(record)
    if record_title:
        score = similarity(ledger_title, record_title)
        if score < min_similarity:
            found.append(issue("error", "TITLE_MISMATCH", item_id=source_id,
                               detail="similarity %.2f: %s" % (score, record_title[:110])))
    else:
        found.append(issue("warning", "RECORD_TITLE_MISSING", item_id=source_id,
                           detail="the saved record carries no title; identity cannot be confirmed"))

    ledger_year = int(re.sub(r"\D", "", row.get("year", "")) or 0)
    record_year = rec_year(record)
    if ledger_year and record_year and ledger_year != record_year:
        found.append(issue("error", "YEAR_MISMATCH", item_id=source_id,
                           detail="ledger %d vs record %d" % (ledger_year, record_year)))

    ledger_volume, record_volume = row.get("volume", ""), rec_volume(record)
    if not absent(ledger_volume) and record_volume and ledger_volume.strip() != record_volume:
        found.append(issue("warning", "VOLUME_MISMATCH", item_id=source_id,
                           detail="ledger %s vs record %s" % (ledger_volume, record_volume)))

    ledger_pages, record_pages = row.get("pages", ""), rec_pages(record)
    if not absent(ledger_pages) and record_pages:
        if page_head(ledger_pages) and page_head(ledger_pages) != page_head(record_pages):
            found.append(issue("warning", "PAGES_MISMATCH", item_id=source_id,
                               detail="ledger %s vs record %s" % (ledger_pages, record_pages)))

    authors = rec_authors(record)
    ledger_author = (row.get("authors") or "").split(",")[0].strip()
    if authors and ledger_author and not surname_matches(ledger_author, authors[0]):
        found.append(issue("warning", "FIRST_AUTHOR_MISMATCH", item_id=source_id,
                           detail="ledger %s vs record %s" % (ledger_author, authors[0])))

    ledger_retraction = (row.get("retraction_status") or "").strip().lower()
    if rec_retracted(record) and ledger_retraction not in {"retracted", "expression_of_concern"}:
        found.append(issue("error", "RETRACTION_CONFLICT", item_id=source_id,
                           detail="the record is marked retracted; ledger says %s" % (ledger_retraction or "blank")))
    elif ledger_retraction in {"retracted", "expression_of_concern"} and not rec_retracted(record):
        found.append(issue("warning", "RETRACTION_UNCONFIRMED", item_id=source_id,
                           detail="ledger marks the source retracted; the saved record does not"))

    if check_numbers:
        abstract = rec_abstract(record)
        if not abstract:
            found.append(issue("info", "ABSTRACT_MISSING", item_id=source_id,
                               detail="no abstract in the record; numbers cannot be traced"))
        else:
            haystack = rec_title(record) + " " + abstract
            estimate = row.get("effect_estimate", "")
            if not absent(estimate):
                missing = [token for token in NUM_RE.findall(estimate)
                           if len(token) >= 2 and token not in haystack]
                if missing:
                    found.append(issue("error" if strict_numbers else "warning", "NUMBER_NOT_IN_RECORD",
                                       item_id=source_id, detail=", ".join(sorted(set(missing))[:8])))
    return found


def cli():
    parser = argparse.ArgumentParser(description="Reconcile sources.csv with saved retrieval records.")
    parser.add_argument("--sources", required=True, help="source ledger (sources.csv)")
    parser.add_argument("--records", required=True, help="record file or directory of JSON/JSONL records")
    parser.add_argument("--min-title-similarity", type=float, default=0.90)
    parser.add_argument("--require-all", action="store_true",
                        help="a source with no saved record is an error, not a warning")
    parser.add_argument("--check-numbers", action="store_true",
                        help="trace effect-estimate numbers into the record's title and abstract")
    parser.add_argument("--strict-numbers", action="store_true",
                        help="an untraceable number becomes an error")
    parser.add_argument("--all", action="store_true",
                        help="check every ledger row, not only verified citable rows")
    args = parser.parse_args()

    if not 0.5 <= args.min_title_similarity <= 1.0:
        raise InputError("--min-title-similarity must be between 0.5 and 1.0")

    _, rows = read_csv(args.sources)
    records = load_records(Path(args.records))

    by_doi, by_pmid = {}, {}
    for record in records:
        doi, pmid = rec_doi(record), rec_pmid(record)
        if doi:
            by_doi.setdefault(doi, record)
        if pmid:
            by_pmid.setdefault(pmid, record)

    issues, checked, matched, missing = [], 0, 0, 0
    for row in rows:
        citable = (row.get("verification_status") == "verified"
                   and row.get("inclusion_status") in {"included", "cited_for_context"})
        if not citable and not args.all:
            continue
        checked += 1
        doi = row.get("doi", "")
        pmid = row.get("pmid", "")
        record = by_doi.get(normalize_doi(doi)) if doi and not absent(doi) else None
        if record is None and pmid and not absent(pmid):
            record = by_pmid.get(str(pmid).strip())
        if record is None:
            missing += 1
            issues.append(issue("error" if args.require_all else "warning", "RECORD_MISSING",
                                item_id=row.get("source_id", "?"),
                                detail="no saved record for doi=%s pmid=%s" % (doi or "none", pmid or "none")))
            continue
        matched += 1
        issues.extend(check_row(row, record, args.min_title_similarity,
                                args.check_numbers, args.strict_numbers))

    return emit_report(TOOL, issues, summary={
        "sources_in_ledger": len(rows),
        "sources_checked": checked,
        "records_loaded": len(records),
        "records_matched": matched,
        "records_missing": missing,
        "min_title_similarity": args.min_title_similarity,
    })


if __name__ == "__main__":
    run(TOOL, cli)
