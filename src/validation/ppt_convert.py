"""Convert legacy .ppt files to .pptx using LibreOffice."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

CONVERTERS = ("soffice", "libreoffice")


def convert_ppt_to_pptx(path: Path, out_dir: Path) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for binary in CONVERTERS:
        if not shutil.which(binary):
            continue
        try:
            subprocess.run(
                [binary, "--headless", "--convert-to", "pptx", "--outdir", str(out_dir), str(path)],
                check=True,
                capture_output=True,
                timeout=180,
            )
            out = out_dir / f"{path.stem}.pptx"
            if out.exists() and out.stat().st_size > 0:
                return out
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            continue
    return None
