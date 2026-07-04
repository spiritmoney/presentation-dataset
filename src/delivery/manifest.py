"""Generate CSV manifest from FileRecord list."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.metadata.schema import MANIFEST_COLUMNS, FileRecord


def write_manifest(records: list[FileRecord], output_path: Path) -> Path:
    rows = [r.to_manifest_row() for r in records]
    df = pd.DataFrame(rows, columns=MANIFEST_COLUMNS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    return output_path


def write_excel_manifest(records: list[FileRecord], output_path: Path) -> Path:
    rows = [r.to_manifest_row() for r in records]
    df = pd.DataFrame(rows, columns=MANIFEST_COLUMNS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(output_path, index=False, sheet_name="manifest")
    return output_path
