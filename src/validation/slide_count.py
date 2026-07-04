"""Validate presentation file integrity and count slides/pages."""

from __future__ import annotations

from pathlib import Path

from src.metadata.schema import FileFormat


class ValidationResult:
    def __init__(
        self,
        valid: bool,
        slide_count: int = 0,
        error: str | None = None,
    ):
        self.valid = valid
        self.slide_count = slide_count
        self.error = error


def count_slides(path: Path) -> ValidationResult:
    ext = path.suffix.lower()
    try:
        if ext == ".pptx":
            from pptx import Presentation

            prs = Presentation(str(path))
            count = len(prs.slides)
            return ValidationResult(valid=True, slide_count=count)

        if ext == ".pdf":
            import fitz

            doc = fitz.open(str(path))
            count = doc.page_count
            doc.close()
            return ValidationResult(valid=True, slide_count=count)

        if ext == ".ppt":
            # Legacy PPT requires additional tooling (e.g., libreoffice conversion)
            return ValidationResult(
                valid=False,
                error="Legacy .ppt requires conversion — not yet implemented",
            )

        return ValidationResult(valid=False, error=f"Unsupported extension: {ext}")
    except Exception as e:
        return ValidationResult(valid=False, error=str(e))


def validate_file(path: Path, min_slides: int = 5) -> ValidationResult:
    if not path.exists():
        return ValidationResult(valid=False, error="File not found")

    result = count_slides(path)
    if not result.valid:
        return result

    if result.slide_count < min_slides:
        return ValidationResult(
            valid=False,
            slide_count=result.slide_count,
            error=f"Slide count {result.slide_count} below minimum {min_slides}",
        )

    return result
