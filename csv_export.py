"""Write the merged Slot/Venue/Faculty + ratings dataset to CSV files.

CSV has no concept of multiple sheets, so what used to be 4 sheets in one
.xlsx workbook is now 4 separate .csv files, all prefixed with the source
PDF's name (so results from different PDFs never mix on disk).

CSV also has no cell styling, so the "confidence < 95 -> yellow highlight"
behaviour from the old Excel export is preserved as a plain boolean column
("Low Confidence") instead of a fill color.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

LOW_CONFIDENCE_THRESHOLD = 95


def export_csvs(
    matched_df: pd.DataFrame,
    review_df: pd.DataFrame,
    unmatched_df: pd.DataFrame,
    stats: dict,
    output_folder: Path,
    prefix: str,
) -> list[Path]:
    """Write matched/review/unmatched/stats data for one PDF as four CSVs.

    Files are named '<prefix>_matched.csv', '<prefix>_needs_review.csv',
    '<prefix>_unmatched.csv', '<prefix>_stats.csv'. Returns the list of
    paths written.
    """
    output_folder.mkdir(parents=True, exist_ok=True)

    matched_out = matched_df.copy()
    if "Confidence" in matched_out.columns:
        # Stand-in for the old yellow-highlight formatting, since CSV can't hold cell colors.
        matched_out["Low Confidence"] = matched_out["Confidence"].apply(
            lambda c: bool(c is not None and c < LOW_CONFIDENCE_THRESHOLD)
        )

    paths = {
        f"{prefix}_matched.csv": matched_out,
        f"{prefix}_needs_review.csv": review_df,
        f"{prefix}_unmatched.csv": unmatched_df,
        f"{prefix}_stats.csv": pd.DataFrame(list(stats.items()), columns=["Metric", "Value"]),
    }

    written: list[Path] = []
    for filename, df in paths.items():
        path = output_folder / filename
        df.to_csv(path, index=False)
        written.append(path)
        logger.info("Wrote %s (%d rows)", path, len(df))

    return written
