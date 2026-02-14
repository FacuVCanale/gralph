"""Shared error classification for engine output and orchestration retries."""

from __future__ import annotations

RATE_LIMIT_PATTERNS: tuple[str, ...] = (
    "rate limit",
    "rate_limit",
    "usage limit",
    "you've hit your limit",
    "quota",
    "429",
    "too many requests",
)

POLICY_BLOCK_PATTERNS: tuple[str, ...] = (
    "blocked by policy",
    "read-only sandbox",
    "approval_policy",
)

MERGE_CONFLICT_PATTERNS: tuple[str, ...] = (
    "automatic merge failed",
    "conflict (content)",
    "conflict in ",
    "merge conflict",
)

EXTERNAL_FAILURE_PATTERNS: tuple[str, ...] = (
    "buninstallfailederror",
    "command not found",
    "commandnotfoundexception",
    "objectnotfound:",
    "enoent",
    "eacces",
    "permission denied",
    "network",
    "timeout",
    "tls",
    "econnreset",
    "etimedout",
    "lockfile",
    "install",
    "certificate",
    "ssl",
    "stalled",
)


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(pattern in lower for pattern in patterns)


def looks_like_rate_limit(text: str) -> bool:
    """Return ``True`` when text matches a rate/usage/quota limit."""
    if not text:
        return False
    return _contains_any(text, RATE_LIMIT_PATTERNS)


def looks_like_policy_block(text: str) -> bool:
    """Return ``True`` when text indicates policy/sandbox blocking."""
    if not text:
        return False
    return _contains_any(text, POLICY_BLOCK_PATTERNS)


def looks_like_merge_conflict(text: str) -> bool:
    """Return ``True`` for textual git merge conflict failures."""
    if not text:
        return False
    return _contains_any(text, MERGE_CONFLICT_PATTERNS)


def looks_like_external_failure(text: str) -> bool:
    """Return ``True`` when failure looks infrastructural/external."""
    if not text:
        return False
    if looks_like_merge_conflict(text):
        return True
    if looks_like_rate_limit(text):
        return True
    if looks_like_policy_block(text):
        return True
    return _contains_any(text, EXTERNAL_FAILURE_PATTERNS)

