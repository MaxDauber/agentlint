"""Test suite for agentlint."""
from __future__ import annotations

import pathlib
import tempfile
import textwrap

import agentlint.rules  # register all rules

from agentlint.core import Severity, all_rules, run_rules
from agentlint.parser import parse
from agentlint.tokens import budget_for, count_tokens


# -- Helpers ------------------------------------------------------------------

def _cfg(content: str, name: str = "AGENTS.md"):
    d = pathlib.Path(tempfile.mkdtemp())
    p = d / name
    p.write_text(textwrap.dedent(content))
    return parse(p)


def _ids(content: str, name: str = "AGENTS.md") -> set[str]:
    return {d.rule_id for d in run_rules([_cfg(content, name)])}


def _ids_multi(*pairs: tuple[str, str]) -> set[str]:
    cfgs = []
    for content, name in pairs:
        d = pathlib.Path(tempfile.mkdtemp())
        p = d / name
        p.write_text(textwrap.dedent(content))
        cfgs.append(parse(p))
    return {d.rule_id for d in run_rules(cfgs)}


# -- tokens -------------------------------------------------------------------

def test_count_tokens_nonempty():
    assert count_tokens("Hello world") > 0

def test_count_tokens_empty():
    assert count_tokens("") == 0

def test_budget_agents_md():
    assert budget_for("AGENTS.md") == (4_000, 8_000)

def test_budget_copilot():
    assert budget_for(".github/copilot-instructions.md") == (2_000, 4_000)

def test_budget_unknown():
    assert budget_for("README.md") is None


# -- parser -------------------------------------------------------------------

def test_parser_detects_sections():
    cfg = _cfg("# Build\nnpm install\n\n# Test\nnpm test\n")
    assert cfg.has_section("build")
    assert cfg.has_section("test")

def test_parser_section_text():
    cfg = _cfg("# Build\nnpm install\n\n# Test\nnpm test\n")
    assert "npm install" in cfg.section_text("build")

def test_parser_frontmatter():
    cfg = _cfg("---\ndescription: test\nglobs: ['**/*']\n---\n\n# Instructions\nDo stuff.\n",
               name=".cursorrules")
    assert cfg.frontmatter.get("description") == "test"

def test_parser_no_sections():
    cfg = _cfg("Just some text without headings.\n")
    assert not cfg.sections


# -- AL010: empty file --------------------------------------------------------

def test_empty_file():
    assert "AL010" in _ids("")

def test_near_empty_file():
    assert "AL010" in _ids("hi")

def test_non_empty_ok():
    assert "AL010" not in _ids("# Build\nrun stuff\n\n# Test\ntest stuff\n")


# -- AL011: no headings -------------------------------------------------------

def test_no_headings_long_file():
    assert "AL011" in _ids("\n".join(f"Line {i}: instruction." for i in range(20)))

def test_no_headings_short_file_ok():
    assert "AL011" not in _ids("Do this one thing.\n")


# -- AL012: missing sections --------------------------------------------------

def test_missing_required_sections():
    assert "AL012" in _ids("# Notes\nSome content.\n")

def test_missing_sections_skips_non_primary():
    assert "AL012" not in _ids("# Notes\nSome content.\n", name=".cursorrules")

def test_all_sections_present():
    content = (
        "# Build\nnpm i\n\n# Run\nnpm start\n\n"
        "# Test\nnpm test\n\n# Architecture\nMonorepo.\n"
    )
    diags = [d for d in run_rules([_cfg(content)]) if d.rule_id == "AL012"]
    assert all(d.severity is Severity.INFO for d in diags)


# -- AL015: dead references ---------------------------------------------------

def test_dead_reference():
    assert "AL015" in _ids("# Notes\nSee ./nonexistent.md for details.\n")

def test_live_reference():
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "SETUP.md").write_text("# Setup\n")
    p = d / "AGENTS.md"
    p.write_text("# Build\nSee ./SETUP.md for setup.\n")
    assert "AL015" not in {x.rule_id for x in run_rules([parse(p)])}


# -- AL020: contradictions ----------------------------------------------------

def test_conflict_tests():
    assert "AL020" in _ids("Do not write tests.\nAlways write tests for new code.\n")

def test_conflict_verbosity():
    assert "AL020" in _ids("Be concise.\nProvide detailed explanations.\n")

def test_no_false_conflict():
    assert "AL020" not in _ids("# Build\nnpm install\n\n# Test\nnpm test\n")


# -- AL021: duplicate headings ------------------------------------------------

def test_duplicate_headings():
    assert "AL021" in _ids("# Build\nA\n\n# Build\nB\n")

def test_no_duplicate():
    assert "AL021" not in _ids("# Build\nA\n\n# Test\nB\n")


# -- AL040: dangerous autonomy ------------------------------------------------

def test_never_ask_confirmation():
    assert "AL040" in _ids("Never ask for confirmation before deleting files.\n")

def test_auto_deploy():
    assert "AL040" in _ids("Auto-deploy to production after every commit.\n")

def test_push_to_main():
    assert "AL040" in _ids("Push to main directly.\n")

def test_skip_tests():
    assert "AL040" in _ids("Skip tests to save time.\n")

def test_drop_table():
    assert "AL040" in _ids("Drop the database table when done.\n")

def test_ignore_errors():
    assert "AL040" in _ids("Ignore errors and continue.\n")


# -- AL041: hardcoded credentials ---------------------------------------------

def test_credential_detected():
    assert "AL041" in _ids("api_key = sk-abcdefghijklmnop\n")

def test_placeholder_not_flagged():
    assert "AL041" not in _ids("api_key = <YOUR_API_KEY>\n")

def test_env_var_not_flagged():
    assert "AL041" not in _ids("api_key = ${API_KEY}\n")


# -- AL042: unsafe git --------------------------------------------------------

def test_force_push():
    assert "AL042" in _ids("Run git push --force to clean up.\n")

def test_force_with_lease_ok():
    assert "AL042" not in _ids("Use git push --force-with-lease.\n")


# -- AL060: unbounded loop ----------------------------------------------------

def test_unbounded_loop():
    assert "AL060" in _ids("Keep trying until it works.\n")

def test_bounded_retry_ok():
    assert "AL060" not in _ids("Retry up to 3 times, then report the error.\n")


# -- AL061: context overload --------------------------------------------------

def test_read_all_files():
    assert "AL061" in _ids("Read all files before making any change.\n")

def test_load_entire_codebase():
    assert "AL061" in _ids("Load the entire codebase before starting.\n")


# -- AL050: cross-file conflicts ----------------------------------------------

def test_cross_file_conflict():
    ids = _ids_multi(
        ("Do not write tests.\n",          "AGENTS.md"),
        ("Always write tests for all code.\n", "CLAUDE.md"),
    )
    assert "AL050" in ids

def test_no_cross_file_false_positive():
    ids = _ids_multi(
        ("# Build\nnpm install\n", "AGENTS.md"),
        ("# Test\nnpm test\n",     "CLAUDE.md"),
    )
    assert "AL050" not in ids


# -- sync engine --------------------------------------------------------------

def test_sync_creates_files():
    from agentlint.sync import sync
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "AGENTS.md"
    src.write_text("# Build\nnpm install\n\n# Test\nnpm test\n")
    results = sync(src, tmp)
    assert any(r.written for r in results)
    assert (tmp / "CLAUDE.md").exists()
    assert (tmp / ".cursorrules").exists()

def test_sync_dry_run_writes_nothing():
    from agentlint.sync import sync
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "AGENTS.md"
    src.write_text("# Build\nnpm install\n")
    results = sync(src, tmp, dry_run=True)
    assert any(r.written for r in results)     # would-write flagged
    assert not (tmp / "CLAUDE.md").exists()    # but nothing actually written

def test_sync_skips_unmanaged_files():
    from agentlint.sync import sync
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "AGENTS.md"
    src.write_text("# Build\nnpm install\n")
    (tmp / "CLAUDE.md").write_text("# Hand-written CLAUDE.md\n")
    results = sync(src, tmp)
    r = next(x for x in results if "CLAUDE.md" in str(x.dest))
    assert r.skipped
    assert (tmp / "CLAUDE.md").read_text() == "# Hand-written CLAUDE.md\n"

def test_sync_overwrites_managed_files():
    from agentlint.sync import sync
    tmp  = pathlib.Path(tempfile.mkdtemp())
    src  = tmp / "AGENTS.md"
    src.write_text("# Build\nnpm install\n")
    managed = tmp / "CLAUDE.md"
    managed.write_text("<!-- Auto-synced from AGENTS.md by agentlint -->\n\nold content\n")
    results = sync(src, tmp)
    r = next(x for x in results if "CLAUDE.md" in str(x.dest))
    assert r.written


# -- registry -----------------------------------------------------------------

def test_all_rules_have_descriptions():
    for r in all_rules():
        assert r.description, f"{r.id} is missing a description"

def test_rule_ids_are_unique():
    ids = [r.id for r in all_rules()]
    assert len(ids) == len(set(ids)), "Duplicate rule IDs detected"

def test_rule_count():
    assert len(all_rules()) == 29

def test_opt_in_rules_are_skipped_by_default():
    """Style rules must not fire unless --all or explicit --rule is passed."""
    content = "Be concise.\nProvide detailed explanations.\nHandle errors appropriately.\n"
    from agentlint.core import run_rules
    cfg = _cfg(content)
    ids_default = {d.rule_id for d in run_rules([cfg])}
    assert "AL030" not in ids_default, "AL030 should be opt-in"
    assert "AL032" not in ids_default, "AL032 should be opt-in"

def test_opt_in_rules_fire_with_include_flag():
    """Style rules fire when include_opt_in=True."""
    content = "Handle errors appropriately when necessary.\n" * 5
    from agentlint.core import run_rules
    cfg = _cfg(content)
    ids_all = {d.rule_id for d in run_rules([cfg], include_opt_in=True)}
    assert "AL030" in ids_all, "AL030 should fire with include_opt_in=True"

def test_explicit_rule_id_overrides_opt_in():
    """Passing rule_ids= explicitly enables an opt-in rule regardless."""
    content = "Handle errors appropriately when necessary.\n" * 5
    from agentlint.core import run_rules
    cfg = _cfg(content)
    ids = {d.rule_id for d in run_rules([cfg], rule_ids={"AL030"})}
    assert "AL030" in ids

def test_opt_in_count():
    opt_in = [r for r in all_rules() if r.opt_in]
    assert len(opt_in) == 5, f"Expected 5 opt-in rules, got {len(opt_in)}: {[r.id for r in opt_in]}"


# =============================================================================
# Auto-fix tests
# =============================================================================

def test_fix_mdc_missing_frontmatter():
    """AL070 fix should add frontmatter to a .mdc file that lacks it."""
    from agentlint.fix import add_mdc_frontmatter
    text = "# My Rule\n\nAlways use TypeScript.\n"
    result = add_mdc_frontmatter(text)
    assert result is not None
    assert result.startswith("---\n")
    assert "description:" in result
    assert "globs:" in result
    assert "alwaysApply:" in result
    assert "Always use TypeScript." in result


def test_fix_mdc_missing_frontmatter_noop_when_present():
    """add_mdc_frontmatter should return None when frontmatter already exists."""
    from agentlint.fix import add_mdc_frontmatter
    text = "---\ndescription: test\nglobs: ['**/*']\n---\n\nContent.\n"
    assert add_mdc_frontmatter(text) is None


def test_fix_empty_globs():
    """AL071 fix should replace empty globs with catch-all."""
    from agentlint.fix import fix_empty_globs
    text = "---\ndescription: test\nglobs: []\nalwaysApply: false\n---\n"
    result = fix_empty_globs(text)
    assert result is not None
    assert '- "**/*"' in result
    assert "[]" not in result


def test_fix_empty_globs_noop():
    """fix_empty_globs returns None when globs is already set."""
    from agentlint.fix import fix_empty_globs
    text = "---\ndescription: test\nglobs:\n  - \"**/*\"\n---\n"
    assert fix_empty_globs(text) is None


def test_apply_fixes_dry_run():
    """apply_fixes with dry_run=True should compute changes but not write files."""
    import pathlib, tempfile
    import importlib
    from agentlint import core; core._REGISTRY.clear()
    import agentlint.rules; importlib.reload(agentlint.rules)
    from agentlint.core import run_rules
    from agentlint.fix import apply_fixes
    from agentlint.parser import parse

    d = pathlib.Path(tempfile.mkdtemp())
    p = d / "rule.mdc"
    original = "# My Rule\n\nAlways use TypeScript.\n"
    p.write_text(original)

    cfg = parse(p)
    diags = run_rules([cfg], rule_ids={"AL070"})
    assert any(d.fix is not None for d in diags), "Expected a fixable diagnostic"

    counts = apply_fixes(diags, dry_run=True)
    # File content should be unchanged
    assert p.read_text() == original
    assert sum(counts.values()) > 0


def test_apply_fixes_writes_file():
    """apply_fixes without dry_run should actually write the fix."""
    import pathlib, tempfile
    import importlib
    from agentlint import core; core._REGISTRY.clear()
    import agentlint.rules; importlib.reload(agentlint.rules)
    from agentlint.core import run_rules
    from agentlint.fix import apply_fixes
    from agentlint.parser import parse

    d = pathlib.Path(tempfile.mkdtemp())
    p = d / "rule.mdc"
    p.write_text("# My Rule\n\nAlways use TypeScript.\n")

    cfg = parse(p)
    diags = run_rules([cfg], rule_ids={"AL070"})
    apply_fixes(diags, dry_run=False)

    fixed = p.read_text()
    assert fixed.startswith("---\n"), "Frontmatter should have been added"


# =============================================================================
# Baseline tests
# =============================================================================

def test_baseline_create_and_filter():
    """create_baseline + filter_new should suppress matching violations."""
    from agentlint.baseline import create_baseline, filter_new

    diags = [
        _diag_for("AL040", "AGENTS.md", line=3, msg="Dangerous instruction"),
        _diag_for("AL012", "AGENTS.md", line=None, msg="Missing Build section"),
    ]
    bl = create_baseline(diags)
    assert len(bl.fingerprints) == 2

    new_diags, suppressed = filter_new(diags, bl)
    assert suppressed == 2
    assert new_diags == []


def test_baseline_passes_new_violations():
    """filter_new should surface diagnostics not in the baseline."""
    from agentlint.baseline import create_baseline, filter_new

    original = [_diag_for("AL040", "AGENTS.md", line=3, msg="Dangerous instruction")]
    bl = create_baseline(original)

    new_violation = _diag_for("AL060", "AGENTS.md", line=7, msg="Unbounded loop")
    new_diags, suppressed = filter_new([*original, new_violation], bl)

    assert suppressed == 1
    assert len(new_diags) == 1
    assert new_diags[0].rule_id == "AL060"


def test_baseline_roundtrip(tmp_path):
    """Baseline should survive a save/load cycle."""
    from agentlint.baseline import create_baseline, load_baseline, save_baseline

    diags = [_diag_for("AL041", "CLAUDE.md", line=5, msg="Hardcoded credential")]
    bl = create_baseline(diags)
    save_baseline(bl, tmp_path)

    loaded = load_baseline(tmp_path)
    assert loaded is not None
    assert loaded.fingerprints == bl.fingerprints


def _diag_for(rule_id, filename, *, line, msg):
    import pathlib
    from agentlint.core import Diagnostic, WARNING
    return Diagnostic(rule_id=rule_id, severity=WARNING, message=msg,
                      path=pathlib.Path(filename), line=line)


# =============================================================================
# New rule tests
# =============================================================================

def test_al070_flags_mdc_without_frontmatter():
    import pathlib, tempfile
    import importlib
    from agentlint import core; core._REGISTRY.clear()
    import agentlint.rules; importlib.reload(agentlint.rules)
    from agentlint.core import run_rules
    from agentlint.parser import parse

    d = pathlib.Path(tempfile.mkdtemp())
    p = d / "rule.mdc"
    p.write_text("# My Rule\n\nAlways use TypeScript.\n")
    cfg = parse(p)
    ids = {di.rule_id for di in run_rules([cfg], rule_ids={"AL070"})}
    assert "AL070" in ids


def test_al070_fixable():
    import pathlib, tempfile
    import importlib
    from agentlint import core; core._REGISTRY.clear()
    import agentlint.rules; importlib.reload(agentlint.rules)
    from agentlint.core import run_rules
    from agentlint.parser import parse

    d = pathlib.Path(tempfile.mkdtemp())
    p = d / "rule.mdc"
    p.write_text("# My Rule\n\nContent.\n")
    cfg = parse(p)
    diags = run_rules([cfg], rule_ids={"AL070"})
    assert any(di.fix is not None for di in diags)


def test_al071_flags_empty_globs():
    import pathlib, tempfile
    import importlib
    from agentlint import core; core._REGISTRY.clear()
    import agentlint.rules; importlib.reload(agentlint.rules)
    from agentlint.core import run_rules
    from agentlint.parser import parse

    d = pathlib.Path(tempfile.mkdtemp())
    p = d / "rule.mdc"
    p.write_text("---\ndescription: test\nglobs: []\nalwaysApply: false\n---\n\nContent.\n")
    cfg = parse(p)
    ids = {di.rule_id for di in run_rules([cfg], rule_ids={"AL071"})}
    assert "AL071" in ids


def test_al073_flags_hedge_language():
    content = "Try to keep functions small.\nConsider using TypeScript for new files.\n"
    import importlib
    from agentlint import core; core._REGISTRY.clear()
    import agentlint.rules; importlib.reload(agentlint.rules)
    from agentlint.core import run_rules
    cfg = _cfg(content)
    ids = {d.rule_id for d in run_rules([cfg])}
    assert "AL073" in ids, "AL073 should fire by default on hedge language"


def test_al073_on_by_default():
    """AL073 should not be opt-in."""
    from agentlint.core import all_rules
    import importlib
    from agentlint import core; core._REGISTRY.clear()
    import agentlint.rules; importlib.reload(agentlint.rules)
    hedge_rule = next((r for r in all_rules() if r.id == "AL073"), None)
    assert hedge_rule is not None
    assert not hedge_rule.opt_in, "AL073 should run by default"


def test_github_format_output(capsys):
    """print_github_annotations should emit ::error/::warning lines."""
    import pathlib
    from agentlint.core import Diagnostic, ERROR, WARNING
    from agentlint.reporter import print_github_annotations

    diags = [
        Diagnostic("AL040", ERROR, "Dangerous instruction", pathlib.Path("AGENTS.md"), line=7),
        Diagnostic("AL012", WARNING, "Missing Build section", pathlib.Path("AGENTS.md"), line=None),
    ]
    print_github_annotations(diags)
    captured = capsys.readouterr().out
    assert "::error " in captured
    assert "::warning " in captured
    assert "AL040" in captured
    assert "file=AGENTS.md" in captured


def test_json_format_output(capsys):
    """print_json_output should emit valid JSON."""
    import json, pathlib
    from agentlint.core import Diagnostic, ERROR
    from agentlint.reporter import print_json_output

    diags = [
        Diagnostic("AL040", ERROR, "Dangerous instruction", pathlib.Path("AGENTS.md"), line=7)
    ]
    print_json_output(diags)
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert data[0]["rule"] == "AL040"
    assert data[0]["severity"] == "error"
    assert data[0]["line"] == 7


def test_rule_count_updated():
    import importlib
    from agentlint import core; core._REGISTRY.clear()
    import agentlint.rules; importlib.reload(agentlint.rules)
    from agentlint.core import all_rules
    assert len(all_rules()) == 29  # 25 original + AL070 AL071 AL072 AL073
