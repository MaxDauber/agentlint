"""Baseline management for agentlint.

A baseline is a snapshot of known violations stored in `.agentlint-baseline.json`.
When ``--baseline`` is passed to ``agentlint check``, violations already in the
baseline are suppressed — only *new* violations fail the check.

Workflow:
    1.  agentlint baseline create        # snapshot current violations
    2.  git add .agentlint-baseline.json # commit the baseline
    3.  agentlint check --baseline       # CI only fails on new issues
    4.  agentlint baseline update        # shrink baseline as issues are fixed
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentlint.core import Diagnostic

BASELINE_FILE = ".agentlint-baseline.json"


def _fingerprint(d: "Diagnostic") -> str:
    """Stable string key for a diagnostic."""
    return f"{d.rule_id}|{d.path}|{d.line}|{d.message}"


@dataclass
class Baseline:
    """A snapshot of known violations."""
    fingerprints: set[str] = field(default_factory=set)


def create_baseline(diags: list["Diagnostic"]) -> Baseline:
    """Build a Baseline from the current set of diagnostics."""
    return Baseline(fingerprints={_fingerprint(d) for d in diags})


def filter_new(
    diags: list["Diagnostic"],
    baseline: "Baseline",
) -> tuple[list["Diagnostic"], int]:
    """Split diagnostics into (new, suppressed_count).

    new              — violations absent from the baseline (fail the check)
    suppressed_count — number of violations already in the baseline (silenced)
    """
    new: list["Diagnostic"] = []
    suppressed = 0
    for d in diags:
        if _fingerprint(d) in baseline.fingerprints:
            suppressed += 1
        else:
            new.append(d)
    return new, suppressed


def save_baseline(baseline: Baseline, directory: Path = Path(".")) -> Path:
    """Write the baseline to a JSON file. Returns the path written."""
    dest = directory / BASELINE_FILE
    dest.write_text(
        json.dumps(sorted(baseline.fingerprints), indent=2) + "\n",
        encoding="utf-8",
    )
    return dest


def load_baseline(directory: Path = Path(".")) -> Baseline | None:
    """Load a baseline from disk. Returns None if the file is absent or corrupt."""
    path = directory / BASELINE_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return Baseline(fingerprints=set(data))
    except (json.JSONDecodeError, OSError):
        pass
    return None
