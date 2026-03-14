"""Token counting with optional tiktoken; falls back to a chars/4 heuristic."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

# (warn_threshold, error_threshold) in tokens
FILE_BUDGETS: dict[str, tuple[int, int]] = {
    "CLAUDE.md":                       (4_000, 8_000),
    "AGENTS.md":                       (4_000, 8_000),
    ".cursorrules":                    (4_000, 8_000),
    ".clinerules":                     (4_000, 8_000),
    ".windsurfrules":                  (4_000, 8_000),
    ".github/copilot-instructions.md": (2_000, 4_000),
    "GEMINI.md":                       (4_000, 8_000),
    "JULES.md":                        (4_000, 8_000),
}

LINE_BUDGETS: dict[str, tuple[int, int]] = {
    "CLAUDE.md": (300, 500),
    "AGENTS.md": (300, 600),
}


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """Return token count. Uses tiktoken when installed; falls back to chars/4."""
    try:
        import tiktoken
        try:    enc = tiktoken.encoding_for_model(model)
        except KeyError: enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return max(0, len(text) // 4)


def budget_for(filename: str) -> Optional[tuple[int, int]]:
    return next((v for k, v in FILE_BUDGETS.items() if filename.endswith(k)), None)


def line_budget_for(filename: str) -> Optional[tuple[int, int]]:
    return next((v for k, v in LINE_BUDGETS.items() if filename.endswith(k)), None)
