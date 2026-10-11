"""Statistical analysis of paper data.

Computes data availability, author statistics, and publication year
distributions, mirroring the logic from literature_review_bulk.py.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def _num(value: Any, ndigits: int = 3) -> Any:
    """Round a statistic for JSON output.

    ``pandas`` returns NaN for the sample standard deviation of a single
    observation (ddof=1), and ``round(float('nan'), 3)`` is still NaN — which
    makes ``json.dumps(..., allow_nan=False)`` raise "Out of range float values
    are not JSON compliant". NaN/inf are reported as ``None`` (honestly
    "undefined") so the payload always serialises as strict JSON.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return round(number, ndigits)


def compute_stats(papers: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute statistics on a list of papers.

    Args:
        papers: List of paper dicts (as returned by
            :func:`academic_search.api.fetch_all_papers`).

    Returns:
        A dict with:
        - ``total_papers``
        - ``field_availability``: per-field null counts and percentages.
        - ``authors``: author count distribution (min, max, mean, std,
          median, IQR).
        - ``publication_year``: year distribution (min, max, mean, std,
          median, IQR).
    """
    if not papers:
        return {"error": "No papers to compute statistics on."}

    data = pd.DataFrame(papers)

    # --- Data availability ---
    availability: dict[str, Any] = {}
    for col in data.columns:
        if col.startswith("_"):
            continue  # Skip internal keys
        non_null = len(data) - int(data[col].isna().sum())
        availability[col] = {
            "count": non_null,
            "total": len(data),
            "percentage": round(100.0 * non_null / len(data), 3),
        }

    # --- Authors ---
    authors_stats: dict[str, Any] = {}
    if "authors" in data.columns:
        data["authors_count"] = data["authors"].apply(
            lambda x: len(x) if isinstance(x, list) and len(x) > 0 else np.nan
        )
        ac = data["authors_count"].dropna()
        if len(ac) > 0:
            authors_stats = {
                "with_authors_data": {
                    "count": int(len(ac)),
                    "total": len(data),
                    "percentage": round(100.0 * len(ac) / len(data), 3),
                },
                "single_author": int((ac == 1).sum()),
                "co_authors": int((ac > 1).sum()),
                "min": int(ac.min()),
                "max": int(ac.max()),
                "mean": _num(ac.mean()),
                "std": _num(ac.std()),
                "median": _num(ac.quantile(0.5)),
                "iqr": [
                    _num(ac.quantile(0.25)),
                    _num(ac.quantile(0.75)),
                ],
            }

    # --- Publication year ---
    year_stats: dict[str, Any] = {}
    if "year" in data.columns:
        yr = data["year"].dropna()
        if len(yr) > 0:
            year_stats = {
                "with_year_data": {
                    "count": int(len(yr)),
                    "total": len(data),
                    "percentage": round(100.0 * len(yr) / len(data), 3),
                },
                "min": int(yr.min()),
                "max": int(yr.max()),
                "mean": _num(yr.mean()),
                "std": _num(yr.std()),
                "median": _num(yr.quantile(0.5)),
                "iqr": [
                    _num(yr.quantile(0.25)),
                    _num(yr.quantile(0.75)),
                ],
            }

    return {
        "total_papers": len(papers),
        "field_availability": availability,
        "authors": authors_stats,
        "publication_year": year_stats,
    }
