"""Core types, AgentConfig, and the rule registry."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional


class Severity(str, Enum):
    ERROR   = "error"
    WARNING = "warning"
    INFO    = "info"

# Aliases for use in rules.py
ERROR   = Severity.ERROR
WARNING = Severity.WARNING
INFO    = Severity.INFO


@dataclass
class Fix:
    """An auto-fix attached to a Diagnostic.

    ``transform`` receives the full file text and returns the fixed text,
    or None if the fix cannot be applied (e.g. the expected pattern is gone).

    ``safe=True``   — applied by default with ``agentlint fix``.
    ``safe=False``  — only applied with ``agentlint fix --unsafe``.
    """
    description: str
    transform:   Callable[[str], Optional[str]]
    safe:        bool = True


@dataclass
class Diagnostic:
    rule_id:  str
    severity: Severity
    message:  str
    path:     Path
    line:     Optional[int] = None
    hint:     Optional[str] = None
    fix:      Optional[Fix] = None    # auto-fix, if available


@dataclass
class AgentConfig:
    path:        Path
    text:        str
    lines:       list[str]
    sections:    dict[str, str] = field(default_factory=dict)  # title.lower() -> body
    frontmatter: dict           = field(default_factory=dict)

    @property
    def line_count(self) -> int:
        return len(self.lines)

    def has_section(self, *candidates: str) -> bool:
        return any(c.lower() in self.sections for c in candidates)

    def section_text(self, *candidates: str) -> str:
        for c in candidates:
            if t := self.sections.get(c.lower()):
                return t
        return ""

    def search(self, pattern: re.Pattern) -> Optional[re.Match]:
        return pattern.search(self.text)


# -- Rule registry -------------------------------------------------------------

@dataclass
class _Rule:
    id:          str
    severity:    Severity
    description: str
    fn:          object
    multi:       bool = False
    opt_in:      bool = False   # True = skipped by default; user must pass --all or -R
    fixable:     bool = False   # True = rule can emit Diagnostics with a Fix attached


_REGISTRY: list[_Rule] = []


def rule(
    rule_id: str,
    *,
    severity: Severity = WARNING,
    description: str = "",
    opt_in: bool = False,
    fixable: bool = False,
) -> Callable:
    """Register a single-file lint rule."""
    def decorator(fn):
        _REGISTRY.append(_Rule(rule_id, severity, description, fn,
                               multi=False, opt_in=opt_in, fixable=fixable))
        return fn
    return decorator


def multi_file_rule(
    rule_id: str,
    *,
    severity: Severity = WARNING,
    description: str = "",
    opt_in: bool = False,
    fixable: bool = False,
) -> Callable:
    """Register a cross-file lint rule (receives the full list of configs)."""
    def decorator(fn):
        _REGISTRY.append(_Rule(rule_id, severity, description, fn,
                               multi=True, opt_in=opt_in, fixable=fixable))
        return fn
    return decorator


def all_rules() -> list[_Rule]:
    return list(_REGISTRY)


def run_rules(
    configs: list[AgentConfig],
    *,
    rule_ids: Optional[set[str]] = None,
    include_opt_in: bool = False,
) -> list[Diagnostic]:
    """Run registered rules and return diagnostics.

    By default, opt-in rules are skipped. Pass include_opt_in=True (or
    provide explicit rule_ids) to include them.
    """
    def _enabled(r: _Rule) -> bool:
        if rule_ids is not None:
            return r.id in rule_ids
        if r.opt_in and not include_opt_in:
            return False
        return True

    diags: list[Diagnostic] = []
    for r in _REGISTRY:
        if not _enabled(r):
            continue
        if r.multi:
            diags.extend(r.fn(configs))
        else:
            for cfg in configs:
                diags.extend(r.fn(cfg))
    return diags
