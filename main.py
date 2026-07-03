"""Faculty Slot Parser and Rating Merger - CLI entrypoint.

Usage:
    python main.py [--pdf-folder ./pdfs] [--ratings-file ./ratings.xlsx] [--output-folder ./output]

--ratings-file can point at:
    - a single .xlsx/.csv file, or
    - a folder containing multiple .xlsx/.csv ratings files (all of them are
      loaded and merged into one lookup table before matching).

Each PDF in --pdf-folder is parsed and matched independently, and gets its
own set of output CSVs (named after the PDF), rather than everything being
combined into one report. This keeps e.g. two PDFs for two different
subjects from being merged into a single list.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from csv_export import export_csvs
from matcher import classify, match_name
from normalizer import normalize_name
from pdf_parser import parse_pdf

logger = logging.getLogger(__name__)

# Column name candidates -> canonical field, checked case-insensitively in this priority order.
RATINGS_COLUMN_ALIASES = {
    "faculty": ["faculty name", "faculty", "name", "professor", "instructor"],
    "rating": ["overall", "rating", "avg rating", "average rating", "score"],
    "difficulty": ["difficulty"],
    "review_count": ["total raters", "review count", "reviews", "num reviews", "raters"],
    "department": ["department", "dept", "school"],
}

RATINGS_FILE_SUFFIXES = {".csv", ".xlsx", ".xls"}


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


def _load_single_ratings_file(path: Path) -> pd.DataFrame:
    """Load one ratings CSV/XLSX and rename its columns to canonical field
    names (faculty/rating/difficulty/review_count/department), without
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

    logger.info("Ratings column mapping for %s: %s", path.name, resolved)
    df = df.rename(columns={orig: field for field, orig in resolved.items()})
    keep_cols = [c for c in ("faculty", "rating", "difficulty", "review_count", "department") if c in df.columns]
    df = df[keep_cols].copy()
    df["__source_file"] = path.name
    return df


def load_ratings(path: Path) -> pd.DataFrame:
    """Load ratings from a single file, or from every ratings file in a
    folder, merged into one lookup table keyed by faculty name.

    If the same faculty name (after normalization) appears in more than one
    file, the first occurrence found wins and a warning is logged so the
    conflict isn't silent.
    """
    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.suffix.lower() in RATINGS_FILE_SUFFIXES)
        if not files:
            raise ValueError(f"No ratings files (.csv/.xlsx/.xls) found in folder {path}")
    else:
        files = [path]

    frames = [_load_single_ratings_file(f) for f in files]
    combined = pd.concat(frames, ignore_index=True)

    combined["__norm_faculty"] = combined["faculty"].astype(str).apply(normalize_name)
    dupe_mask = combined.duplicated(subset="__norm_faculty", keep="first")
    for _, row in combined[dupe_mask].iterrows():
        logger.warning(
            "Duplicate faculty '%s' found in %s; keeping the first entry seen for this name.",
            row["faculty"], row["__source_file"],
        )
    combined = combined[~dupe_mask].drop(columns=["__norm_faculty", "__source_file"]).reset_index(drop=True)

    logger.info("Loaded %d ratings rows from %d file(s): %s", len(combined), len(files), [f.name for f in files])
    return combined


def build_output_frames(slot_rows, ratings_df: pd.DataFrame):
    candidate_names = ratings_df["faculty"].dropna().astype(str).unique().tolist()
    ratings_by_name = {row["faculty"]: row for _, row in ratings_df.iterrows()}

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
                "Rating": rdata.get("rating", None),
                "Difficulty": rdata.get("difficulty", None),
                "Review Count": rdata.get("review_count", None),
                "Department": rdata.get("department", None),
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


def run(pdf_folder: Path, ratings_file: Path, output_folder: Path) -> list[Path]:
    setup_logging(output_folder)

    pdf_paths = sorted(Path(pdf_folder).glob("*.pdf"))
    if not pdf_paths:
        raise RuntimeError(f"No PDFs found in {pdf_folder}")

    ratings_df = load_ratings(ratings_file)

    all_written: list[Path] = []
    for pdf_path in pdf_paths:
        slot_rows = parse_pdf(pdf_path)
        if not slot_rows:
            logger.warning("No slot rows extracted from %s; skipping.", pdf_path.name)
            continue

        matched_df, review_df, unmatched_df, stats = build_output_frames(slot_rows, ratings_df)
        prefix = pdf_path.stem
        written = export_csvs(matched_df, review_df, unmatched_df, stats, output_folder, prefix)
        all_written.extend(written)
        logger.info("Done with %s. Stats: %s", pdf_path.name, stats)

    if not all_written:
        raise RuntimeError(f"No slot rows extracted from any PDF in {pdf_folder}")

    return all_written


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse FFCS PDFs and merge with faculty ratings.")
    parser.add_argument("--pdf-folder", default="./pdfs", type=Path)
    parser.add_argument("--ratings-file", default="./ratings.xlsx", type=Path,
                         help="A single ratings file, or a folder of ratings files to merge.")
    parser.add_argument("--output-folder", default="./output", type=Path)
    args = parser.parse_args()
    run(args.pdf_folder, args.ratings_file, args.output_folder)


if __name__ == "__main__":
    main()