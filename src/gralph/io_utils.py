"""Wrappers for text file I/O with consistent encoding (UTF-8)."""

from __future__ import annotations

from io import TextIOWrapper
from pathlib import Path
from typing import Any

PathLike = Path | str


def read_text(path: PathLike, errors: str = "strict", **kwargs: Any) -> str:
    """Read path as text with UTF-8 encoding. Forwards extra kwargs to Path.read_text."""
    p = path if isinstance(path, Path) else Path(path)
    return p.read_text(encoding="utf-8", errors=errors, **kwargs)


def write_text(path: PathLike, text: str, **kwargs: Any) -> None:
    """Write text to path with UTF-8 encoding. Forwards extra kwargs to Path.write_text."""
    p = path if isinstance(path, Path) else Path(path)
    p.write_text(text, encoding="utf-8", **kwargs)


def open_text(
    path: PathLike,
    mode: str = "r",
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
    **kwargs: Any,
) -> TextIOWrapper:
    """Open path for text I/O with UTF-8 by default. Use for append/write (e.g. log files)."""
    p = path if isinstance(path, (Path, str)) else Path(path)
    return open(p, mode, encoding=encoding, errors=errors, **kwargs)
