"""agentlint CLI — check, fix, baseline, tokens, sync, init, rules."""
from __future__ import annotations

import sys
from pathlib import Path

import click

KNOWN_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    ".cursorrules",
    ".clinerules",
    ".windsurfrules",
    "GEMINI.md",
    "JULES.md",
    ".github/copilot-instructions.md",
)

_INIT_TEMPLATE = """\
# {name}

> Agent instructions for this repository.
> Managed by [agentlint](https://github.com/your-org/agentlint).
> Edit this file, then run `agentlint sync` to propagate to all tools.

## Build

```bash
{install}
```

## Run

```bash
# TODO: add start command
```

## Test

```bash
{test}
```

## Architecture

<!--
  Describe the project in 3-5 sentences:
    - What it does and who it is for
    - Entry point(s)
    - Key directories and their purpose
-->

TODO

## Key Conventions

- <!-- e.g. All public functions must have type annotations. -->
- <!-- e.g. Use pathlib.Path, not os.path. -->

## Out of Scope

<!--
  What the agent must NOT touch:
    - Do not modify files in dist/
    - Do not alter the database schema without a migration
-->
"""


def _discover(files: tuple, root: Path) -> list[Path]:
    if files:
        return [p.resolve() for p in files if p.exists()]
    found: list[Path] = []
    for name in KNOWN_FILES:
        c = (root / name).resolve()
        if c.exists():
            found.append(c)
    mdc_dir = root / ".cursor" / "rules"
    if mdc_dir.is_dir():
        for mdc in sorted(mdc_dir.rglob("*.mdc")):
            found.append(mdc.resolve())
    return found


@click.group(no_args_is_help=True)
@click.version_option(package_name="agentlint")
def app() -> None:
    """Lint, validate, and sync AI agent configuration files."""


# -- check --------------------------------------------------------------------

@app.command("check")
@click.argument("files", nargs=-1, type=click.Path(path_type=Path))
@click.option("--root", "-r", default=Path("."), show_default=True,
              type=click.Path(file_okay=False, path_type=Path),
              help="Project root used for auto-discovery.")
@click.option("--no-hints", is_flag=True, help="Suppress hint text.")
@click.option("--no-info",  is_flag=True, help="Hide INFO-level diagnostics.")
@click.option("--strict",   is_flag=True, help="Exit non-zero on warnings too.")
@click.option("--rule", "-R", multiple=True, metavar="ID",
              help="Run only these rule IDs (repeatable).")
@click.option("--all", "all_rules", is_flag=True,
              help="Include opt-in style/clarity rules (AL013, AL030–AL032, AL063).")
@click.option("--format", "fmt",
              type=click.Choice(["text", "github", "json"], case_sensitive=False),
              default="text", show_default=True,
              help="Output format: text (default), github (Actions annotations), json.")
@click.option("--baseline", is_flag=True,
              help="Suppress violations already captured in .agentlint-baseline.json.")
@click.option("--baseline-file", default=None, type=click.Path(path_type=Path),
              metavar="FILE", help="Path to baseline file (default: .agentlint-baseline.json).")
def cmd_check(files, root, no_hints, no_info, strict, rule,
              all_rules, fmt, baseline, baseline_file) -> None:
    """Lint one or more agent configuration files.

    Auto-discovers AGENTS.md, CLAUDE.md, .cursorrules, and other known
    formats when no FILES are given.

    Safety and consistency rules run by default. Pass --all to also run
    opt-in style and clarity rules (AL013, AL030-AL032, AL063).

    \b
    Output formats:
      text    — colourised terminal output (default)
      github  — GitHub Actions inline PR annotations
      json    — machine-readable JSON array
    """
    import agentlint.rules  # registers all rules via decorators
    from agentlint.core import run_rules
    from agentlint.parser import parse
    targets = _discover(files, root.resolve())
    if not targets:
        click.echo("No agent config files found. Pass a path or run from a project root.", err=True)
        sys.exit(1)

    rule_ids = {r.upper() for r in rule} if rule else None
    configs  = [parse(p) for p in targets]
    diags    = run_rules(configs, rule_ids=rule_ids, include_opt_in=all_rules)

    # Apply baseline filtering
    suppressed_count = 0
    if baseline:
        from agentlint.baseline import filter_new, load_baseline
        loaded_bl = load_baseline(root.resolve())
        if loaded_bl is None:
            click.echo("No baseline found. Run `agentlint baseline` first.", err=True)
            sys.exit(1)
        diags, suppressed_count = filter_new(diags, loaded_bl)

    # Render
    from agentlint.reporter import (
        print_diagnostics, print_github_annotations, print_json_output
    )
    if fmt == "github":
        print_github_annotations(diags, show_info=not no_info)
    elif fmt == "json":
        print_json_output(diags, show_info=not no_info)
    else:
        print_diagnostics(diags, show_hints=not no_hints, show_info=not no_info,
                          suppressed=suppressed_count)

    has_errors   = any(d.severity.value == "error"   for d in diags)
    has_warnings = any(d.severity.value == "warning" for d in diags)
    if has_errors or (strict and has_warnings):
        sys.exit(1)


# -- fix ----------------------------------------------------------------------

@app.command("fix")
@click.argument("files", nargs=-1, type=click.Path(path_type=Path))
@click.option("--root", "-r", default=Path("."),
              type=click.Path(file_okay=False, path_type=Path))
@click.option("--unsafe", is_flag=True,
              help="Also apply unsafe fixes (changes semantics — review before committing).")
@click.option("--dry-run", "-n", is_flag=True,
              help="Show what would change without writing any files.")
@click.option("--rule", "-R", multiple=True, metavar="ID",
              help="Fix only these rule IDs (repeatable).")
@click.option("--all", "all_rules", is_flag=True,
              help="Include opt-in rules when collecting fixes.")
def cmd_fix(files, root, unsafe, dry_run, rule, all_rules) -> None:
    """Auto-fix lint violations.

    Safe fixes are applied by default. Safe fixes are conservative transforms
    that preserve meaning: replacing --force with --force-with-lease,
    redacting hardcoded credentials, adding missing frontmatter.

    \b
    Pass --unsafe to also apply fixes that change semantics:
      - Scaffold missing required sections (AL012)
      - Append a retry cap to unbounded loop instructions (AL060)

    Always review --unsafe changes before committing.
    """
    import agentlint.rules
    from agentlint.core import run_rules
    from agentlint.parser import parse
    from agentlint.fix import apply_fixes
    import colorama
    from colorama import Fore, Style
    colorama.init(autoreset=True)

    targets = _discover(files, root.resolve())
    if not targets:
        click.echo("No agent config files found.", err=True)
        sys.exit(1)

    rule_ids = {r.upper() for r in rule} if rule else None
    configs  = [parse(p) for p in targets]
    diags    = run_rules(configs, rule_ids=rule_ids, include_opt_in=all_rules)

    fixable = [d for d in diags if d.fix is not None and (not d.fix.safe or not unsafe or True)]
    if not fixable:
        click.echo(f"{Fore.GREEN}Nothing to fix.{Style.RESET_ALL}")
        return

    safe_fixes   = [d for d in fixable if d.fix and d.fix.safe]
    unsafe_fixes = [d for d in fixable if d.fix and not d.fix.safe]

    to_apply = safe_fixes + (unsafe_fixes if unsafe else [])

    if dry_run:
        click.echo(f"\n{'(dry run) '}Would apply {len(to_apply)} fix(es):\n")
    else:
        click.echo(f"\nApplying {len(to_apply)} fix(es):\n")

    if not unsafe and unsafe_fixes:
        click.echo(
            f"  {Fore.YELLOW}!{Style.RESET_ALL} {len(unsafe_fixes)} unsafe fix(es) skipped "
            f"— rerun with --unsafe to apply them."
        )

    counts = apply_fixes(to_apply, safe_only=not unsafe, dry_run=dry_run)

    for path, n in sorted(counts.items()):
        verb = "Would fix" if dry_run else "Fixed"
        click.echo(f"  {Fore.GREEN}OK{Style.RESET_ALL}  {verb} {n} issue(s) in {path}")

    total = sum(counts.values())
    if total:
        suffix = " (dry run — no files written)" if dry_run else ""
        click.echo(f"\n{total} fix(es) applied{suffix}.")
    else:
        click.echo(f"\n{Fore.YELLOW}No fixable patterns found in current file state.{Style.RESET_ALL}")


# -- baseline -----------------------------------------------------------------

@app.group("baseline")
def cmd_baseline() -> None:
    """Manage the violation baseline for gradual adoption.

    \b
    Workflow:
      1.  agentlint baseline create   — snapshot current violations
      2.  git add .agentlint-baseline.json
      3.  agentlint check --baseline  — CI only fails on new issues

    Fix existing issues over time, then run `agentlint baseline update`
    to shrink the baseline as violations are resolved.
    """


@cmd_baseline.command("create")
@click.argument("files", nargs=-1, type=click.Path(path_type=Path))
@click.option("--root", "-r", default=Path("."),
              type=click.Path(file_okay=False, path_type=Path))
@click.option("--output", "-o", default=None, type=click.Path(path_type=Path),
              help="Path to write baseline (default: .agentlint-baseline.json).")
@click.option("--force", "-f", is_flag=True,
              help="Overwrite an existing baseline file.")
def baseline_create(files, root, output, force) -> None:
    """Snapshot all current violations into a baseline file."""
    import agentlint.rules
    from agentlint.core import run_rules
    from agentlint.parser import parse
    from agentlint import baseline as bl
    import colorama
    from colorama import Fore, Style
    colorama.init(autoreset=True)

    dest = output or (root.resolve() / bl.BASELINE_FILE)
    if Path(dest).exists() and not force:
        click.echo(f"Baseline already exists: {dest}. Use --force to overwrite.", err=True)
        sys.exit(1)

    targets = _discover(files, root.resolve())
    if not targets:
        click.echo("No agent config files found.", err=True)
        sys.exit(1)

    configs = [parse(p) for p in targets]
    diags   = run_rules(configs, include_opt_in=True)
    baseline_obj = bl.create_baseline(diags)
    out_path = bl.save_baseline(baseline_obj, Path(dest).parent if Path(dest).name == bl.BASELINE_FILE else Path(dest).parent)
    n = len(baseline_obj.fingerprints)

    click.echo(f"{Fore.GREEN}OK{Style.RESET_ALL}  Baseline created: {out_path} ({n} violation(s))")
    click.echo(f"    Commit this file, then run `agentlint check --baseline` in CI.")


@cmd_baseline.command("update")
@click.argument("files", nargs=-1, type=click.Path(path_type=Path))
@click.option("--root", "-r", default=Path("."),
              type=click.Path(file_okay=False, path_type=Path))
@click.option("--baseline-file", default=None, type=click.Path(path_type=Path))
def baseline_update(files, root, baseline_file) -> None:
    """Re-snapshot violations, replacing the existing baseline.

    Run this after fixing some issues to shrink the baseline. The new
    baseline will contain only violations that still exist.
    """
    import agentlint.rules
    from agentlint.core import run_rules
    from agentlint.parser import parse
    from agentlint import baseline as bl
    import colorama
    from colorama import Fore, Style
    colorama.init(autoreset=True)

    bf = Path(baseline_file) if baseline_file else (root.resolve() / bl.BASELINE_FILE)
    old_bl    = bl.load_baseline(bf.parent)
    old_count = len(old_bl.fingerprints) if old_bl else 0

    targets = _discover(files, root.resolve())
    if not targets:
        click.echo("No agent config files found.", err=True)
        sys.exit(1)

    configs = [parse(p) for p in targets]
    diags   = run_rules(configs, include_opt_in=True)
    new_bl  = bl.create_baseline(diags)
    bl.save_baseline(new_bl, bf.parent)
    n = len(new_bl.fingerprints)

    delta = old_count - n
    colour = Fore.GREEN if delta > 0 else (Fore.YELLOW if delta == 0 else Fore.RED)
    click.echo(f"{colour}OK{Style.RESET_ALL}  Baseline updated: {bf}")
    click.echo(f"    {old_count} → {n} violation(s)  "
               f"({'+' if delta >= 0 else ''}{delta} from previous baseline)")


@cmd_baseline.command("status")
@click.argument("files", nargs=-1, type=click.Path(path_type=Path))
@click.option("--root", "-r", default=Path("."),
              type=click.Path(file_okay=False, path_type=Path))
@click.option("--baseline-file", default=None, type=click.Path(path_type=Path))
def baseline_status(files, root, baseline_file) -> None:
    """Show how many baseline violations remain unresolved."""
    import agentlint.rules
    from agentlint.core import run_rules
    from agentlint.parser import parse
    from agentlint import baseline as bl
    from agentlint.formatters import print_text
    import colorama
    from colorama import Fore, Style
    colorama.init(autoreset=True)

    bf = Path(baseline_file) if baseline_file else (root.resolve() / bl.BASELINE_FILE)
    loaded_bl = bl.load_baseline(bf.parent)
    if loaded_bl is None:
        click.echo("No baseline file found. Run `agentlint baseline create` first.")
        return

    targets = _discover(files, root.resolve())
    if not targets:
        click.echo("No agent config files found.", err=True)
        sys.exit(1)

    configs = [parse(p) for p in targets]
    diags   = run_rules(configs, include_opt_in=True)
    new_diags, suppressed_count = bl.filter_new(diags, loaded_bl)
    # suppressed_count is the number still in baseline; new_diags are truly new
    total_in_baseline = len(loaded_bl.fingerprints)
    still_present     = suppressed_count

    click.echo(f"\n{Style.BRIGHT}Baseline status{Style.RESET_ALL}  ({bf})")
    click.echo(f"  Total in baseline : {total_in_baseline}")
    click.echo(f"  Still present     : {still_present}")
    resolved = total_in_baseline - still_present
    if resolved:
        click.echo(f"  {Fore.GREEN}Resolved          : {resolved}{Style.RESET_ALL}  "
                   f"(run `agentlint baseline update` to remove them)")
    # Show the suppressed (still-present baseline) violations
    suppressed_diags = [d for d in diags if d not in new_diags]
    if suppressed_diags:
        click.echo(f"\n  Remaining violations:\n")
        print_text(suppressed_diags, show_hints=False)


# -- tokens -------------------------------------------------------------------

@app.command("tokens")
@click.argument("files", nargs=-1, type=click.Path(path_type=Path))
@click.option("--root",  "-r", default=Path("."),
              type=click.Path(file_okay=False, path_type=Path))
@click.option("--model", "-m", default="gpt-4o", show_default=True,
              help="Tokenizer model name (requires tiktoken for accuracy).")
def cmd_tokens(files, root, model) -> None:
    """Show a token-budget breakdown for all agent config files."""
    from agentlint.reporter import print_token_table

    targets = _discover(files, root.resolve())
    if not targets:
        click.echo("No agent config files found.", err=True)
        sys.exit(1)
    print_token_table(targets, model=model)


# -- sync ---------------------------------------------------------------------

@app.command("sync")
@click.argument("source", default="AGENTS.md", type=click.Path(path_type=Path))
@click.option("--root",    "-r", default=Path("."),
              type=click.Path(file_okay=False, path_type=Path))
@click.option("--dry-run", "-n", is_flag=True,
              help="Show what would be written without writing anything.")
@click.option("--force",   "-f", is_flag=True,
              help="Overwrite files that were not generated by agentlint.")
@click.option("--only", multiple=True, metavar="NAME",
              help="Sync only the named target(s) (repeatable).")
def cmd_sync(source, root, dry_run, force, only) -> None:
    """Generate tool-specific config files from a canonical AGENTS.md.

    Produces CLAUDE.md, .cursorrules, .github/copilot-instructions.md,
    .clinerules, and .windsurfrules — each formatted for its tool.
    """
    from agentlint.sync import DEFAULT_TARGETS, sync
    from agentlint.reporter import print_sync_results

    src = (root / source).resolve()
    if not src.exists():
        click.echo(f"Source file not found: {src}", err=True)
        sys.exit(1)

    targets = DEFAULT_TARGETS
    if only:
        names   = {n.lower() for n in only}
        targets = [t for t in targets if t.name.lower() in names]
        if not targets:
            click.echo(f"No targets matched: {list(only)}", err=True)
            sys.exit(1)

    prefix = "(dry run) " if dry_run else ""
    click.echo(f"\n{prefix}Syncing {src.name} -> {len(targets)} target(s)\n")

    results = sync(src, root.resolve(), targets=targets, dry_run=dry_run, force=force)
    print_sync_results(results)

    n = sum(1 for r in results if r.written)
    suffix = " (dry run)" if dry_run else ""
    click.echo(f"\n{n} file(s) written{suffix}.")


# -- init ---------------------------------------------------------------------

@app.command("init")
@click.option("--root",   "-r", default=Path("."),
              type=click.Path(file_okay=False, path_type=Path))
@click.option("--python", "lang", flag_value="python", help="Python project defaults.")
@click.option("--node",   "lang", flag_value="node",   help="Node.js project defaults.")
@click.option("--force",  "-f",   is_flag=True, help="Overwrite existing AGENTS.md.")
def cmd_init(root, lang, force) -> None:
    """Scaffold a new AGENTS.md with all recommended sections."""
    dest = (root / "AGENTS.md").resolve()
    if dest.exists() and not force:
        click.echo("AGENTS.md already exists. Use --force to overwrite.", err=True)
        sys.exit(1)

    install, test = {
        "python": ("pip install -e '.[dev]'", "pytest"),
        "node":   ("npm install",              "npm test"),
    }.get(lang or "", ("# TODO: add install command", "# TODO: add test command"))

    name = root.resolve().name.replace("-", " ").replace("_", " ").title()
    dest.write_text(_INIT_TEMPLATE.format(name=name, install=install, test=test))
    click.echo(f"OK  Created {dest}")
    click.echo("Next: fill in the TODOs, run `agentlint check`, then `agentlint sync`.")


# -- rules --------------------------------------------------------------------

@app.command("rules")
@click.option("--fixable", is_flag=True, help="Show only fixable rules.")
def cmd_rules(fixable) -> None:
    """List all available lint rules."""
    import agentlint.rules
    from agentlint.core import all_rules, Severity
    import colorama
    from colorama import Fore, Style
    colorama.init(autoreset=True)

    def _c(text, color): return f"{color}{text}{Style.RESET_ALL}"

    _col = {
        Severity.ERROR:   Fore.RED,
        Severity.WARNING: Fore.YELLOW,
        Severity.INFO:    Fore.CYAN,
    }

    rules = all_rules()
    if fixable:
        rules = [r for r in rules if r.fixable]

    click.echo(f"\n{'ID':8}  {'Severity':9}  {'':8}  {'Fix':6}  Description\n{'-' * 84}")
    for r in rules:
        opt_tag = _c("opt-in  ", Fore.MAGENTA) if r.opt_in else "        "
        fix_tag = _c("[fix] ", Fore.GREEN) if r.fixable else "      "
        click.echo(
            f"{r.id:8}  "
            f"{_col[r.severity]}{r.severity.value:9}{Style.RESET_ALL}  "
            f"{opt_tag}"
            f"{fix_tag}"
            f"{r.description}"
        )
    click.echo()

    n_fixable = sum(1 for r in all_rules() if r.fixable)
    click.echo(_c(f"[fix]  = auto-fixable with `agentlint fix`  ({n_fixable} rules)", Fore.GREEN))
    click.echo(_c("opt-in = run only with --all or --rule <ID>", Style.DIM))
    click.echo()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
