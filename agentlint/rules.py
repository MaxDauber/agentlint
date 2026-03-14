"""
All agentlint lint rules.

Each rule is a plain function decorated with @rule or @multi_file_rule.
Single-config rules receive one AgentConfig.
Multi-file rules receive list[AgentConfig] and detect cross-file issues.

Rule ID ranges
  AL001-AL009  Token / size budgets
  AL010-AL019  Structure & completeness
  AL020-AL029  Conflicts & contradictions
  AL030-AL039  Style & clarity
  AL040-AL049  Safety & dangerous autonomy
  AL050-AL059  Cross-file consistency
  AL060-AL069  Forward-looking / multi-agent / cost
"""
from __future__ import annotations

import re
from pathlib import Path

from agentlint.core import (
    AgentConfig, Diagnostic, Fix, Severity,
    ERROR, WARNING, INFO,
    rule, multi_file_rule,
)
from agentlint.tokens import budget_for, count_tokens, line_budget_for


# -- Shared helpers ------------------------------------------------------------

def _diag(
    cfg: AgentConfig,
    rule_id: str,
    severity: Severity,
    message: str,
    *,
    line: int | None = None,
    hint: str | None = None,
    fix=None,
) -> Diagnostic:
    return Diagnostic(rule_id=rule_id, severity=severity, message=message,
                      path=cfg.path, line=line, hint=hint, fix=fix)


def _ln(cfg: AgentConfig, m: re.Match) -> int:
    """Return the 1-based line number of a regex match within cfg.text."""
    return cfg.text[: m.start()].count("\n") + 1


def _excerpt(cfg: AgentConfig, m: re.Match, width: int = 60) -> str:
    return cfg.lines[_ln(cfg, m) - 1].strip()[:width]


# ==============================================================================
# AL001-AL009  Token / size budgets
# ==============================================================================

@rule("AL001", description="File exceeds recommended token budget")
def token_budget(cfg: AgentConfig) -> list[Diagnostic]:
    budget = budget_for(str(cfg.path))
    if not budget:
        return []
    warn_at, error_at = budget
    n = count_tokens(cfg.text)
    if n >= error_at:
        return [_diag(cfg, "AL001", ERROR,
            f"~{n:,} tokens exceeds the hard limit of {error_at:,}. "
            "Agents will truncate or ignore excess content.",
            hint="Split the file or move reference material to linked documents.")]
    if n >= warn_at:
        return [_diag(cfg, "AL001", WARNING,
            f"~{n:,} tokens is approaching the soft limit of {warn_at:,}.",
            hint="Trim verbose sections or move details to a linked MEMORY.md.")]
    return []


@rule("AL002", description="File exceeds recommended line count")
def line_budget(cfg: AgentConfig) -> list[Diagnostic]:
    budget = line_budget_for(str(cfg.path))
    if not budget:
        return []
    warn_at, error_at = budget
    n = cfg.line_count
    if n >= error_at:
        return [_diag(cfg, "AL002", ERROR,
            f"{n} lines exceeds the hard limit of {error_at}.",
            hint="Anthropic recommends keeping CLAUDE.md under 300 lines.")]
    if n >= warn_at:
        return [_diag(cfg, "AL002", WARNING,
            f"{n} lines is approaching the soft limit of {warn_at}.")]
    return []


_LARGE_BLOCK = re.compile(r"```[a-z]*\n[\s\S]{600,?}\n```")

@rule("AL003", description="Large inline block should be a file reference")
def inline_block(cfg: AgentConfig) -> list[Diagnostic]:
    return [
        _diag(cfg, "AL003", WARNING,
            "Large inline content block wastes context budget.",
            line=_ln(cfg, m),
            hint='Replace with a pointer: "See `path/to/file` for the full contents."')
        for m in _LARGE_BLOCK.finditer(cfg.text)
    ]


# ==============================================================================
# AL010-AL019  Structure & completeness
# ==============================================================================

_PRIMARY_FILES = {"AGENTS.md", "CLAUDE.md"}

_REQUIRED_SECTIONS: list[tuple[str, ...]] = [
    ("build", "build commands", "setup", "installation", "getting started"),
    ("run",   "running", "development", "dev server", "start"),
    ("test",  "testing", "tests", "run tests"),
    ("architecture", "structure", "project structure", "codebase overview", "overview"),
]
_SUGGESTED_SECTIONS: list[tuple[str, ...]] = [
    ("security",     "auth", "authentication"),
    ("performance",  "optimisation", "optimization"),
    ("contributing", "workflow", "guidelines"),
]


@rule("AL010", description="File is empty or near-empty")
def empty_file(cfg: AgentConfig) -> list[Diagnostic]:
    stripped = cfg.text.strip()
    if not stripped:
        return [_diag(cfg, "AL010", ERROR, "File is empty.")]
    if len(stripped.splitlines()) < 3:
        return [_diag(cfg, "AL010", WARNING,
            "File has fewer than 3 non-empty lines — likely a placeholder.")]
    return []


@rule("AL011", description="File has no section headings")
def no_headings(cfg: AgentConfig) -> list[Diagnostic]:
    if cfg.line_count < 10 or cfg.sections:
        return []
    return [_diag(cfg, "AL011", WARNING,
        "No section headings found in a file long enough to need them.",
        hint="Organise content under headings like `# Build`, `# Architecture`, `# Testing`.")]


@rule("AL012", description="Missing recommended sections (Build / Run / Test / Architecture)", fixable=True)
def missing_sections(cfg: AgentConfig) -> list[Diagnostic]:
    if cfg.path.name not in _PRIMARY_FILES:
        return []
    diags: list[Diagnostic] = []
    missing_required = [g for g in _REQUIRED_SECTIONS if not cfg.has_section(*g)]
    if missing_required:
        # Build one unsafe fix that scaffolds ALL missing required sections at once
        def _scaffold_fix(text: str, sections: list = missing_required) -> str | None:
            additions = "".join(
                f"\n## {g[0].title()}\n\n```bash\n# TODO: add {g[0]} command\n```\n"
                for g in sections
            )
            return text.rstrip() + "\n" + additions
        fix = Fix(
            description="Scaffold missing required sections at end of file",
            transform=_scaffold_fix,
            safe=False,  # changes file content — require --unsafe
        )
        for group in missing_required:
            canon = group[0].title()
            diags.append(Diagnostic(
                rule_id="AL012", severity=WARNING,
                message=f"Missing `{canon}` section.",
                path=cfg.path, fix=fix,
                hint=f"Add `# {canon}` with the commands/context agents need to work here."))
    for group in _SUGGESTED_SECTIONS:
        if not cfg.has_section(*group):
            diags.append(_diag(cfg, "AL012", INFO,
                f"Consider adding a `{group[0].title()}` section — present in fewer than "
                "15% of real repos but consistently useful."))
    return diags


_LINTER_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(always use|must use|use only)\s+(single|double)\s+quot", re.I),
     "Quote style belongs in your formatter config (e.g. black/ruff), not agent instructions."),
    (re.compile(r"\b(always|must)\s+use\s+(2|4)\s+space", re.I),
     "Indentation style belongs in your formatter config."),
    (re.compile(r"\bmax(?:imum)?\s+line\s+length\b", re.I),
     "Line length limits belong in your linter config."),
    (re.compile(r"\bno\s+trailing\s+whitespace\b", re.I),
     "Trailing whitespace is an editor/formatter concern."),
    (re.compile(r"\buse\s+(?:utf-?8|ascii)\s+encoding\b", re.I),
     "File encoding is a project-level tool concern."),
]

@rule("AL013", severity=INFO, opt_in=True, description="Instruction duplicates what a formatter or linter already enforces")
def redundant_linter_rule(cfg: AgentConfig) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for i, line in enumerate(cfg.lines, 1):
        for pat, hint in _LINTER_PATTERNS:
            if pat.search(line):
                diags.append(_diag(cfg, "AL013", INFO,
                    f"Redundant style instruction: {line.strip()[:55]}",
                    line=i, hint=hint))
                break
    return diags


_BULLET = re.compile(r"^\s*[-*+]\s", re.MULTILINE)
_DENSITY_THRESHOLD = 15

@rule("AL014", description="Section has too many bullet points — agent instruction overload")
def section_density(cfg: AgentConfig) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for title, body in cfg.sections.items():
        n = len(_BULLET.findall(body))
        if n > _DENSITY_THRESHOLD:
            diags.append(_diag(cfg, "AL014", WARNING,
                f"`{title.title()}` section has {n} bullet points. "
                f"Agents reliably follow ~{_DENSITY_THRESHOLD} per section at most.",
                hint="Split into subsections or consolidate related items."))
    return diags


_FILE_REF = re.compile(
    r"(?:see|refer to|check|read)\s+[`'\"]?([^\s`'\"]+\.(?:md|txt|yaml|yml|toml|json|py|sh))[`'\"]?",
    re.I,
)

@rule("AL015", description="References a file that does not exist")
def dead_reference(cfg: AgentConfig) -> list[Diagnostic]:
    root = cfg.path.parent
    return [
        _diag(cfg, "AL015", WARNING,
            f"References `{m.group(1)}` but the file does not exist.",
            line=_ln(cfg, m),
            hint="Update the path or create the file.")
        for m in _FILE_REF.finditer(cfg.text)
        if not (root / m.group(1)).resolve().exists()
    ]


# ==============================================================================
# AL020-AL029  Conflicts & contradictions
# ==============================================================================

_CONFLICT_PAIRS: list[tuple[re.Pattern, re.Pattern, str]] = [
    (
        re.compile(r"\bdo\s+not\s+write\s+tests?\b", re.I),
        re.compile(r"\balways\s+write\s+tests?\b|\badd\s+tests?\b", re.I),
        "Contradictory test-writing instructions.",
    ),
    (
        re.compile(r"\bdo\s+not\s+use\s+type\s+hints?\b|\bskip\s+type\s+hints?\b", re.I),
        re.compile(r"\balways\s+use\s+type\s+hints?\b|\badd\s+type\s+hints?\b", re.I),
        "Contradictory type-hint instructions.",
    ),
    (
        re.compile(r"\bdo\s+not\s+add\s+comments?\b|\bavoid\s+comments?\b", re.I),
        re.compile(r"\balways\s+add\s+comments?\b|\bcomment\s+(?:your|all)\b", re.I),
        "Contradictory comment instructions.",
    ),
    (
        re.compile(r"\bdo\s+not\s+commit\b|\bnever\s+commit\b", re.I),
        re.compile(r"\bauto[\s-]commit\b|\bcommit\s+after\b", re.I),
        "Contradictory commit-behaviour instructions.",
    ),
    (
        re.compile(r"\bdo\s+not\s+modify\s+(?:the\s+)?schema\b", re.I),
        re.compile(r"\bupdate\s+(?:the\s+)?schema\b|\bmigrat\w+\b", re.I),
        "Contradictory schema-modification instructions.",
    ),
]

_CONCISE   = re.compile(r"\bbe\s+concise\b|\bshort\s+(?:answers?|responses?)\b|\bbrief\b", re.I)
_VERBOSE   = re.compile(r"\bdetailed\b|\bverbose\b|\bthorough\b|\bin[-\s]depth\b", re.I)
_HEAD_RE   = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)


@rule("AL020", severity=ERROR, description="Contradictory instructions in the same file")
def conflicting_instructions(cfg: AgentConfig) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for pat_a, pat_b, desc in _CONFLICT_PAIRS:
        ma, mb = pat_a.search(cfg.text), pat_b.search(cfg.text)
        if ma and mb:
            la, lb = _ln(cfg, ma), _ln(cfg, mb)
            diags.append(_diag(cfg, "AL020", ERROR, desc,
                line=min(la, lb),
                hint=f"Conflicting statements near lines {la} and {lb}."))
    ca, cb = _CONCISE.search(cfg.text), _VERBOSE.search(cfg.text)
    if ca and cb:
        diags.append(_diag(cfg, "AL020", WARNING,
            "Conflicting verbosity instructions ('concise' and 'detailed/verbose').",
            line=min(_ln(cfg, ca), _ln(cfg, cb))))
    return diags


@rule("AL021", description="Duplicate section heading")
def duplicate_headings(cfg: AgentConfig) -> list[Diagnostic]:
    seen: dict[str, int] = {}
    diags: list[Diagnostic] = []
    for m in _HEAD_RE.finditer(cfg.text):
        key = m.group(1).strip().lower()
        ln  = _ln(cfg, m)
        if key in seen:
            diags.append(_diag(cfg, "AL021", WARNING,
                f"Duplicate heading `{m.group(1).strip()}`.",
                line=ln,
                hint=f"First occurrence at line {seen[key]}. Merge the two sections."))
        else:
            seen[key] = ln
    return diags


# ==============================================================================
# AL030-AL039  Style & clarity
# ==============================================================================

_VAGUE_TERMS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bappropriately\b", re.I),
     "Replace 'appropriately' with the specific behaviour you want."),
    (re.compile(r"\bwhen\s+necessary\b", re.I),
     "Replace 'when necessary' with a concrete condition."),
    (re.compile(r"\bif\s+applicable\b", re.I),
     "Replace 'if applicable' with a concrete rule."),
    (re.compile(r"\bbest\s+practices?\b", re.I),
     "Agents lack implicit context — specify which best practices."),
    (re.compile(r"\bcommon\s+sense\b", re.I),
     "'Common sense' is not machine-parseable."),
    (re.compile(r"\bas\s+needed\b", re.I),
     "Replace 'as needed' with a measurable criterion."),
    (re.compile(r"\breasonable\b", re.I),
     "Define what 'reasonable' means for this project."),
    (re.compile(r"\bgood\s+(?:code|practice|style)\b", re.I),
     "Define what 'good' means — agents need specifics."),
    (re.compile(r"\betc\.?\b", re.I),
     "Enumerate fully. Agents do not extrapolate 'etc.'"),
    (re.compile(r"\bsomething\s+like\b", re.I),
     "Give a concrete example instead of 'something like'."),
]

@rule("AL030", severity=INFO, opt_in=True, description="Vague language an agent cannot reliably act on")
def vague_instructions(cfg: AgentConfig) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for i, line in enumerate(cfg.lines, 1):
        for pat, hint in _VAGUE_TERMS:
            if pat.search(line):
                diags.append(_diag(cfg, "AL030", INFO,
                    f"Vague instruction: {line.strip()[:60]}",
                    line=i, hint=hint))
                break
    return diags


_NEGATION = re.compile(r"\b(do\s+not|don'?t|never|avoid|refrain\s+from)\b", re.I)
_NEGATION_THRESHOLD = 8

@rule("AL031", opt_in=True, description="Heavy use of prohibitions rather than positive directives")
def negation_overload(cfg: AgentConfig) -> list[Diagnostic]:
    n = sum(1 for ln in cfg.lines if _NEGATION.search(ln))
    if n >= _NEGATION_THRESHOLD:
        return [_diag(cfg, "AL031", WARNING,
            f"{n} lines use prohibitions ('do not', 'never', 'avoid'). "
            "Heavy negation makes agent behaviour less predictable.",
            hint="Rephrase prohibitions as positive directives wherever possible.")]
    return []


_PASSIVE = re.compile(r"\b(?:should|must|needs?)\s+to\s+be\s+\w+ed\b"
                      r"|\b(?:should|must)\s+be\s+\w+ed\b", re.I)

@rule("AL032", severity=INFO, opt_in=True, description="Passive-voice instruction obscures who acts")
def passive_voice(cfg: AgentConfig) -> list[Diagnostic]:
    return [
        _diag(cfg, "AL032", INFO,
            f"Passive instruction: {_excerpt(cfg, m)}",
            line=_ln(cfg, m),
            hint="Use active voice: 'You must validate input' not 'Input must be validated'.")
        for m in _PASSIVE.finditer(cfg.text)
    ]


# ==============================================================================
# AL040-AL049  Safety & dangerous autonomy
# ==============================================================================

_DANGEROUS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"\bnever\s+ask\s+(?:for\s+)?(?:confirmation|permission|approval)\b", re.I),
        "Skipping confirmation enables irreversible damage in production.",
    ),
    (
        re.compile(r"\bauto[\s-]?(?:merge|deploy|push|delete|drop|truncate)\b", re.I),
        "Autonomous destructive operations require a human approval gate.",
    ),
    (
        re.compile(r"\bforce[\s-]?push\b|\bpush\s+-{1,2}force\b", re.I),
        "Force-pushing can permanently destroy shared commit history.",
    ),
    (
        re.compile(r"\bpush\s+(?:directly\s+)?to\s+(?:main|master)\b", re.I),
        "Direct pushes to protected branches bypass review and CI.",
    ),
    (
        re.compile(r"\bskip\s+(?:tests?|ci|review|lint|checks?)\b", re.I),
        "Skipping quality gates removes the safety net that catches agent mistakes.",
    ),
    (
        re.compile(r"\brun\s+as\s+root\b|\bsudo\s+without\b", re.I),
        "Running as root amplifies the blast radius of any agent error.",
    ),
    (
        re.compile(r"\bdelete\s+(?:all|every|the)\b.{0,30}\bwithout\s+backup\b", re.I),
        "Deleting data without a backup is irreversible.",
    ),
    (
        re.compile(r"\bdrop\s+(?:\w+\s+){0,3}(?:table|database|schema|collection)\b", re.I),
        "Dropping database objects must require explicit human approval.",
    ),
    (
        re.compile(r"\bignore\s+(?:errors?|exceptions?|failures?)\b", re.I),
        "Silent error suppression hides agent mistakes and causes silent data corruption.",
    ),
    (
        re.compile(r"\bbypass\s+(?:auth|authentication|authoriz|security|firewall)\b", re.I),
        "Bypassing security controls is a critical vulnerability.",
    ),
]

@rule("AL040", severity=ERROR, description="Dangerous autonomy pattern that risks irreversible damage")
def dangerous_autonomy(cfg: AgentConfig) -> list[Diagnostic]:
    return [
        _diag(cfg, "AL040", ERROR,
            f"Dangerous instruction: {_excerpt(cfg, m)}",
            line=_ln(cfg, m), hint=hint)
        for pat, hint in _DANGEROUS
        for m in pat.finditer(cfg.text)
    ]


_CREDENTIAL = re.compile(
    r"""(?ix)
    (?:api[_\-]?key | secret[_\-]?key | access[_\-]?token |
       password | passwd | private[_\-]?key)
    \s*[=:]\s*
    (?!<[A-Z_]+>)       # not a placeholder like <YOUR_KEY>
    (?!\$\{)            # not an env-var like ${API_KEY}
    (?!process\.env)    # not a code reference
    ["']?[A-Za-z0-9+/=_\-]{8,}["']?
    """,
)

@rule("AL041", severity=ERROR, fixable=True, description="Possible hardcoded credential or secret")
def hardcoded_credential(cfg: AgentConfig) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for m in _CREDENTIAL.finditer(cfg.text):
        # Build a safe fix: replace the matched value portion with a placeholder
        matched = m.group(0)
        def _redact(text: str, _m: str = matched) -> str | None:
            if _m not in text:
                return None
            # Preserve the key= prefix, replace the value with an env-var placeholder
            key_part = re.split(r"[=:]\s*", _m, 1)[0]
            env_name  = re.sub(r"[^A-Z0-9]", "_", key_part.upper().strip())
            return text.replace(_m, f"{key_part}=${{{{ {env_name} }}}}", 1)
        diags.append(Diagnostic(
            rule_id="AL041", severity=ERROR,
            message="Possible hardcoded credential — never store secrets in agent config files.",
            path=cfg.path, line=_ln(cfg, m),
            hint="Use environment variables or a secrets manager.",
            fix=Fix(
                description="Replace credential value with an environment variable placeholder",
                transform=_redact,
                safe=True,
            )))
    return diags


_UNSAFE_GIT = re.compile(
    r"\brebase\s+(?:published|shared|main|master|origin)\b"
    r"|\bgit\s+push\s+.*--force(?!-with-lease)\b",
    re.I,
)

@rule("AL042", severity=ERROR, fixable=True, description="Unsafe git operation that can destroy shared history")
def unsafe_git(cfg: AgentConfig) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for m in _UNSAFE_GIT.finditer(cfg.text):
        matched = m.group(0)
        def _fix_force(text: str, _m: str = matched) -> str | None:
            if _m not in text:
                return None
            fixed = re.sub(r"--force(?!-with-lease)", "--force-with-lease", _m)
            return text.replace(_m, fixed, 1) if fixed != _m else None
        diags.append(Diagnostic(
            rule_id="AL042", severity=ERROR,
            message=f"Unsafe git operation: {_excerpt(cfg, m)}",
            path=cfg.path, line=_ln(cfg, m),
            hint="Use --force-with-lease instead of --force. Never rebase published commits.",
            fix=Fix(
                description="Replace --force with --force-with-lease",
                transform=_fix_force,
                safe=True,
            )))
    return diags


_PROD = re.compile(
    r"\b(?:production|prod)\s+(?:database|db|server|cluster|environment|env)\b"
    r"|\bdeploy\s+to\s+(?:production|prod)\b",
    re.I,
)
_GATE = re.compile(r"\b(?:ask|confirm|approval|human|review|checkpoint)\b", re.I)

@rule("AL043", description="Production access without an explicit human approval gate")
def prod_without_gate(cfg: AgentConfig) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for m in _PROD.finditer(cfg.text):
        ln = _ln(cfg, m)
        ctx = "\n".join(cfg.lines[max(0, ln - 5): ln + 5])
        if not _GATE.search(ctx):
            diags.append(_diag(cfg, "AL043", WARNING,
                f"Production access near line {ln} with no approval gate in context.",
                line=ln,
                hint="Add an explicit human confirmation step before any production operation."))
    return diags


# ==============================================================================
# AL050-AL059  Cross-file consistency
# ==============================================================================

@multi_file_rule("AL050", severity=ERROR, description="Contradictory instructions across config files")
def cross_file_conflicts(configs: list[AgentConfig]) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for pat_a, pat_b, desc in _CONFLICT_PAIRS:
        files_a = [c for c in configs if pat_a.search(c.text)]
        files_b = [c for c in configs if pat_b.search(c.text)]
        for fa in files_a:
            for fb in files_b:
                if fa.path != fb.path:
                    diags.append(Diagnostic(
                        rule_id="AL050", severity=ERROR,
                        message=f"Cross-file conflict: {desc}",
                        path=fa.path,
                        hint=f"{fa.path.name} and {fb.path.name} give opposing instructions."))
    return diags


_TRIVIAL = re.compile(r"^\s*(?:#|<!--|$|-{3,}|={3,})")

@multi_file_rule("AL051", description="Identical instruction copy-pasted across 3 or more config files")
def cross_file_duplication(configs: list[AgentConfig]) -> list[Diagnostic]:
    if len(configs) < 3:
        return []
    seen: dict[str, list[Path]] = {}
    for cfg in configs:
        for ln in cfg.lines:
            s = ln.strip()
            if len(s) > 30 and not _TRIVIAL.match(s):
                seen.setdefault(s, []).append(cfg.path)
    diags: list[Diagnostic] = []
    for line_text, paths in seen.items():
        unique = list(dict.fromkeys(paths))
        if len(unique) >= 3:
            diags.append(Diagnostic(
                rule_id="AL051", severity=WARNING,
                message=f"Instruction repeated verbatim in {len(unique)} files: {line_text[:55]}",
                path=unique[0],
                hint="Keep the instruction in AGENTS.md and run `agentlint sync` to propagate it."))
    return diags


# ==============================================================================
# AL060-AL069  Forward-looking / multi-agent / cost
# ==============================================================================

_UNBOUNDED = re.compile(
    r"\bkeep\s+(?:trying|retrying|looping)\s+until\b"
    r"|\brepeat\s+until\s+(?:it\s+)?(?:works?|succeeds?|passes?)\b"
    r"|\bretry\s+(?:indefinitely|forever|without\s+limit)\b",
    re.I,
)

@rule("AL060", severity=ERROR, fixable=True, description="Unbounded retry/loop instruction that will burn token budget")
def unbounded_loop(cfg: AgentConfig) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    for m in _UNBOUNDED.finditer(cfg.text):
        matched = m.group(0)
        def _cap_retries(text: str, _m: str = matched) -> str | None:
            if _m not in text:
                return None
            return text.replace(_m, _m + " (up to 3 times, then stop and report)", 1)
        diags.append(Diagnostic(
            rule_id="AL060", severity=ERROR,
            message=f"Unbounded loop instruction: {_excerpt(cfg, m)}",
            path=cfg.path, line=_ln(cfg, m),
            hint="Add a maximum retry count, e.g. 'retry up to 3 times, then stop and report'.",
            fix=Fix(
                description="Append a 3-attempt cap to the retry instruction",
                transform=_cap_retries,
                safe=False,  # changes semantic meaning — require --unsafe
            )))
    return diags


_READ_ALL = re.compile(
    r"\bread\s+(?:all|every|each)\s+(?:files?|documents?|sources?)\b"
    r"|\bload\s+(?:all|every|the\s+entire)\s+(?:codebase|repo|project)\b"
    r"|\bsearch\s+(?:all|every)\s+files?\b",
    re.I,
)

@rule("AL061", description="Instruction tells agent to load the entire codebase into context")
def context_overload(cfg: AgentConfig) -> list[Diagnostic]:
    return [
        _diag(cfg, "AL061", WARNING,
            f"Broad context instruction: {_excerpt(cfg, m)}",
            line=_ln(cfg, m),
            hint="Target specific files or directories. Loading everything exhausts the context window.")
        for m in _READ_ALL.finditer(cfg.text)
    ]


_AGENT_REF   = re.compile(r"\bagent\s+\d\b|\bsub[\s-]?agent\b|\bworker\s+agent\b", re.I)
_ROLE_DEFN   = re.compile(r"\byour\s+role\s+is\b|\byou\s+are\s+(?:a|the)\b", re.I)

@rule("AL062", description="Multi-agent reference with no explicit role definition")
def multi_agent_no_role(cfg: AgentConfig) -> list[Diagnostic]:
    if _AGENT_REF.search(cfg.text) and not _ROLE_DEFN.search(cfg.text):
        return [_diag(cfg, "AL062", WARNING,
            "File references multiple agents but defines no roles.",
            hint="Add a 'Your Role' or 'Agent Responsibilities' section "
                 "so each agent knows its scope.")]
    return []


_TOOL_USE     = re.compile(r"\buse\s+(?:the\s+)?`?(\w+)`?\s+tool\b|\bcall\s+`?(\w+)`?\s*\(", re.I)
_BUILTIN_TOOLS = frozenset({
    "bash", "python", "read_file", "write_file", "search", "git",
    "grep", "find", "curl", "cat", "ls", "sed", "awk",
})

@rule("AL063", severity=INFO, opt_in=True, description="References a tool not listed in the tools section")
def undefined_tool(cfg: AgentConfig) -> list[Diagnostic]:
    if not cfg.has_section("tools", "available tools", "mcp", "mcp servers"):
        return []
    defined = cfg.section_text("tools", "available tools", "mcp", "mcp servers").lower()
    return [
        _diag(cfg, "AL063", INFO,
            f"Tool `{name}` referenced but not listed in the tools section.",
            line=_ln(cfg, m),
            hint="Add it to the tools section or remove the reference.")
        for m in _TOOL_USE.finditer(cfg.text)
        if (name := (m.group(1) or m.group(2) or "").lower())
        and name not in _BUILTIN_TOOLS
        and name not in defined
    ]


_DESTRUCTIVE = re.compile(
    r"(?:step\s+\d|first|then|next|finally|after\s+that).{0,80}"
    r"(?:delete|drop|truncate|destroy|remove|wipe|purge|reset|overwrite)",
    re.I | re.DOTALL,
)
_CHECKPOINT = re.compile(
    r"\b(?:confirm|checkpoint|verify|validate|backup|snapshot|rollback)\b", re.I
)

@rule("AL064", description="Multi-step destructive workflow has no checkpoint or backup step")
def destructive_no_checkpoint(cfg: AgentConfig) -> list[Diagnostic]:
    return [
        _diag(cfg, "AL064", WARNING,
            "Multi-step destructive workflow with no checkpoint or backup step.",
            line=_ln(cfg, m),
            hint="Add an explicit 'verify / backup before proceeding' step.")
        for m in _DESTRUCTIVE.finditer(cfg.text)
        if not _CHECKPOINT.search(cfg.text[max(0, m.start() - 200): m.end() + 200])
    ]


# ==============================================================================
# AL070-AL079  Cursor MDC / frontmatter validation
# ==============================================================================

_MDC_REQUIRED_KEYS = {"description", "globs", "alwaysApply"}

@rule("AL070", severity=ERROR,
      description="Cursor .mdc rule file is missing required YAML frontmatter")
def mdc_missing_frontmatter(cfg: AgentConfig) -> list[Diagnostic]:
    """Flag .mdc files that lack frontmatter entirely, or are missing key fields."""
    if cfg.path.suffix != ".mdc":
        return []

    from agentlint.core import Fix
    from agentlint.fix import add_mdc_frontmatter

    if not cfg.frontmatter:
        return [_diag(cfg, "AL070", ERROR,
            "Cursor rule file has no YAML frontmatter — Cursor will silently ignore it.",
            hint="Add a frontmatter block with `description`, `globs`, and `alwaysApply`.",
            fix=Fix(
                description="Add default YAML frontmatter",
                transform=add_mdc_frontmatter,
                safe=True,
            ))]

    missing = _MDC_REQUIRED_KEYS - set(cfg.frontmatter.keys())
    if missing:
        return [_diag(cfg, "AL070", ERROR,
            f"Frontmatter missing required field(s): {', '.join(sorted(missing))}.",
            hint="Without these fields Cursor may not load the rule correctly.")]
    return []


@rule("AL071", description="Cursor .mdc rule has an empty globs array — it will never match")
def mdc_empty_globs(cfg: AgentConfig) -> list[Diagnostic]:
    if cfg.path.suffix != ".mdc":
        return []
    globs = cfg.frontmatter.get("globs")
    if globs is None:
        return []  # AL070 already covers missing frontmatter

    from agentlint.core import Fix
    from agentlint.fix import fix_empty_globs

    if isinstance(globs, list) and len(globs) == 0:
        return [_diag(cfg, "AL071", WARNING,
            "globs is an empty list — this rule will never be applied to any file.",
            hint='Set globs to ["**/*"] to apply always, or specify the relevant path patterns.',
            fix=Fix(
                description='Set globs to ["**/*"]',
                transform=fix_empty_globs,
                safe=True,
            ))]
    return []


_ALWAYS_APPLY_THRESHOLD = 3

@multi_file_rule("AL072",
    description="Excessive use of alwaysApply:true burns token budget on every request")
def mdc_always_apply_overload(configs: list[AgentConfig]) -> list[Diagnostic]:
    """Flag when too many .mdc rules use alwaysApply:true.

    Each alwaysApply rule is injected on every LLM request. More than
    3 simultaneously active rules adds significant token overhead.
    """
    always_on = [
        c for c in configs
        if c.path.suffix == ".mdc"
        and c.frontmatter.get("alwaysApply") is True
    ]
    if len(always_on) <= _ALWAYS_APPLY_THRESHOLD:
        return []

    names = ", ".join(c.path.name for c in always_on[:5])
    if len(always_on) > 5:
        names += f" … (+{len(always_on) - 5} more)"

    return [Diagnostic(
        rule_id="AL072", severity=WARNING,
        message=(
            f"{len(always_on)} rules use alwaysApply:true ({names}). "
            "Each adds to every request's token budget."
        ),
        path=always_on[0].path,
        hint=(
            "Set alwaysApply:false and use specific globs instead. "
            "Limit always-on rules to your 2-3 most critical global constraints."
        ),
    )]


# ==============================================================================
# AL073  Hedge language (default-on, higher-confidence than opt-in AL030)
# ==============================================================================

_HEDGE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\btry\s+to\b", re.I),
     "Replace 'try to' with a definitive directive — agents interpret it as optional."),
    (re.compile(r"\bconsider\s+using\b", re.I),
     "Replace 'consider using' with 'use' — agents treat suggestions as ignorable."),
    (re.compile(r"\byou\s+(?:might|could|may)\s+want\s+to\b", re.I),
     "This phrasing gives the agent permission to skip the instruction entirely."),
    (re.compile(r"\bif\s+possible\b", re.I),
     "Replace 'if possible' with a concrete condition or remove it."),
    (re.compile(r"\bwhen(?:ever)?\s+you\s+can\b", re.I),
     "This lets the agent decide whether the instruction applies. Be explicit."),
]

@rule("AL073", description="Hedge language makes instructions optional — agents will skip them")
def hedge_language(cfg: AgentConfig) -> list[Diagnostic]:
    """Catch 'try to X', 'consider using X', 'you might want to' etc.

    Unlike AL030 (opt-in, broad vague terms), this rule targets a specific
    class of hedge that makes a directive explicitly optional.  The fix is
    always the same: remove the hedge and state the requirement directly.
    Evidence: cursor-doctor found these patterns in 27/50 real projects.
    """
    diags: list[Diagnostic] = []
    for i, line in enumerate(cfg.lines, 1):
        for pat, hint in _HEDGE_PATTERNS:
            if pat.search(line):
                diags.append(_diag(cfg, "AL073", WARNING,
                    f"Hedge language gives agent permission to ignore: {line.strip()[:65]}",
                    line=i, hint=hint))
                break
    return diags
