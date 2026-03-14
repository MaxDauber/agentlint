"""Terminal output — click + colorama.

Supports three output formats:
  terminal  — colourised, human-readable (default)
  github    — ::error/::warning annotations for GitHub Actions
  json      — machine-readable JSON array
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import click
import colorama
from colorama import Fore, Style

colorama.init(autoreset=True)

from agentlint.core import Diagnostic, Severity

_COLOR = {
    Severity.ERROR:   Fore.RED   + Style.BRIGHT,
    Severity.WARNING: Fore.YELLOW + Style.BRIGHT,
    Severity.INFO:    Fore.CYAN,
}
_ICON = {Severity.ERROR: "X", Severity.WARNING: "!", Severity.INFO: "i"}


def _c(text: str, color: str) -> str:
    return f"{color}{text}{Style.RESET_ALL}"


# ---------------------------------------------------------------------------
# Terminal (default)
# ---------------------------------------------------------------------------

def print_diagnostics(
    diags: list[Diagnostic],
    *,
    show_hints: bool = True,
    show_info: bool  = True,
    suppressed: int  = 0,
) -> None:
    if not diags:
        msg = _c("OK  No issues found.", Fore.GREEN + Style.BRIGHT)
        if suppressed:
            msg += _c(f"  ({suppressed} suppressed by baseline)", Style.DIM)
        click.echo(msg)
        return

    by_file: dict[Path, list[Diagnostic]] = defaultdict(list)
    for d in diags:
        by_file[d.path].append(d)

    counts: dict[Severity, int] = {s: 0 for s in Severity}
    fixable = 0

    for path, file_diags in sorted(by_file.items(), key=lambda x: str(x[0])):
        click.echo(f"\n{Style.BRIGHT}{path}{Style.RESET_ALL}")
        for d in sorted(file_diags, key=lambda x: (x.line or 0, x.severity.value)):
            if d.severity is Severity.INFO and not show_info:
                continue
            loc      = _c(f":{d.line}" if d.line else "", Style.DIM)
            fix_tag  = _c(" [fixable]", Fore.GREEN) if d.fix else ""
            click.echo(
                f"  {_ICON[d.severity]} "
                f"{_c(f'{d.severity.value.upper():7}', _COLOR[d.severity])} "
                f"{_c(d.rule_id, Style.DIM)}  {d.message}{loc}{fix_tag}"
            )
            if show_hints and d.hint:
                click.echo(_c(f"    -> {d.hint}", Style.DIM))
            counts[d.severity] += 1
            if d.fix:
                fixable += 1

    parts = []
    if counts[Severity.ERROR]:
        parts.append(_c(f"{counts[Severity.ERROR]} error(s)",   Fore.RED    + Style.BRIGHT))
    if counts[Severity.WARNING]:
        parts.append(_c(f"{counts[Severity.WARNING]} warning(s)", Fore.YELLOW + Style.BRIGHT))
    if counts[Severity.INFO] and show_info:
        parts.append(_c(f"{counts[Severity.INFO]} info",          Fore.CYAN))

    total   = sum(counts.values())
    summary = "  ".join(parts) if parts else _c("0 issues", Fore.GREEN)
    click.echo(f"\n{summary}  {_c(f'({total} total)', Style.DIM)}")

    if fixable:
        click.echo(_c(f"  {fixable} fixable — run: agentlint fix", Fore.GREEN))
    if suppressed:
        click.echo(_c(f"  {suppressed} suppressed by baseline", Style.DIM))


# ---------------------------------------------------------------------------
# GitHub Actions workflow commands
# ---------------------------------------------------------------------------

def print_github_annotations(
    diags: list[Diagnostic],
    *,
    show_info: bool = True,
) -> None:
    """Emit ::error/::warning/::notice annotations consumed by GitHub Actions."""
    level_map = {
        Severity.ERROR:   "error",
        Severity.WARNING: "warning",
        Severity.INFO:    "notice",
    }
    for d in sorted(diags, key=lambda x: (str(x.path), x.line or 0)):
        if d.severity is Severity.INFO and not show_info:
            continue
        level = level_map[d.severity]
        # Escape % :: \n in the message per GitHub docs
        msg = d.message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        title = d.rule_id
        file  = str(d.path).replace("\\", "/")
        parts = [f"file={file}", f"title={title}"]
        if d.line:
            parts.append(f"line={d.line}")
        click.echo(f"::{level} {','.join(parts)}::{msg}")


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

def print_json_output(
    diags: list[Diagnostic],
    *,
    show_info: bool = True,
) -> None:
    """Emit a JSON array of diagnostics to stdout."""
    records = []
    for d in diags:
        if d.severity is Severity.INFO and not show_info:
            continue
        records.append({
            "rule":     d.rule_id,
            "severity": d.severity.value,
            "file":     str(d.path),
            "line":     d.line,
            "message":  d.message,
            "hint":     d.hint,
            "fixable":  d.fix is not None,
        })
    click.echo(json.dumps(records, indent=2))


# ---------------------------------------------------------------------------
# Token table
# ---------------------------------------------------------------------------

def print_token_table(paths: list[Path], model: str = "gpt-4o") -> None:
    from agentlint.tokens import budget_for, count_tokens

    W = (36, 6, 8, 18, 8)

    def row(*cells: object) -> str:
        return "  ".join(str(c).ljust(w) for c, w in zip(cells, W))

    sep = "-+-".join("-" * w for w in W)
    click.echo(f"\n{Style.BRIGHT}Token Budget{Style.RESET_ALL}\n{sep}")
    click.echo(row("File", "Lines", "Tokens", "Budget (warn/err)", "Status"))
    click.echo(sep)

    for p in sorted(paths):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n      = count_tokens(text, model)
        lines  = text.count("\n")
        budget = budget_for(str(p))
        if budget is None:
            status, bs = _c("-", Style.DIM), "-"
        else:
            warn, err = budget
            bs = f"{warn:,}/{err:,}"
            if n >= err:    status = _c("X OVER", Fore.RED    + Style.BRIGHT)
            elif n >= warn: status = _c("! WARN", Fore.YELLOW + Style.BRIGHT)
            else:           status = _c("OK",     Fore.GREEN)
        click.echo(row(str(p), lines, f"{n:,}", bs, status))

    click.echo(sep + "\n")


# ---------------------------------------------------------------------------
# Sync results
# ---------------------------------------------------------------------------

def print_sync_results(results: list) -> None:
    for r in results:
        if r.written:
            click.echo(f"  {_c('OK', Fore.GREEN)} Written  "
                       f"{r.dest}  {_c(f'({r.target.name})', Style.DIM)}")
        else:
            click.echo(f"  {_c('-', Style.DIM)} Skipped  "
                       f"{r.dest}  {_c(f'({r.reason})', Style.DIM)}")


