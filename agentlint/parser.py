"""Single-pass markdown parser for agent configuration files."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from agentlint.core import AgentConfig

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_HEADING     = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def parse(path: Path) -> AgentConfig:
    text  = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    frontmatter: dict = {}
    body = text
    if m := _FRONTMATTER.match(text):
        try:
            frontmatter = yaml.safe_load(m.group(1)) or {}
        except Exception:
            pass
        body = text[m.end():]

    sections: dict[str, str] = {}
    headings = list(_HEADING.finditer(body))
    for i, hm in enumerate(headings):
        title = hm.group(2).strip()
        start = hm.end()
        end   = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        sections[title.lower()] = body[start:end].strip()

    return AgentConfig(
        path=path,
        text=text,
        lines=lines,
        sections=sections,
        frontmatter=frontmatter,
    )
