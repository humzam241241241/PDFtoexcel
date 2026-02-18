"""
Validation diagnostic script for extract_b92.py
Runs the current parser against each PDF and reports detailed diagnostics.
Does NOT modify the parser. Read-only analysis.
"""

import re
import sys
from pathlib import Path
from datetime import datetime

import pdfplumber
import pandas as pd

# Import the existing extractor functions without modification
sys.path.insert(0, str(Path(__file__).parent))
from extract_b92 import extract_sensor_name, parse_pdf


PDF_FILES = [
    Path(r"C:\Users\U1106812\Downloads\QE-1681582 Non-GMP run B92 AlPO4 22Jan2026.pdf"),
    Path(r"C:\Users\U1106812\Downloads\QE-1681582 TK-001 Conductivity 16Jan2026.pdf"),
    Path(r"C:\Users\U1106812\Downloads\QE-1681582 TK-001 Weight Trend 16Jan2026.pdf"),
    Path(r"C:\Users\U1106812\Downloads\Tabular (2).pdf"),
]

SEPARATOR = "=" * 80


def try_parse_timestamp(ts_text: str) -> str | None:
    """Try common datetime formats. Return error string if all fail, else None."""
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M",
        "%d-%b-%Y %H:%M:%S",
        "%d-%b-%Y %H:%M",
        "%b %d, %Y %H:%M:%S",
        "%m/%d/%Y %I:%M:%S %p",
        "%d/%m/%Y %I:%M:%S %p",
    ]
    for fmt in formats:
        try:
            datetime.strptime(ts_text.strip(), fmt)
            return None
        except ValueError:
            continue
    # Also try pandas as a fallback
    try:
        pd.to_datetime(ts_text.strip())
        return None
    except Exception:
        pass
    return f"FAILED to parse: '{ts_text}'"


def is_non_numeric(val_text: str) -> bool:
    """Return True if the value cannot be interpreted as a number."""
    try:
        float(val_text.replace(",", ""))
        return False
    except (ValueError, TypeError):
        return True


def diagnose_pdf(pdf_path: Path) -> None:
    print(f"\n{SEPARATOR}")
    print(f"FILE: {pdf_path.name}")
    print(f"PATH: {pdf_path}")
    print(SEPARATOR)

    if not pdf_path.exists():
        print("  *** FILE NOT FOUND ***")
        return

    # --- Phase 1: Low-level page-by-page inspection ---
    print("\n--- Page-by-page inspection (raw pdfplumber) ---\n")

    pages_no_table = []
    page_table_counts = {}
    page_row_counts = {}
    total_raw_rows = 0

    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            print(f"  Total pages: {total_pages}")

            for page_idx, page in enumerate(pdf.pages):
                page_num = page_idx + 1
                tables = page.find_tables()
                num_tables = len(tables)
                page_table_counts[page_num] = num_tables

                if num_tables == 0:
                    pages_no_table.append(page_num)
                    page_row_counts[page_num] = 0
                    print(f"\n  Page {page_num}: 0 tables found")
                    print(f"    Raw text extract (first 500 chars):")
                    raw_text = page.extract_text() or "(empty)"
                    for line in raw_text[:500].splitlines():
                        print(f"      | {line}")
                    if len(raw_text) > 500:
                        print(f"      | ... ({len(raw_text)} total chars)")
                    continue

                rows_this_page = 0
                for t_idx, tbl in enumerate(tables):
                    extracted = tbl.extract()
                    num_rows = len(extracted) if extracted else 0
                    rows_this_page += num_rows
                    total_raw_rows += num_rows

                    if t_idx == 0 and page_idx == 0:
                        # Show sensor name detection for first table on first page
                        table_top = tbl.bbox[1]
                        sensor = extract_sensor_name(page, table_top)
                        print(f"\n  Detected sensor name: {sensor}")

                page_row_counts[page_num] = rows_this_page
                print(f"\n  Page {page_num}: {num_tables} table(s), {rows_this_page} raw row(s)")

    except Exception as e:
        print(f"  *** pdfplumber FAILED: {type(e).__name__}: {e} ***")
        return

    print(f"\n  Total raw rows across all pages: {total_raw_rows}")

    # --- Phase 2: Run the actual parser ---
    print("\n--- Parser output (parse_pdf) ---\n")

    try:
        df = parse_pdf(pdf_path)
    except Exception as e:
        print(f"  *** parse_pdf FAILED: {type(e).__name__}: {e} ***")
        return

    print(f"  Total extracted rows: {len(df)}")

    if df.empty:
        print("  (no rows extracted)")
    else:
        print(f"\n  First 5 extracted rows:")
        print(df.head(5).to_string(index=False))

    # --- Phase 3: Diagnostics ---
    print(f"\n--- Diagnostics ---\n")

    # Pages with no table
    if pages_no_table:
        print(f"  Pages with NO table detected: {pages_no_table}")
    else:
        print(f"  All pages had at least one table.")

    # Rows skipped analysis: compare raw rows vs extracted
    raw_data_rows = 0
    skipped_reasons = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                tables = page.find_tables()
                if not tables:
                    continue
                table = tables[0]
                rows = table.extract()
                if not rows:
                    continue
                for row_idx, row in enumerate(rows):
                    raw_data_rows += 1
                    if row is None or len(row) < 2:
                        skipped_reasons.append(
                            f"  Page {page_idx+1}, row {row_idx}: None or <2 cols -> {row}"
                        )
                        continue
                    ts_raw, val_raw = row[0], row[1]
                    if ts_raw is None or val_raw is None:
                        skipped_reasons.append(
                            f"  Page {page_idx+1}, row {row_idx}: ts or val is None -> {row}"
                        )
                        continue
                    ts_text = str(ts_raw).strip()
                    val_text = str(val_raw).strip()
                    if re.match(r"(?i)^time", ts_text) or re.match(r"(?i)^val", val_text):
                        skipped_reasons.append(
                            f"  Page {page_idx+1}, row {row_idx}: header row -> [{ts_text}, {val_text}]"
                        )
                        continue
                    if not ts_text or not val_text:
                        skipped_reasons.append(
                            f"  Page {page_idx+1}, row {row_idx}: empty ts or val -> [{repr(ts_text)}, {repr(val_text)}]"
                        )
                        continue
    except Exception as e:
        print(f"  *** Skip analysis failed: {e} ***")

    print(f"\n  Raw rows from first table per page: {raw_data_rows}")
    print(f"  Rows after filtering: {len(df)}")
    print(f"  Rows skipped: {raw_data_rows - len(df)}")

    if skipped_reasons:
        print(f"\n  Skipped row details ({len(skipped_reasons)} rows):")
        for reason in skipped_reasons[:20]:
            print(f"    {reason}")
        if len(skipped_reasons) > 20:
            print(f"    ... and {len(skipped_reasons) - 20} more")
    else:
        print(f"  No rows were skipped.")

    # Non-numeric values in Value column
    if not df.empty:
        non_numeric = df[df["Value"].apply(is_non_numeric)]
        if not non_numeric.empty:
            print(f"\n  Non-numeric values in Value column ({len(non_numeric)} rows):")
            for idx, row in non_numeric.head(10).iterrows():
                print(f"    Row {idx}: Value='{row['Value']}' | Timestamp='{row['Timestamp']}'")
            if len(non_numeric) > 10:
                print(f"    ... and {len(non_numeric) - 10} more")
        else:
            print(f"\n  All Value entries are numeric.")

    # Timestamp parsing failures
    if not df.empty:
        ts_failures = []
        for idx, row in df.iterrows():
            err = try_parse_timestamp(row["Timestamp"])
            if err:
                ts_failures.append((idx, row["Timestamp"], err))

        if ts_failures:
            print(f"\n  Timestamp parsing failures ({len(ts_failures)} rows):")
            for idx, ts, err in ts_failures[:10]:
                print(f"    Row {idx}: '{ts}' -> {err}")
            if len(ts_failures) > 10:
                print(f"    ... and {len(ts_failures) - 10} more")
        else:
            print(f"\n  All timestamps parsed successfully.")

    print(f"\n{SEPARATOR}")
    print(f"END OF DIAGNOSTICS: {pdf_path.name}")
    print(SEPARATOR)


def main():
    print("B92_ALPO Extraction Validator")
    print(f"Running diagnostics on {len(PDF_FILES)} PDF(s)...")
    print(f"Using parser from: extract_b92.py (unmodified)")

    for pdf_path in PDF_FILES:
        diagnose_pdf(pdf_path)

    print(f"\n\n{'#' * 80}")
    print("VALIDATION COMPLETE - No changes made to parser.")
    print(f"{'#' * 80}")


if __name__ == "__main__":
    main()
