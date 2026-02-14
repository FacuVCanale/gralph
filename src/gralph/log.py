"""Logging utilities with colored output via Rich."""

from __future__ import annotations

from rich.console import Console

console = Console(highlight=False)
_err_console = Console(highlight=False, stderr=True)

_verbose = False


def set_verbose(enabled: bool) -> None:
    global _verbose
    _verbose = enabled


def info(msg: str) -> None:
    console.print(f"[blue]\\[INFO][/blue] {msg}")


def success(msg: str) -> None:
    console.print(f"[green]\\[OK][/green] {msg}")


def warn(msg: str) -> None:
    console.print(f"[yellow]\\[WARN][/yellow] {msg}")


def error(msg: str) -> None:
    _err_console.print(f"[red]\\[ERROR][/red] {msg}")


def debug(msg: str) -> None:
    if _verbose:
        console.print(f"[dim]\\[DEBUG] {msg}[/dim]")
