"""Faculty Slot Parser and Rating Merger - CLI entrypoint.

Usage:
    python main.py [--pdf-folder ./pdfs] [--ratings-file ./ratings.xlsx] [--output-folder ./output]
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from excel_export import export_workbook
from matcher import classify, match_name
from normalizer import normalize_name
from pdf_parser import parse_pdf_folder

logger = logging.getLogger(__name__)

# Column name candidates -> canonical field, checked case-insensitively in this priority order.
RATINGS_COLUMN_ALIASES = {
    "faculty": ["faculty name", "faculty", "name", "professor", "instructor"],
    "rating": ["overall", "rating", "avg rating", "average rating", "score"],
    "difficulty": ["difficulty"],
    "review_count": ["total raters", "review count", "reviews", "num reviews", "raters"],
    "department": ["department", "dept", "school"],
}


def setup_logging(output_folder: Path) -> None:
    output_folder.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(output_folder / "matching_log.txt", mode="w", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def load_ratings(path: Path) -> tuple[pd.DataFrame, dict[str, str]]:
    """Load ratings CSV/XLSX and map its columns to canonical fields, without
    assuming a fixed schema."""
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        df = pd.read_excel(path)

    lower_cols = {c.lower().strip(): c for c in df.columns}
    resolved: dict[str, str] = {}
    for field, aliases in RATINGS_COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lower_cols:
                resolved[field] = lower_cols[alias]
                break
    if "faculty" not in resolved:
        raise ValueError(f"Could not find a faculty-name column in {path}. Columns: {list(df.columns)}")
    logger.info("Ratings column mapping: %s", resolved)
    return df, resolved


def build_output_frames(slot_rows, ratings_df: pd.DataFrame, colmap: dict[str, str]):
    faculty_col = colmap["faculty"]
    candidate_names = ratings_df[faculty_col].dropna().astype(str).unique().tolist()
    ratings_by_name = {row[faculty_col]: row for _, row in ratings_df.iterrows()}

    # Cache one match result per unique PDF faculty name (avoid recomputation per slot row).
    unique_names = sorted({row.faculty for row in slot_rows})
    match_cache = {name: match_name(name, candidate_names) for name in unique_names}
    for name, result in match_cache.items():
        logger.info("Match decision: '%s' -> %s (score=%.1f, method=%s)", name, result.matched_name, result.score, result.method)

    matched_records, review_records, unmatched_records = [], [], []
    for row in slot_rows:
        result = match_cache[row.faculty]
        bucket = classify(result)
        if bucket == "matched":
            rdata = ratings_by_name.get(result.matched_name, {})
            matched_records.append({
                "Faculty (PDF)": row.faculty,
                "Matched Faculty": result.matched_name,
                "Slot": row.slot,
                "Venue": row.venue,
                "Rating": rdata.get(colmap.get("rating", ""), None),
                "Difficulty": rdata.get(colmap.get("difficulty", ""), None),
                "Review Count": rdata.get(colmap.get("review_count", ""), None),
                "Department": rdata.get(colmap.get("department", ""), None),
                "Confidence": round(result.score, 1),
            })
        elif bucket == "review":
            review_records.append({
                "Faculty From PDF": row.faculty,
                "Top Candidate": result.matched_name,
                "Score": round(result.score, 1),
                "Possible Matches": ", ".join(f"{n} ({s:.0f})" for n, s in result.candidates) or result.matched_name or "",
            })
        else:
            unmatched_records.append({"Faculty Name": row.faculty})

    matched_df = pd.DataFrame(matched_records, columns=["Faculty (PDF)", "Matched Faculty", "Slot", "Venue", "Rating", "Difficulty", "Review Count", "Department", "Confidence"])
    review_df = pd.DataFrame(review_records, columns=["Faculty From PDF", "Top Candidate", "Score", "Possible Matches"]).drop_duplicates()
    unmatched_df = pd.DataFrame(unmatched_records, columns=["Faculty Name"]).drop_duplicates()

    stats = {
        "Total slot rows": len(slot_rows),
        "Unique faculty (PDF)": len(unique_names),
        "Auto-matched slot rows": len(matched_records),
        "Needs-review names": review_df["Faculty From PDF"].nunique() if not review_df.empty else 0,
        "Unmatched names": len(unmatched_df),
    }
    return matched_df, review_df, unmatched_df, stats


def run(pdf_folder: Path, ratings_file: Path, output_folder: Path) -> Path:
    setup_logging(output_folder)
    slot_rows = parse_pdf_folder(pdf_folder)
    if not slot_rows:
        raise RuntimeError(f"No slot rows extracted from any PDF in {pdf_folder}")
    ratings_df, colmap = load_ratings(ratings_file)
    matched_df, review_df, unmatched_df, stats = build_output_frames(slot_rows, ratings_df, colmap)

    output_path = output_folder / "faculty_slots_with_ratings.xlsx"
    export_workbook(matched_df, review_df, unmatched_df, stats, output_path)
    logger.info("Done. Stats: %s", stats)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse FFCS PDFs and merge with faculty ratings.")
    parser.add_argument("--pdf-folder", default="./pdfs", type=Path)
    parser.add_argument("--ratings-file", default="./ratings.xlsx", type=Path)
    parser.add_argument("--output-folder", default="./output", type=Path)
    args = parser.parse_args()
    run(args.pdf_folder, args.ratings_file, args.output_folder)


if __name__ == "__main__":
    main()
