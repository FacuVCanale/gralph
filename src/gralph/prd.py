"""PRD handling: extract prd-id, setup run directory, find PRD files."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from gralph.io_utils import read_text


def extract_prd_id(prd_file: Path) -> str:
    """Extract the prd-id from a PRD markdown file.

    Looks for a line starting with ``prd-id:`` and returns the value.
    """
    if not prd_file.is_file():
        return ""
    for line in read_text(prd_file).splitlines():
        if line.startswith("prd-id:"):
            return line.split(":", 1)[1].strip()
    return ""


def setup_run_dir(prd_id: str) -> Path:
    """Create ``artifacts/prd/<prd_id>/reports`` and return the run dir."""
    run_dir = Path("artifacts/prd") / prd_id
    (run_dir / "reports").mkdir(parents=True, exist_ok=True)
    return run_dir


def find_prd_file() -> Path | None:
    """Search common locations for a PRD file and return the first match."""
    candidates = ["PRD.md", "prd.md"]
    for name in candidates:
        p = Path(name)
        if p.is_file():
            return p
    # Also check tasks/prd-*.md
    for p in Path("tasks").glob("prd-*.md"):
        if p.is_file():
            return p
    return None


def copy_prd_to_run_dir(prd_file: Path, run_dir: Path) -> None:
    """Copy the PRD file into the run directory as ``PRD.md``."""
    shutil.copy2(prd_file, run_dir / "PRD.md")


def slugify(text: str, max_len: int = 50) -> str:
    """Convert text to a URL/branch-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len]
