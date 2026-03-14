"""Output formatters for agentlint check.

Three formats:

  text    — colourised human output (default, same as current reporter)
  github  — GitHub Actions workflow commands for inline PR annotations
  json    — machine-readable JSON array

Usage in CLI:
    agentlint check --format github
    agentlint check --format json | jq '.[] | select(.severity=="error")'
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import click
import colorama
from colorama import Fore, Style

from agentlint.core import Diagnostic, Severity

colorama.init(autoreset=True)

_COLOR = {
    Severity.ERROR:   Fore.RED    + Style.BRIGHT,
    Severity.WARNING: Fore.YELLOW + Style.BRIGHT,
    Severity.INFO:    Fore.CYAN,
}
_ICON = {Severity.ERROR: "X", Severity.WARNING: "!", Severity.INFO: "i"}


def _c(text: str, color: str) -> str:
    return f"{color}{text}{Style.RESET_ALL}"


# ---------------------------------------------------------------------------
# text (default)
# ---------------------------------------------------------------------------

def print_text(
    diags: list[Diagnostic],
    *,
    show_hints: bool = True,
    show_info:  bool = True,
    suppressed: int  = 0,
) -> None:
    if not diags and not suppressed:
        click.echo(_c("OK  No issues found.", Fore.GREEN + Style.BRIGHT))
        return

    by_file: dict[Path, list[Diagnostic]] = defaultdict(list)
    for d in diags:
        by_file[d.path].append(d)

    counts: dict[Severity, int] = {s: 0 for s in Severity}
    fixable_count = 0

    for path, file_diags in sorted(by_file.items(), key=lambda x: str(x[0])):
        click.echo(f"\n{Style.BRIGHT}{path}{Style.RESET_ALL}")
        for d in sorted(file_diags, key=lambda x: (x.line or 0, x.severity.value)):
            if d.severity is Severity.INFO and not show_info:
                continue
            loc      = _c(f":{d.line}" if d.line else "", Style.DIM)
            fix_tag  = _c(" [fix]", Fore.GREEN) if d.fix else ""
            click.echo(
                f"  {_ICON[d.severity]} "
                f"{_c(f'{d.severity.value.upper():7}', _COLOR[d.severity])} "
                f"{_c(d.rule_id, Style.DIM)}  {d.message}{loc}{fix_tag}"
            )
            if show_hints and d.hint:
                click.echo(_c(f"    -> {d.hint}", Style.DIM))
            counts[d.severity] += 1
            if d.fix:
                fixable_count += 1

    parts = []
    if counts[Severity.ERROR]:
        parts.append(_c(f"{counts[Severity.ERROR]} error(s)", Fore.RED + Style.BRIGHT))
    if counts[Severity.WARNING]:
        parts.append(_c(f"{counts[Severity.WARNING]} warning(s)", Fore.YELLOW + Style.BRIGHT))
    if counts[Severity.INFO] and show_info:
        parts.append(_c(f"{counts[Severity.INFO]} info", Fore.CYAN))

    total   = sum(counts.values())
    summary = "  ".join(parts) if parts else _c("0 issues", Fore.GREEN)
    click.echo(f"\n{summary}  {_c(f'({total} total)', Style.DIM)}")

    if fixable_count:
        safe_hint  = f"{fixable_count} fixable with `agentlint fix`"
        click.echo(_c(f"  {safe_hint}", Fore.GREEN))

    if suppressed:
        click.echo(_c(f"  {suppressed} existing issue(s) suppressed by baseline "
                      "(run `agentlint baseline status` to review)", Style.DIM))


# ---------------------------------------------------------------------------
# github
# ---------------------------------------------------------------------------

def print_github(diags: list[Diagnostic], *, show_info: bool = True) -> None:
    """Emit GitHub Actions workflow commands.

    GitHub renders these as file annotations in pull requests when the
    workflow step runs with `agentlint check --format github`.
    """
    _level = {
        Severity.ERROR:   "error",
        Severity.WARNING: "warning",
        Severity.INFO:    "notice",
    }
    for d in diags:
        if d.severity is Severity.INFO and not show_info:
            continue
        level = _level[d.severity]
        loc   = f",line={d.line}" if d.line else ""
        # message must not contain newlines in the workflow command
        msg   = d.message.replace("\n", " ")
        if d.hint:
            msg += f" ({d.hint.replace(chr(10), ' ')})"
        click.echo(f"::{level} file={d.path}{loc},title={d.rule_id}::{msg}")


# ---------------------------------------------------------------------------
# json
# ---------------------------------------------------------------------------

def print_json(diags: list[Diagnostic], *, show_info: bool = True) -> None:
    """Print diagnostics as a JSON array to stdout."""
    out = []
    for d in diags:
        if d.severity is Severity.INFO and not show_info:
            continue
        out.append({
            "rule_id":  d.rule_id,
            "severity": d.severity.value,
            "message":  d.message,
            "path":     str(d.path),
            "line":     d.line,
            "hint":     d.hint,
            "fixable":  d.fix is not None,
            "fix_safe": d.fix.safe if d.fix else None,
        })
    click.echo(json.dumps(out, indent=2))
