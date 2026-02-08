"""Cross-platform notifications (sound + toast), best-effort."""

from __future__ import annotations

import subprocess
import sys


def _run_quiet(*cmd: str) -> None:
    """Fire-and-forget subprocess, ignore failures."""
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError):
        pass


def notify_done(message: str = "GRALPH has completed all tasks!") -> None:
    """Play a success sound and show a notification toast."""
    if sys.platform == "darwin":
        _run_quiet("afplay", "/System/Library/Sounds/Glass.aiff")
        _run_quiet(
            "osascript", "-e",
            f'display notification "{message}" with title "GRALPH"',
        )
    elif sys.platform.startswith("linux"):
        _run_quiet("notify-send", "GRALPH", message)
        _run_quiet("paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga")
    elif sys.platform == "win32":
        _run_quiet(
            "powershell.exe", "-Command",
            "[System.Media.SystemSounds]::Asterisk.Play()",
        )


def notify_error(message: str = "GRALPH encountered an error") -> None:
    """Play an error sound and show a notification toast."""
    if sys.platform == "darwin":
        _run_quiet(
            "osascript", "-e",
            f'display notification "{message}" with title "GRALPH - Error"',
        )
    elif sys.platform.startswith("linux"):
        _run_quiet("notify-send", "-u", "critical", "GRALPH - Error", message)
    elif sys.platform == "win32":
        _run_quiet(
            "powershell.exe", "-Command",
            "[System.Media.SystemSounds]::Hand.Play()",
        )
