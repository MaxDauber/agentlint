"""Auto-fix engine for agentlint.

Fixes are attached to Diagnostics as optional Fix objects. Each Fix carries
a text transform (full-file string -> string | None). Returning None means the
fix decided it could not be applied safely to the current file state.

Safe fixes (fix.safe=True) are applied by default.
Unsafe fixes require --unsafe-fixes.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentlint.core import Diagnostic


def apply_fixes(
    diags: list["Diagnostic"],
    *,
    safe_only: bool = True,
    dry_run: bool = False,
) -> dict[Path, int]:
    """Apply auto-fixes grouped by file.

    Returns a mapping of {path: number_of_fixes_applied}.
    With dry_run=True the transforms are computed but files are not written.
    """
    from agentlint.core import Fix  # local import avoids circular deps at module level

    fixable = [
        d for d in diags
        if d.fix is not None
        and (not safe_only or d.fix.safe)
    ]
    if not fixable:
        return {}

    # Group by path so we apply all fixes to the same in-memory buffer
    by_path: dict[Path, list["Diagnostic"]] = defaultdict(list)
    for d in fixable:
        by_path[d.path].append(d)

    counts: dict[Path, int] = {}

    for path, path_diags in sorted(by_path.items()):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            counts[path] = 0
            continue

        original = text
        applied = 0

        for d in path_diags:
            if d.fix is None:
                continue
            result = d.fix.transform(text)
            if result is not None and result != text:
                text = result
                applied += 1

        if not dry_run and text != original:
            path.write_text(text, encoding="utf-8")

        counts[path] = applied

    return counts


# ---------------------------------------------------------------------------
# Reusable transform helpers (imported by rules.py)
# ---------------------------------------------------------------------------

def add_mdc_frontmatter(text: str) -> str | None:
    """Add a default YAML frontmatter block to a .mdc file that lacks one."""
    if re.match(r"^---\s*\n", text):
        return None  # already has frontmatter — bail
    fm = (
        "---\n"
        "description: Agent instructions\n"
        "globs:\n"
        '  - "**/*"\n'
        "alwaysApply: false\n"
        "---\n\n"
    )
    return fm + text


def fix_empty_globs(text: str) -> str | None:
    """Replace an empty globs array with a sensible default."""
    # Matches `globs: []` or `globs:\n  []` etc.
    if not re.search(r"globs\s*:\s*\[\s*\]", text):
        return None
    return re.sub(r"(globs\s*:\s*)\[\s*\]", 'globs:\n  - "**/*"', text)
