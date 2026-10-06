"""WHO ICTRP connector for paper-search-mcp.

PATCHED-BY-paper-search-mcp-patches: source #26 (international trial registry aggregator).

Why this source exists
----------------------
The WHO International Clinical Trials Registry Platform aggregates ~20 national
registries (ClinicalTrials.gov, ISRCTN, ChiCTR, CTRI, JPRN, DRKS, ANZCTR, EU
registries ...) behind one search, which is why systematic reviews use it for
cross-registry coverage rather than querying each registry separately.

Verified: ``malaria AND treatment`` -> 870 records / 842 trials spanning
NCT07819825 *and* ISRCTN11384306; ``CRISPR`` -> 137 records / 117 trials
(ChiCTR/NCT/...); ``zzzqqq AND xylophone`` -> no results.

Implementation note: the portal is an ASP.NET WebForms page with no JSON API, so
this connector performs a real form postback -- a fresh GET to obtain the
per-session ``__VIEWSTATE``/``__EVENTVALIDATION`` plus every hidden input, then a
POST with ``TextBox1`` + ``Button1``.  Extra field values beyond the ones the
browser sends make EventValidation reject the post (that is what a 2.6 KB
response means), so unsolicited fields are deliberately not added.

Query semantics: ICTRP treats a bare space as a phrase and needs explicit
operators, and an over-constrained AND can legitimately match nothing
(``CRISPR AND base AND editing`` -> none, while ``CRISPR`` -> 117).  A
progressive-relaxation ladder is therefore used: all terms ANDed -> fewer terms
-> the most distinctive single term.  A page that is neither a result set nor the
"No results" page raises ``SourceUnavailable`` instead of returning [].
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

from ..paper import Paper
from ..source_status import SourceUnavailable, search_terms
from .base import PaperSource

logger = logging.getLogger(__name__)

SEARCH_URL = "https://trialsearch.who.int/Default.aspx"
TRIAL_URL = "https://trialsearch.who.int/Trial2.aspx?TrialID="
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_HIDDEN_RE = re.compile(
    r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', re.I)
_HIDDEN_RE_REVERSED = re.compile(
    r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"[^>]*type="hidden"', re.I)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_TRIAL_ID_RE = re.compile(r"Trial2\.aspx\?TrialID=([^\"'&]+)")
_COUNT_RE = re.compile(r"([\d,]+)\s*records?\s*for\s*([\d,]+)\s*trials?", re.I)

#: Registry inferred from the trial identifier prefix (shown to the user).
_REGISTRIES = (
    ("NCT", "ClinicalTrials.gov"),
    ("ISRCTN", "ISRCTN"),
    ("ChiCTR", "ChiCTR"),
    ("CTRI", "CTRI (India)"),
    ("JPRN", "JPRN (Japan)"),
    ("DRKS", "DRKS (Germany)"),
    ("ANZCTR", "ANZCTR"),
    ("KCT", "KCT (Korea)"),
    ("IRCT", "IRCT (Iran)"),
    ("TCTR", "TCTR (Thailand)"),
    ("EUCTR", "EU CTR"),
    ("NL", "Netherlands Trial Register"),
    ("SLCTR", "SLCTR"),
    ("PACTR", "PACTR"),
    ("REBEC", "ReBec (Brazil)"),
    ("RBR", "ReBec (Brazil)"),
    ("LBCTR", "LBCTR (Lebanon)"),
    ("PER", "Peruvian Registry"),
    ("TCR", "TCR (Tunisia)"),
)


def registry_for(trial_id: str) -> str:
    """Name the registry a trial identifier belongs to (best effort)."""
    upper = (trial_id or "").upper()
    for prefix, name in _REGISTRIES:
        if upper.startswith(prefix):
            return name
    return ""


class ICTRPSearcher(PaperSource):
    """Search the WHO ICTRP aggregator across ~20 registries (free, no key)."""

    SOURCE = "ictrp"
    TIMEOUT = 60

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Referer": SEARCH_URL,
        })

    # ------------------------------------------------------------------ search
    def search(self, query: str, max_results: int = 10, **kwargs) -> List[Paper]:
        """Search the ICTRP portal.

        Args:
            query: Query using explicit operators, e.g. ``"malaria AND treatment"``.
                A bare multi-word phrase is passed through as-is (ICTRP treats it
                as a phrase) with the relaxation ladder applied behind it.
            max_results: Maximum trials to return (default: 10).
        """
        wanted = min(max(int(max_results or 10), 1), 100)
        terms = search_terms(query)

        # Relaxation ladder: all terms ANDed, then every pairwise combination.
        # No single-term rung: ICTRP silently ignores words it deems "noise", so a
        # one-word query derived from an out-of-domain topic degenerates into an
        # empty search that returns unrelated trials.
        candidates: List[str] = []
        raw = str(query or "").strip()
        if len(terms) >= 2:
            candidates.append(" AND ".join(terms))
            # Every pairwise combination, because ICTRP silently ignores words it
            # deems noise, and an over-constrained AND then matches nothing
            # (measured: 'CRISPR AND base' -> 0 records, 'CRISPR AND editing' -> 18).
            for i, first in enumerate(terms):
                for second in terms[i + 1:]:
                    candidates.append(f"{first} AND {second}")
        if raw and len(terms) < 2:
            candidates.append(raw)

        errors: List[SourceUnavailable] = []
        saw_valid_empty = False
        for candidate in dict.fromkeys(c for c in candidates if c):
            try:
                html = self._post_search(candidate)
            except SourceUnavailable as exc:
                errors.append(exc)
                continue
            papers, matched = self._parse_results(html, wanted, terms)
            if papers:
                logger.info(
                    "ICTRP query %r matched %s, returning %s",
                    candidate[:60], matched, len(papers),
                )
                return papers
            saw_valid_empty = True

        # A rung that produced a proper "0 records" page proves the search works,
        # so an odd page on another rung must not be reported as an outage.
        if saw_valid_empty or not errors:
            return []
        raise errors[0]

    # ------------------------------------------------------------- transport
    def _post_search(self, query: str) -> str:
        """Run one ICTRP search postback and return the results page HTML."""
        try:
            form = self.session.get(SEARCH_URL, timeout=self.TIMEOUT)
        except requests.RequestException as exc:
            raise SourceUnavailable("ictrp", f"form fetch failed: {exc}"[:200])

        if form.status_code != 200:
            raise SourceUnavailable(
                "ictrp", f"form fetch returned {form.status_code}", form.status_code)

        payload: Dict[str, str] = {}
        for pattern in (_HIDDEN_RE, _HIDDEN_RE_REVERSED):
            for name, value in pattern.findall(form.text):
                payload.setdefault(name, value)
        if "__VIEWSTATE" not in payload:
            raise SourceUnavailable(
                "ictrp", "search form did not carry a __VIEWSTATE field")

        # Only the fields the real browser sends: extra values make ASP.NET
        # EventValidation reject the post (observed as a ~2.6 KB error page).
        payload.update({
            "TextBox1": query,
            "Button1": "Search",
            "TextBoxWatermarkExtender1_ClientState": "undefined",
        })

        try:
            response = self.session.post(
                SEARCH_URL,
                data=urlencode(payload),
                timeout=self.TIMEOUT,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except requests.RequestException as exc:
            raise SourceUnavailable("ictrp", f"search postback failed: {exc}"[:200])

        if response.status_code != 200:
            raise SourceUnavailable(
                "ictrp", f"search returned {response.status_code}", response.status_code)

        html = response.text
        if len(html) < 8000:
            raise SourceUnavailable(
                "ictrp",
                f"search page looks like a rejected postback ({len(html)} bytes)",
            )
        # A genuine results page always announces "N records for M trials found".
        # The "No results" page is acceptable too -- and must be recognised first,
        # because it carries a stray Trial2.aspx link in its page furniture that an
        # earlier version mistook for a result (it surfaced a newborn-body-
        # composition trial for a physics query).
        if not _COUNT_RE.search(html) and "No results were found" not in html:
            raise SourceUnavailable(
                "ictrp", "unrecognised results page (no record count, no 'no results')")
        return html

    # ----------------------------------------------------------------- parsing
    def _parse_results(self, html: str, wanted: int, terms=None):
        """Return (papers, matched_count) parsed from an ICTRP results page."""
        if "No results were found" in html:
            return [], "0"

        count_match = _COUNT_RE.search(html)
        if not count_match:
            # No count means this is not a results page; do not mine stray links.
            return [], "0"
        matched = count_match.group(1).replace(",", "")
        if matched == "0":
            return [], "0"

        # No client-side term filter: every rung sends an explicit AND query, and
        # ICTRP ANDs it against its full index (which covers scientific titles and
        # interventions, not just the public title shown here).  A title-only check
        # was rejected by measurement: it dropped real CRISPR trials, whose public
        # titles name the edited gene ("BCL11A enhancer") rather than "CRISPR".
        # The hazard it was guarding against -- out-of-vocabulary words being
        # filtered out until the query is empty -- is removed by dropping the
        # single-term rung above.

        papers: List[Paper] = []
        seen = set()
        for row in _ROW_RE.findall(html):
            id_match = _TRIAL_ID_RE.search(row)
            if not id_match:
                continue
            trial_id = id_match.group(1).strip()
            if not trial_id or trial_id in seen:
                continue
            seen.add(trial_id)

            cells = [" ".join(_TAG_RE.sub(" ", cell).split())
                     for cell in _CELL_RE.findall(row)]
            cells = [cell for cell in cells if cell]

            status = cells[0] if cells else ""
            prospective = cells[1] if len(cells) > 1 else ""

            # Columns are: status, prospective registration, main ID, (link),
            # public title, date of registration, results available.
            title = ""
            for cell in cells[2:]:
                if cell.upper() == trial_id.upper():
                    continue
                if re.fullmatch(r"[\d/\-]{6,}", cell):
                    continue
                if len(cell) > len(title):
                    title = cell

            registration_date = ""
            for cell in cells:
                if re.fullmatch(r"\d{1,2}\s+\w{3,9}\s+\d{4}", cell):
                    registration_date = cell
                    break

            results_available = "Yes" if cells and cells[-1].strip().lower() == "yes" else ""
            registry = registry_for(trial_id)

            published: Optional[datetime] = None
            for fmt in ("%d %B %Y", "%d %b %Y"):
                try:
                    published = datetime.strptime(registration_date, fmt)
                    break
                except ValueError:
                    continue

            papers.append(Paper(
                paper_id=trial_id,
                title=title or trial_id,
                authors=[registry] if registry else [],
                abstract=" ".join(part for part in (
                    f"Registry: {registry}." if registry else "",
                    f"Recruitment status: {status}." if status else "",
                    f"Registered: {registration_date}." if registration_date else "",
                    f"Results available: {results_available}." if results_available else "",
                ) if part),
                doi="",
                published_date=published,
                pdf_url="",
                url=f"{TRIAL_URL}{trial_id}",
                source=self.SOURCE,
                categories=[item for item in (registry, status) if item],
                keywords=[registry] if registry else [],
                citations=0,
                extra={
                    "trial_id": trial_id,
                    "registry": registry,
                    "recruitment_status": status,
                    "prospective_registration": prospective,
                    "results_available": results_available,
                    "registration_date": registration_date,
                },
            ))
            if len(papers) >= wanted:
                break

        return papers, matched
