# agentlint

A safety-focused linter for AI agent configuration files — with auto-fix, baseline mode, and CI integration.

AGENTS.md, CLAUDE.md, .cursorrules, and their siblings control how AI agents behave in your codebase. A single bad instruction — "never ask for confirmation before deleting," an unbounded retry loop, a contradicting rule buried in another file — can cause real production damage. agentlint catches these before they ship.

```
$ agentlint check

AGENTS.md
  X ERROR   AL040  Dangerous instruction: Never ask for confirmation before deleting. :7 [fix]
    -> Skipping confirmation enables irreversible damage in production.
  X ERROR   AL060  Unbounded loop: Keep trying until it works. :10 [fix]
    -> Add a maximum retry count, e.g. 'retry up to 3 times, then stop and report'.
  X ERROR   AL042  Unsafe git operation: git push --force origin main :14 [fix]
    -> Use --force-with-lease instead of --force.
  ! WARNING AL073  Hedge language: Try to write clean code. :11
    -> Replace 'try to' with a definitive directive — agents interpret it as optional.

3 error(s)  1 warning(s)  (4 total)
  3 fixable with `agentlint fix`
```

---

## Install

```bash
pip install agentlint

# With accurate token counting:
pip install "agentlint[accurate]"
```

Requires Python 3.10+.

---

## Commands

### `agentlint check`

Lint all agent config files in the current project.

```bash
agentlint check                         # auto-discover all known formats
agentlint check AGENTS.md CLAUDE.md    # lint specific files
agentlint check --strict                # exit 1 on warnings too (CI mode)
agentlint check --all                   # also run opt-in style rules
agentlint check --rule AL040            # run a single rule
agentlint check --no-info               # hide INFO diagnostics
agentlint check --format github         # GitHub Actions PR annotations
agentlint check --format json           # machine-readable JSON
agentlint check --baseline              # suppress violations in .agentlint-baseline.json
```

Auto-discovers: `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `.clinerules`, `.windsurfrules`, `GEMINI.md`, `JULES.md`, `.github/copilot-instructions.md`.

Exit code 1 on errors, making it drop-in ready for CI.

### `agentlint fix`

Auto-fix violations. Safe fixes apply by default; `--unsafe` enables semantic changes.

```bash
agentlint fix                  # apply safe fixes
agentlint fix --unsafe         # also apply unsafe fixes (review before committing)
agentlint fix --dry-run        # preview without writing
agentlint fix --rule AL042     # fix a single rule
```

**Safe fixes** are conservative transforms that preserve meaning:
- AL041 — replace hardcoded credentials with environment variable placeholders
- AL042 — replace `--force` with `--force-with-lease`
- AL070 — add missing YAML frontmatter to `.mdc` files
- AL071 — replace empty `globs: []` with `globs: ["**/*"]`

**Unsafe fixes** change semantics and require review:
- AL012 — scaffold missing required sections at the end of the file
- AL060 — append a retry cap to unbounded loop instructions

### `agentlint baseline`

Snapshot current violations so CI only fails on *new* issues. The essential workflow for adopting agentlint on an existing repo with pre-existing violations.

```bash
agentlint baseline create   # snapshot all current violations
agentlint baseline update   # re-snapshot after fixing some issues
agentlint baseline status   # show how many baseline violations remain
```

**Workflow:**

```bash
# Step 1: snapshot everything that's currently wrong
agentlint baseline create

# Step 2: commit the baseline file
git add .agentlint-baseline.json
git commit -m "chore: add agentlint baseline"

# Step 3: CI only fails on new issues
agentlint check --baseline --strict

# Step 4: fix existing issues over time, then shrink the baseline
agentlint baseline update
```

### `agentlint tokens`

Show a token-budget breakdown across all config files.

```bash
agentlint tokens
agentlint tokens --model gpt-4o
```

### `agentlint sync`

Generate tool-specific files from a single canonical `AGENTS.md`.

```bash
agentlint sync                   # write all targets
agentlint sync --dry-run         # preview without writing
agentlint sync --force           # overwrite unmanaged files
agentlint sync --only "Cursor"   # one target only
```

Produces `CLAUDE.md`, `.cursorrules`, `.github/copilot-instructions.md`, `.clinerules`, and `.windsurfrules` — each formatted for its tool. Only overwrites files agentlint previously generated.

### `agentlint init`

Scaffold a new `AGENTS.md` with all recommended sections.

```bash
agentlint init --python
agentlint init --node
```

### `agentlint rules`

List all rules with severity, opt-in status, and fixability.

```bash
agentlint rules              # all rules
agentlint rules --fixable    # only rules with auto-fix
```

---

## Rules

Twenty-nine rules total. Twenty run by default; five opt-in style rules run only with `--all`.

### Default rules

| ID | Severity | Fix | Description |
|----|----------|-----|-------------|
| AL001 | warning | | File exceeds recommended token budget |
| AL002 | warning | | File exceeds recommended line count |
| AL003 | warning | | Large inline block should be a file reference |
| AL010 | warning | | File is empty or near-empty |
| AL011 | warning | | File has no section headings |
| AL012 | warning | ⚡ unsafe | Missing recommended sections (Build / Run / Test / Architecture) |
| AL014 | warning | | Section has too many bullet points — agent instruction overload |
| AL015 | warning | | References a file that does not exist |
| AL020 | **error** | | Contradictory instructions in the same file |
| AL021 | warning | | Duplicate section heading |
| AL040 | **error** | | Dangerous autonomy pattern that risks irreversible damage |
| AL041 | **error** | ✅ safe | Possible hardcoded credential or secret |
| AL042 | **error** | ✅ safe | Unsafe git operation that can destroy shared history |
| AL043 | warning | | Production access without an explicit human approval gate |
| AL050 | **error** | | Contradictory instructions across config files |
| AL051 | warning | | Identical instruction copy-pasted across 3 or more config files |
| AL060 | **error** | ⚡ unsafe | Unbounded retry/loop instruction that will burn token budget |
| AL061 | warning | | Instruction tells agent to load the entire codebase into context |
| AL062 | warning | | Multi-agent reference with no explicit role definition |
| AL064 | warning | | Multi-step destructive workflow has no checkpoint or backup step |
| AL070 | **error** | ✅ safe | Cursor .mdc rule file is missing required YAML frontmatter |
| AL071 | warning | ✅ safe | Cursor .mdc rule has an empty globs array — it will never match |
| AL072 | warning | | Excessive use of alwaysApply:true burns token budget on every request |
| AL073 | warning | | Hedge language makes instructions optional — agents will skip them |

### Opt-in rules (`--all`)

| ID | Severity | Description |
|----|----------|-------------|
| AL013 | info | Instruction duplicates what a formatter or linter already enforces |
| AL030 | info | Vague language an agent cannot reliably act on |
| AL031 | warning | Heavy use of prohibitions rather than positive directives |
| AL032 | info | Passive-voice instruction obscures who acts |
| AL063 | info | References a tool not listed in the tools section |

---

## CI

### GitHub Actions

```yaml
# .github/workflows/agentlint.yml
name: agentlint
on: [push, pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ./  # or: uses: your-org/agentlint@v1
        with:
          strict: "true"
          baseline: "true"   # suppress existing violations
```

The action uses `--format github` automatically, producing inline PR annotations for every violation.

### Pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/your-org/agentlint
    rev: v0.2.0
    hooks:
      - id: agentlint        # lint on every commit
      - id: agentlint-fix    # auto-fix safe violations
```

### Generic CI

```bash
pip install agentlint
agentlint check --strict --baseline
```

---

## Output formats

**`--format text`** (default) — colourised terminal output with hints and fix indicators.

**`--format github`** — GitHub Actions workflow commands. GitHub renders these as inline annotations in pull requests:
```
::error file=AGENTS.md,line=7,title=AL040::Dangerous instruction: Never ask for confirmation.
::warning file=AGENTS.md,line=10,title=AL060::Unbounded loop: Keep trying until it works.
```

**`--format json`** — machine-readable array:
```json
[
  {
    "rule_id": "AL040",
    "severity": "error",
    "message": "Dangerous instruction: Never ask for confirmation.",
    "path": "AGENTS.md",
    "line": 7,
    "fixable": false,
    "fix_safe": null
  }
]
```

---

## Writing custom rules

```python
from agentlint.core import rule, WARNING, AgentConfig, Diagnostic

@rule("MYTEAM001", severity=WARNING, description="No TODO comments in agent configs")
def no_todos(cfg: AgentConfig) -> list[Diagnostic]:
    return [
        Diagnostic(
            rule_id="MYTEAM001",
            severity=WARNING,
            message="Unresolved TODO — fix before shipping.",
            path=cfg.path,
            line=i + 1,
        )
        for i, line in enumerate(cfg.lines)
        if "TODO" in line
    ]
```

Import your rule module before calling `run_rules` and it is included automatically.

---

## Configuration

agentlint reads `.agentlint.toml` from the project root if present.

```toml
[agentlint]
ignore = ["AL014"]   # disable specific rules
strict = true        # treat warnings as errors
all    = false       # include opt-in rules
baseline = true      # always apply baseline suppression
```

---

## Why safety-first?

Most lint rules are stylistic opinions. The consequence of getting them wrong is a messy diff. Agent config rules are different: a single dangerous instruction can cause a CI pipeline to force-push to main, drop a production database, or burn thousands of tokens in a loop with no exit condition.

agentlint runs the high-confidence safety and consistency rules by default, and leaves the stylistic judgement calls as opt-in. The goal is a CI check you can trust to fail only when something is actually wrong.

The baseline system exists because most repos already have pre-existing issues. Blocking adoption until every historical violation is fixed defeats the purpose. Snapshot the current state, commit it, and enforce the guarantee that things only get better from here.

---

## License

MIT
