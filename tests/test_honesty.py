"""Claims this project may not make, swept over everything a reader or an agent sees.

README, docs, the install examples, the citation file, the package description,
the server instructions and every tool and parameter description. These are
absolutes: the cost of a false claim here is not a failing test, it is someone
believing it.
"""

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from mcp.client.client import Client

from litcheck_mcp.server import HONESTY_RULE, server

REPO = Path(__file__).resolve().parents[1]

# The honesty rule is the one place "novel" may appear, and it is exempt wherever it does.
FORBIDDEN = {
    "novelty claim": r"\bnovel(ty)?\b",
    "proof claim": r"\bproves?\b",
    "guarantee": r"\bguarantee[sd]?\b",
    "verified support": r"\bverified\s+support\b",
    "hallucination-free": r"\bhallucination[\s-]free\b",
    "complete search": r"\bcomplete\s+search\b",
    "biographical claim": r"\b(NYU|Langone|PhD)\b",
}


def _flat(text: str) -> str:
    return " ".join(text.split())


def _without_rule(text: str) -> str:
    return _flat(text).replace(_flat(HONESTY_RULE), " ")


def document_texts() -> dict[str, str]:
    paths = [REPO / "README.md", REPO / "CITATION.cff"]
    paths += sorted((REPO / "docs").glob("*.md")) + sorted((REPO / "examples").glob("*"))
    texts = {str(p.relative_to(REPO)): p.read_text(encoding="utf-8") for p in paths}
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    texts["pyproject.toml description"] = project["description"]
    return texts


async def server_texts() -> dict[str, str]:
    texts = {"server instructions": server.instructions or ""}
    async with Client(server, raise_exceptions=True) as client:
        for tool in (await client.list_tools()).tools:
            texts[f"tool {tool.name}"] = tool.description or ""
            for name, prop in tool.input_schema.get("properties", {}).items():
                texts[f"tool {tool.name}.{name}"] = prop.get("description", "")
            for name, prop in (tool.output_schema or {}).get("properties", {}).items():
                texts[f"tool {tool.name} -> {name}"] = prop.get("description", "")
    return texts


async def all_texts() -> dict[str, str]:
    texts = document_texts()
    texts.update(await server_texts())
    return texts


async def test_the_sweep_sees_what_it_should():
    """Guard the guard: an empty sweep would pass every test below vacuously."""
    texts = await all_texts()
    assert "README.md" in texts and "docs/EXAMPLE.md" in texts
    assert sum(1 for k in texts if k.startswith("tool ")) >= 14
    assert all(texts[k] for k in texts if k in ("README.md", "server instructions"))


@pytest.mark.parametrize("label,pattern", list(FORBIDDEN.items()))
async def test_no_forbidden_claims(label, pattern):
    hits = []
    for where, text in (await all_texts()).items():
        for match in re.finditer(pattern, _without_rule(text), re.IGNORECASE):
            hits.append(f"{where}: {match.group(0)!r}")
    assert not hits, f"{label} found:\n" + "\n".join(hits)


def test_the_rule_fires():
    assert re.search(FORBIDDEN["novelty claim"], "this hypothesis is Novel", re.IGNORECASE)
    assert not re.search(FORBIDDEN["novelty claim"], _without_rule(HONESTY_RULE), re.IGNORECASE)
    wrapped = HONESTY_RULE.replace(" a hypothesis", "\n  a hypothesis")
    assert not re.search(FORBIDDEN["novelty claim"], _without_rule(wrapped), re.IGNORECASE)


def test_honesty_rule_is_stated_early_and_verbatim():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    flat = _flat(readme)
    rule = _flat(HONESTY_RULE)
    assert rule in flat
    assert len(flat[: flat.index(rule)].split()) <= 200
    assert rule in _flat(server.instructions or "")


async def test_every_tool_is_in_the_readme_table():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    async with Client(server, raise_exceptions=True) as client:
        names = [t.name for t in (await client.list_tools()).tools]
    assert len(names) == 7
    for name in names:
        assert f"| `{name}` |" in readme, f"{name} is not in the README's tool table"


def test_license_is_plain_mit():
    text = " ".join((REPO / "LICENSE").read_text(encoding="utf-8").split())
    assert text.startswith("MIT License")
    assert text.endswith("DEALINGS IN THE SOFTWARE.")


def test_readme_and_worked_example_match_the_code():
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_readme.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
