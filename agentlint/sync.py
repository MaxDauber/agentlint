"""Sync engine: generate tool-specific config files from a canonical AGENTS.md."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import yaml

_SYNC_MARKER = "auto-synced from agents.md by agentlint"
_FM_STRIP    = re.compile(r"^---\n.*?\n---\n\s*", re.DOTALL)
_LEAD_H1     = re.compile(r"^#\s+\S[^\n]*\n")


def _strip_fm(content: str) -> str:
    return _FM_STRIP.sub("", content).lstrip()


def _with_notice(content: str) -> str:
    notice = (
        "<!-- Auto-synced from AGENTS.md by agentlint"
        " — edit AGENTS.md, then run: agentlint sync -->\n\n"
    )
    return notice + _strip_fm(content)


def _cursorrules(content: str) -> str:
    fm = yaml.dump(
        {"description": "Auto-synced from AGENTS.md by agentlint",
         "globs": ["**/*"], "alwaysApply": True},
        default_flow_style=False,
    ).strip()
    body = _LEAD_H1.sub("", _strip_fm(content), count=1).lstrip()
    return f"---\n{fm}\n---\n\n{body}"


@dataclass
class Target:
    name:      str
    filename:  str
    transform: Callable[[str], str]


DEFAULT_TARGETS: list[Target] = [
    Target("Claude Code",    "CLAUDE.md",                           _with_notice),
    Target("Cursor",         ".cursorrules",                        _cursorrules),
    Target("GitHub Copilot", ".github/copilot-instructions.md",     _with_notice),
    Target("Cline",          ".clinerules",                         _strip_fm),
    Target("Windsurf",       ".windsurfrules",                      _strip_fm),
]


@dataclass
class SyncResult:
    target:  Target
    dest:    Path
    written: bool
    skipped: bool
    reason:  Optional[str] = None


def sync(
    source: Path,
    root: Path,
    *,
    targets: Optional[list[Target]] = None,
    dry_run: bool = False,
    force: bool = False,
) -> list[SyncResult]:
    raw     = source.read_text(encoding="utf-8")
    results: list[SyncResult] = []

    for target in targets or DEFAULT_TARGETS:
        dest = (root / target.filename).resolve()

        if dest == source.resolve():
            results.append(SyncResult(target, dest, written=False, skipped=True,
                reason="source file"))
            continue

        transformed = target.transform(raw)

        if dest.exists() and not force:
            existing = dest.read_text(encoding="utf-8")
            if _SYNC_MARKER not in existing.lower():
                results.append(SyncResult(target, dest, written=False, skipped=True,
                    reason="unmanaged file — pass --force to overwrite"))
                continue
            if existing == transformed:
                results.append(SyncResult(target, dest, written=False, skipped=True,
                    reason="already up to date"))
                continue

        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(transformed, encoding="utf-8")

        results.append(SyncResult(target, dest, written=True, skipped=False))

    return results
