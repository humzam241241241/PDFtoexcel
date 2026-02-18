"""
B92_ALPO Monitoring Report Extractor
Extracts sensor name, timestamps, and values from Sanofi B92_ALPO PDF reports.
Outputs a wide-format CSV: Date, Time, Timestamp, <sensor columns...>
"""

import argparse
import logging
import re
import sys
from pathlib import Path

import pandas as pd
import pdfplumber

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logger = logging.getLogger("b92_extractor")

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

DATETIME_LINE_RE = re.compile(
    r"^\s*(?P<ts>(?:"
    r"\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}:\d{2}(?:\.\d+)?"
    r"|"
    r"\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?"
    r"|"
    r"\d{1,2}-[A-Za-z]{3}-\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?"
    r"|"
    r"\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?"
    r"))\s+(?P<rest>.+)$",
    re.IGNORECASE,
)

NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
TIME_WORD_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")

DATE_ONLY_RE = re.compile(
    r"^\s*(?:"
    r"\d{1,2}/\d{1,2}/\d{4}"
    r"|"
    r"\d{4}-\d{2}-\d{2}"
    r"|"
    r"\d{1,2}-[A-Za-z]{3}-\d{4}"
    r"|"
    r"\d{1,2}\s+[A-Za-z]{3}\s+\d{4}"
    r")\s*$"
)

DATETIME_CELL_RE = re.compile(
    r"^\s*(?:"
    r"\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?"
    r"|"
    r"\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?"
    r"|"
    r"\d{1,2}-[A-Za-z]{3}-\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?"
    r"|"
    r"\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?"
    r")\s*$",
    re.IGNORECASE,
)

VIA_MEDIA_PREFIX_RE = re.compile(
    r"\bVIA\b.*?\bMEDIA\b.*?\bAND\b.*?\bFORMULAT(?:ION|IO)?\b",
    re.IGNORECASE,
)

HEADER_KEYWORD_RE = re.compile(r"(?i)^(timestamp|time|date(/time)?|date-time|datetime)$")

# Matches the distinctive sensor path anchor (e.g. "N/01350/TT_33")
SENSOR_PATH_RE = re.compile(r"N/\d{3,}", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_temporal_cell(text: str) -> bool:
    t = str(text or "").strip()
    if not t:
        return False
    if TIME_WORD_RE.match(t):
        return True
    if DATETIME_CELL_RE.match(t):
        return True
    if DATE_ONLY_RE.match(t):
        return True
    return False


def _normalize_sensor_label(label: str) -> str:
    """Canonicalize a sensor label into a stable, single-line column name."""
    if label is None:
        return ""
    s = str(label)
    s = s.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*/\s*", "/", s)
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"(_)\s+(\d+)\b", r"\1\2", s)
    s = re.sub(r"\b([A-Z]{2,})_\s+(\d+)\b", r"\1_\2", s, flags=re.IGNORECASE)

    m = VIA_MEDIA_PREFIX_RE.search(s)
    if m:
        suffix = (s[m.end():] or "").strip()
        s = f"VIA MEDIA AND FORMULATION {suffix}" if suffix else "VIA MEDIA AND FORMULATION"

    s = re.sub(r"\bFORMULATIO\b", "FORMULATION", s, flags=re.IGNORECASE)
    return s.upper().strip()


# ---------------------------------------------------------------------------
# Targeted sensor-column detection using "N/XXXXX/..." anchors
# ---------------------------------------------------------------------------

def _infer_first_data_row_top(words: list[dict]) -> float | None:
    """Y-position of the first data row (time token + numeric value to its right)."""
    if not words:
        return None
    y_tol = 3.0
    candidates: list[float] = []
    for w in words:
        txt = str(w.get("text", "")).strip()
        if not TIME_WORD_RE.match(txt):
            continue
        top = float(w["top"])
        x0 = float(w["x0"])
        for w2 in words:
            if abs(float(w2["top"]) - top) > y_tol:
                continue
            if float(w2["x0"]) <= x0 + 10:
                continue
            if NUMBER_RE.fullmatch(str(w2.get("text", "")).strip()):
                candidates.append(top)
                break
    return min(candidates) if candidates else None


def _find_sensor_columns(page: pdfplumber.page.Page) -> list[str]:
    """Find sensor columns by locating 'N/XXXXX/...' anchor words in the header.

    Every sensor column in these reports follows the pattern:
      VIA MEDIA AND FORMULATION <sensor-path>
    where <sensor-path> starts with N/ followed by a numeric tag.

    We find those N/ words, sort left-to-right, collect continuation words
    below each (for multi-line tags like 'AT-C' + 'OND_01'), and build the
    full canonical column name.
    """
    words = page.extract_words(use_text_flow=True) or []
    if not words:
        return []

    # Find the y boundary between header and data
    first_data_top = _infer_first_data_row_top(words)
    if first_data_top is None:
        try:
            tables = page.find_tables()
            if tables:
                first_data_top = tables[0].bbox[1]
        except Exception:
            pass
    if first_data_top is None:
        first_data_top = page.height * 0.4

    header_words = [w for w in words if float(w["top"]) < first_data_top - 2.0]
    if not header_words:
        return []

    # Find words containing the sensor path anchor pattern (N/01350/...)
    n_anchors = []
    for w in header_words:
        t = str(w.get("text", "")).strip()
        if SENSOR_PATH_RE.search(t):
            n_anchors.append(w)

    if not n_anchors:
        logger.debug("No N/XXXXX/ sensor-path anchors found in header area")
        return []

    n_anchors.sort(key=lambda w: float(w["x0"]))

    x_tol = 22.0
    used_ids: set[int] = set()
    results: list[str] = []

    for anchor in n_anchors:
        if id(anchor) in used_ids:
            continue
        ax = float(anchor["x0"])
        ay = float(anchor["top"])

        # Continuation words directly below anchor in the same x-band
        continuations = sorted(
            [
                w for w in header_words
                if id(w) not in used_ids
                and abs(float(w["x0"]) - ax) <= x_tol
                and ay + 1.0 < float(w["top"]) < ay + 35.0
            ],
            key=lambda w: float(w["top"]),
        )

        parts = [str(anchor["text"]).strip()]
        used_ids.add(id(anchor))
        for cw in continuations:
            ct = str(cw["text"]).strip()
            if SENSOR_PATH_RE.search(ct):
                break
            parts.append(ct)
            used_ids.add(id(cw))

        tag = " ".join(parts)
        name = _normalize_sensor_label(f"VIA MEDIA AND FORMULATION {tag}")
        results.append(name)

    # Dedupe preserving left-to-right order
    seen: set[str] = set()
    unique: list[str] = []
    for r in results:
        if r not in seen:
            seen.add(r)
            unique.append(r)

    logger.info("Detected %d sensor column(s): %s", len(unique), unique)
    return unique


# ---------------------------------------------------------------------------
# Table-based data extraction (uses pre-detected column names)
# ---------------------------------------------------------------------------

def _find_data_start(rows: list[list]) -> int | None:
    for i, r in enumerate(rows):
        if not r or len(r) < 2:
            continue
        has_temporal = any(
            _is_temporal_cell(str(r[k] or "")) for k in range(min(3, len(r)))
        )
        if not has_temporal:
            continue
        has_number = any(
            NUMBER_RE.fullmatch(str(c or "").strip())
            for c in r[1:] if str(c or "").strip()
        )
        if has_number:
            return i
    return None


def _identify_key_columns(data_row: list) -> set[int]:
    return {k for k, cell in enumerate(data_row) if _is_temporal_cell(str(cell or ""))}


def _build_timestamp(row: list, key_cols: list[int]) -> str:
    parts = [str(row[k] or "").strip() for k in key_cols if k < len(row)]
    return " ".join(p for p in parts if p).strip()


def _extract_table_data(table_obj, sensor_labels: list[str]) -> list[dict]:
    """Extract data rows from a pdfplumber table, mapping values to sensor_labels."""
    rows = table_obj.extract() or []
    if not rows:
        return []

    data_start = _find_data_start(rows)
    if data_start is None:
        logger.debug("  table: could not find data start row")
        return []

    first_data_row = rows[data_start]
    key_col_idxs = _identify_key_columns(first_data_row)
    key_cols_sorted = sorted(key_col_idxs)
    value_col_idxs = [
        i for i in range(len(first_data_row)) if i not in key_col_idxs
    ]

    logger.debug(
        "  table: data_start=%d, key_cols=%s, value_cols=%d, sensor_labels=%d",
        data_start, key_cols_sorted, len(value_col_idxs), len(sensor_labels),
    )

    extracted: list[dict] = []
    for r in rows[data_start:]:
        if not r or len(r) < 2:
            continue
        ts_text = _build_timestamp(r, key_cols_sorted)
        if not ts_text or HEADER_KEYWORD_RE.match(ts_text):
            continue

        for j, col_idx in enumerate(value_col_idxs):
            if j >= len(sensor_labels):
                break
            if col_idx >= len(r):
                continue
            val = str(r[col_idx] or "").strip()
            if not val:
                continue
            m = NUMBER_RE.search(val)
            if not m:
                continue
            extracted.append({
                "Timestamp": ts_text,
                "Sensor": sensor_labels[j],
                "Value": m.group(0),
            })

    return extracted


# ---------------------------------------------------------------------------
# Sensor-name extraction (above-table header, for single-sensor fallback)
# ---------------------------------------------------------------------------

def extract_sensor_name(page: pdfplumber.page.Page, table_top: float) -> str | None:
    header_crop = page.crop((0, 0, page.width, table_top))
    text = header_crop.extract_text()
    if not text:
        return None

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    skip_patterns = re.compile(
        r"^(page\s+\d|date|time|printed|report|b92[_ ]alpo|period|from\s|to\s)",
        re.IGNORECASE,
    )
    meaningful = [ln for ln in lines if not skip_patterns.match(ln)]
    if not meaningful:
        meaningful = lines

    return " ".join(meaningful).strip() or None


# ---------------------------------------------------------------------------
# Single-PDF parsing
# ---------------------------------------------------------------------------

def parse_pdf(pdf_path: Path) -> pd.DataFrame:
    """Parse one B92_ALPO monitoring PDF -> DataFrame[Timestamp, Sensor, Value]."""
    all_rows: list[dict] = []
    sensor_columns: list[str] | None = None
    sensor_name: str | None = None
    pages_table_ok = 0
    pages_text_ok = 0
    mismatch_pages: set[int] = set()

    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            page_num = page_idx + 1

            # ----------------------------------------------------------
            # Phase 1 (once): detect sensor column names from page 1
            # ----------------------------------------------------------
            if sensor_columns is None:
                sensor_columns = _find_sensor_columns(page)

            if sensor_name is None:
                try:
                    tbls = page.find_tables()
                except Exception:
                    tbls = []
                if tbls:
                    sensor_name = extract_sensor_name(page, tbls[0].bbox[1])
                if not sensor_name:
                    sensor_name = pdf_path.stem

            if not sensor_columns:
                logger.debug(
                    "%s – page %d: no sensor columns detected yet",
                    pdf_path.name, page_num,
                )

            # ----------------------------------------------------------
            # Phase 2: extract data — table first, text fallback
            # ----------------------------------------------------------

            # Strategy 1: Table extraction
            page_added = 0
            if sensor_columns:
                tables: list = []
                for settings in [
                    {},
                    {"vertical_strategy": "text", "horizontal_strategy": "text"},
                ]:
                    try:
                        found = (
                            page.find_tables(table_settings=settings)
                            if settings else page.find_tables()
                        )
                    except Exception:
                        found = []
                    if found:
                        tables = found
                        break

                for tbl in tables[:3]:
                    rows = _extract_table_data(tbl, sensor_columns)
                    if rows:
                        all_rows.extend(rows)
                        page_added += len(rows)
                        break

            if page_added > 0:
                pages_table_ok += 1
                logger.debug(
                    "%s – page %d: %d cells via table",
                    pdf_path.name, page_num, page_added,
                )
                continue

            # Strategy 2: Text-line extraction
            text = page.extract_text() or ""
            if not text:
                logger.warning("%s – page %d: no text", pdf_path.name, page_num)
                continue

            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            page_rows_before = len(all_rows)

            for line in lines:
                if not line or not line[0].isdigit():
                    continue
                match = DATETIME_LINE_RE.match(line)
                if not match:
                    continue

                ts_text = match.group("ts").strip()
                rest = match.group("rest")
                if not ts_text or not rest:
                    continue

                values = NUMBER_RE.findall(rest)
                if not values:
                    continue

                if sensor_columns:
                    if len(values) != len(sensor_columns):
                        if page_num not in mismatch_pages:
                            mismatch_pages.add(page_num)
                            logger.warning(
                                "%s – page %d: values/columns mismatch (%d vs %d)",
                                pdf_path.name, page_num,
                                len(values), len(sensor_columns),
                            )
                    take = min(len(values), len(sensor_columns))
                    for i in range(take):
                        all_rows.append({
                            "Timestamp": ts_text,
                            "Sensor": sensor_columns[i],
                            "Value": values[i],
                        })
                else:
                    all_rows.append({
                        "Timestamp": ts_text,
                        "Sensor": _normalize_sensor_label(sensor_name),
                        "Value": values[0],
                    })

            page_rows_text = len(all_rows) - page_rows_before
            if page_rows_text > 0:
                pages_text_ok += 1
                logger.debug(
                    "%s – page %d: %d rows via text",
                    pdf_path.name, page_num, page_rows_text,
                )

    if not all_rows:
        logger.error("%s – no data rows extracted", pdf_path.name)
        return pd.DataFrame(columns=["Timestamp", "Sensor", "Value"])

    df = pd.DataFrame(all_rows)
    logger.info(
        "%s – %d rows (table pages=%d, text pages=%d, columns=%s)",
        pdf_path.name, len(df), pages_table_ok, pages_text_ok,
        len(sensor_columns) if sensor_columns else "n/a",
    )
    return df


# ---------------------------------------------------------------------------
# Batch / output
# ---------------------------------------------------------------------------

def _dedupe_columns(df: pd.DataFrame, key_cols: list[str]) -> pd.DataFrame:
    cols = list(df.columns)
    if len(set(cols)) == len(cols):
        return df
    out = df.copy()
    for name in list(dict.fromkeys(cols)):
        if name in key_cols:
            continue
        idxs = [i for i, c in enumerate(out.columns) if c == name]
        if len(idxs) <= 1:
            continue
        combined = None
        for i in idxs:
            s = out.iloc[:, i]
            combined = s if combined is None else combined.combine_first(s)
        out = out.drop(columns=[name])
        out[name] = combined
    sensor_cols = [c for c in out.columns if c not in key_cols]
    return out[key_cols + sensor_cols]


def process_paths(paths: list[Path], output: Path) -> None:
    pdf_files: list[Path] = []
    for p in paths:
        if p.is_dir():
            pdf_files.extend(sorted(p.glob("*.pdf")))
        elif p.suffix.lower() == ".pdf":
            pdf_files.append(p)
        else:
            logger.warning("Skipping non-PDF path: %s", p)

    if not pdf_files:
        logger.error("No PDF files found in the provided paths.")
        sys.exit(1)

    logger.info("Found %d PDF(s) to process", len(pdf_files))

    frames: list[pd.DataFrame] = []
    for pdf_path in pdf_files:
        try:
            df = parse_pdf(pdf_path)
            if df.empty:
                logger.error("%s – no rows; skipping", pdf_path.name)
            else:
                frames.append(df)
        except Exception:
            logger.exception("Failed to parse %s", pdf_path.name)

    if not frames:
        logger.error("No data extracted from any file.")
        sys.exit(1)

    combined = pd.concat(frames, ignore_index=True)
    combined["Sensor"] = combined["Sensor"].astype(str).map(_normalize_sensor_label)
    combined["Timestamp"] = combined["Timestamp"].astype(str).str.strip()

    dt = pd.to_datetime(combined["Timestamp"], errors="coerce", dayfirst=True)
    combined["Date"] = dt.dt.strftime("%Y-%m-%d")
    combined["Time"] = dt.dt.strftime("%H:%M:%S")

    combined["Value"] = (
        combined["Value"].astype(str).str.replace(",", ".", regex=False)
    )
    combined["Value"] = pd.to_numeric(combined["Value"], errors="coerce")

    wide = (
        combined.pivot_table(
            index=["Date", "Time", "Timestamp"],
            columns="Sensor",
            values="Value",
            aggfunc="first",
        )
        .reset_index()
    )
    wide.columns.name = None

    output.parent.mkdir(parents=True, exist_ok=True)
    key_cols = ["Date", "Time", "Timestamp"]

    if output.exists():
        try:
            existing = pd.read_csv(output)
            rename_map = {
                c: _normalize_sensor_label(c)
                for c in existing.columns if c not in key_cols
            }
            existing = existing.rename(columns=rename_map)
            existing = _dedupe_columns(existing, key_cols=key_cols)
            wide = wide.merge(existing, on=key_cols, how="outer", suffixes=("", "_old"))
            for c in list(wide.columns):
                if not c.endswith("_old"):
                    continue
                base = c[:-len("_old")]
                if base in wide.columns:
                    wide[base] = wide[base].combine_first(wide[c])
                    wide = wide.drop(columns=[c])
                else:
                    wide = wide.rename(columns={c: base})
        except Exception:
            logger.exception("Failed to merge with existing output; rewriting.")

    sensor_cols = sorted(c for c in wide.columns if c not in key_cols)
    wide = wide[key_cols + sensor_cols]
    wide = wide.sort_values(by=["Date", "Time", "Timestamp"], kind="stable")
    wide.to_csv(output, index=False)
    logger.info("Wrote %d rows to %s", len(wide), output)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract B92_ALPO monitoring data from PDF reports to CSV.",
    )
    parser.add_argument(
        "inputs", nargs="+", type=Path,
        help="One or more PDF files or folders containing PDFs.",
    )
    parser.add_argument(
        "-o", "--output", type=Path,
        default=Path(__file__).parent / "outputs" / "b92_output.csv",
        help="Output CSV path (default: project_dir/outputs/b92_output.csv).",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable debug-level logging.",
    )
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format=LOG_FORMAT)

    output_path = args.output
    if not output_path.is_absolute() and output_path.parent == Path("."):
        output_path = Path(__file__).parent / "outputs" / output_path.name

    process_paths(args.inputs, output_path)


if __name__ == "__main__":
    main()
