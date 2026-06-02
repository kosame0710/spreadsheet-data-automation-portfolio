"""
report.py — Turn a CleanResult into deliverables.

Produces:
  * A formatted multi-sheet Excel workbook (Summary, Clean Data, Rejected Rows,
    Issue Log) with styled headers, frozen panes, auto-fit columns and a
    currency format on money columns.
  * A plain-text run report (also printed to the console) so the result is
    legible even without opening Excel.

openpyxl is used for the Excel styling. If it is unavailable the caller can
still get CSV + text outputs (see cleaner/main), so the demo degrades gracefully.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import config
from cleaner import CleanResult


HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(color="FFFFFF", bold=True)
TITLE_FONT = Font(size=14, bold=True, color="1F4E78")
MONEY_FORMAT = '#,##0.00'
MONEY_COLUMNS = {"unit_price_original", "unit_price_usd", "line_total_usd"}


def _autofit_and_style(ws, df: pd.DataFrame, header_row: int = 1) -> None:
    """Apply header styling, freeze panes and approximate column auto-fit."""
    for col_idx, col_name in enumerate(df.columns, start=1):
        cell = ws.cell(row=header_row, column=col_idx)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")

        # Width from the longest value in the column (capped for sanity).
        max_len = max(
            [len(str(col_name))]
            + [len(str(v)) for v in df[col_name].head(200).tolist()]
        )
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 3, 40)

        if col_name in MONEY_COLUMNS:
            for r in range(header_row + 1, header_row + 1 + len(df)):
                ws.cell(row=r, column=col_idx).number_format = MONEY_FORMAT

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)


def _write_summary_sheet(ws, result: CleanResult) -> None:
    """Build a human-readable summary sheet from the run statistics."""
    s = result.stats
    rows = [
        ("Spreadsheet Cleaner — Run Summary", ""),
        ("", ""),
        ("Source files merged", ", ".join(s.get("source_files", []))),
        ("Rows read (raw)", s.get("rows_in", 0)),
        ("Rows in clean dataset", s.get("rows_clean", 0)),
        ("Rows rejected (failed validation)", s.get("rows_rejected", 0)),
        ("Duplicate rows removed", s.get("duplicates_removed", 0)),
        ("Total issues logged", s.get("issues_logged", 0)),
        ("", ""),
        (f"Total revenue ({config.REPORTING_CURRENCY})", s.get("total_revenue_usd", 0)),
    ]
    for r_idx, (label, value) in enumerate(rows, start=1):
        ws.cell(row=r_idx, column=1, value=label)
        ws.cell(row=r_idx, column=2, value=value)
    ws.cell(row=1, column=1).font = TITLE_FONT
    ws.column_dimensions["A"].width = 36
    ws.column_dimensions["B"].width = 48


def write_excel(result: CleanResult, out_path: Path) -> None:
    """Write the full formatted workbook to *out_path*."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sheets = {
        "Clean Data": result.clean,
        "Rejected Rows": result.rejected.drop(columns=["_reject_reasons"], errors="ignore")
        if "_reject_reasons" not in result.rejected.columns
        else result.rejected,
        "Issue Log": pd.DataFrame(result.issues),
    }

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        # Summary first.
        pd.DataFrame().to_excel(writer, sheet_name="Summary", index=False, header=False)
        _write_summary_sheet(writer.sheets["Summary"], result)

        for name, df in sheets.items():
            safe = df if not df.empty else pd.DataFrame({"(none)": []})
            safe.to_excel(writer, sheet_name=name, index=False)
            if not df.empty:
                _autofit_and_style(writer.sheets[name], df)


def build_text_report(result: CleanResult) -> str:
    """Compose a plain-text report summarizing the run and the top issues."""
    s = result.stats
    lines = [
        "=" * 64,
        " SPREADSHEET CLEANER — RUN REPORT",
        "=" * 64,
        f" Source files merged : {', '.join(s.get('source_files', []))}",
        f" Rows read (raw)     : {s.get('rows_in', 0)}",
        f" Rows clean          : {s.get('rows_clean', 0)}",
        f" Rows rejected       : {s.get('rows_rejected', 0)}",
        f" Duplicates removed  : {s.get('duplicates_removed', 0)}",
        f" Issues logged       : {s.get('issues_logged', 0)}",
        f" Total revenue (USD) : {s.get('total_revenue_usd', 0):,.2f}",
        "-" * 64,
        " Issue log (data quality problems found and how they were handled):",
        "-" * 64,
    ]
    for i, issue in enumerate(result.issues, start=1):
        lines.append(
            f" {i:>2}. [{issue['source_file']}] order {issue['row_id']} "
            f"/ {issue['column']}: {issue['problem']} -> {issue['action']}"
        )
    lines.append("=" * 64)
    return "\n".join(lines)


def write_outputs(result: CleanResult, output_dir: Path) -> dict:
    """Write all deliverables and return a dict of the paths produced."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}

    excel_path = output_dir / "cleaned_sales.xlsx"
    write_excel(result, excel_path)
    paths["excel"] = excel_path

    # CSVs alongside Excel for clients who prefer raw text / git diffs.
    clean_csv = output_dir / "cleaned_sales.csv"
    result.clean.to_csv(clean_csv, index=False, encoding="utf-8-sig")
    paths["clean_csv"] = clean_csv

    if not result.rejected.empty:
        rejected_csv = output_dir / "rejected_rows.csv"
        result.rejected.to_csv(rejected_csv, index=False, encoding="utf-8-sig")
        paths["rejected_csv"] = rejected_csv

    report_text = build_text_report(result)
    report_path = output_dir / "run_report.txt"
    report_path.write_text(report_text, encoding="utf-8")
    paths["report"] = report_path

    return paths
