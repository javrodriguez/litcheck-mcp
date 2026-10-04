#!/usr/bin/env python
"""Structural checks on the README and the worked example, which a reader trusts first.

1. Both install lines appear within the first 200 words of README.md, each in its
   own fenced block, byte-identical to examples/claude_code.txt and
   examples/codex.txt, so the README and the files people copy cannot drift.
2. Every output block in docs/EXAMPLE.md equals what the code produces from the
   recorded fixtures, with the clock pinned to the fixtures' recorded date and the
   log path shown as <LOG>. The page is re-derived, not typed.
3. Two README sentences are bound to the code: `as_of` is a UTC date (checked on
   the recorded responses' own Date headers, no clock pinned), and `check`'s exit
   status for FOUND is 0, or 3 when the paper's retraction status is RETRACTED.

    uv run python scripts/check_readme.py          # check
    uv run python scripts/check_readme.py --write  # re-derive docs/EXAMPLE.md's blocks
"""

import asyncio
import io
import json
import re
import shlex
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "core"))

from litcheck import cli  # noqa: E402
from litcheck.transport import ReplayTransport  # noqa: E402

FIXTURES = REPO / "core" / "tests" / "fixtures"
EXAMPLE = REPO / "docs" / "EXAMPLE.md"
WORD_LIMIT = 200
FIXTURE_DAY = "2026-10-03T21:32:25Z"
INSTALL_FILES = ("claude_code.txt", "codex.txt")

PMCID = "PMC10496602"
TRUE_QUOTE = "Arteriosclerosis consists of functional depletion of large-artery elasticity."
CHANGED_QUOTE = "Arteriosclerosis consists of functional depletion of small-artery elasticity."
CLAIM = "Arteriosclerosis is a loss of large-artery elasticity."

# (block id, how to run it, arguments). CLI steps share one log; MCP steps share another.
STEPS = (
    ("cli-found", "cli", ["check", "--id", PMCID, "--quote", TRUE_QUOTE, "--claim", CLAIM]),
    ("cli-changed", "cli", ["check", "--id", PMCID, "--quote", CHANGED_QUOTE]),
    ("cli-verify", "cli", ["verify-log"]),
    ("mcp-found", "mcp", ("check_quote", {"identifier": PMCID, "quote": TRUE_QUOTE})),
    ("mcp-changed", "mcp", ("check_quote", {"identifier": PMCID, "quote": CHANGED_QUOTE})),
    ("mcp-retraction", "mcp", ("retraction_status", {"identifier": PMCID})),
    ("mcp-verify", "mcp", ("verify_log", {})),
)
MARKER = re.compile(r"<!-- output: ([a-z-]+) -->\n```text\n(.*?)```\n", re.DOTALL)


def readme_text() -> str:
    return (REPO / "README.md").read_text(encoding="utf-8")


def check_install_lines() -> list[int]:
    text = readme_text()
    positions = []
    for name in INSTALL_FILES:
        line = (REPO / "examples" / name).read_text(encoding="utf-8")
        block = "```bash\n" + line + "```\n"
        assert block in text, f"README has no fenced block equal to examples/{name}"
        words = len(text[: text.index(block)].split())
        assert words <= WORD_LIMIT, (
            f"examples/{name} sits {words} words in; it must appear within the first {WORD_LIMIT}"
        )
        positions.append(words)
    return positions


AS_OF_SENTENCE = "as of that date (a UTC date: the day of the earliest check)"
EXIT_SENTENCES = (
    "`check` exits 0 only for `FOUND` in a paper whose retraction status is not `RETRACTED`, "
    "3 for `FOUND` in a paper whose retraction status is `RETRACTED`",
    "A retraction status of `UNVERIFIABLE` is not `RETRACTED`, so a `FOUND` with it still exits 0",
)
UTC_STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


def _flat(text: str) -> str:
    return " ".join(text.split())


def check_documented_facts() -> None:
    readme = _flat(readme_text())
    _, result = cli.retraction_for(PMCID, ReplayTransport(FIXTURES))
    stamps = [s["checked_at"] for s in result["sources"]]
    assert result["status"] == "NOT_RETRACTED_AS_OF" and stamps, result
    assert all(UTC_STAMP.fullmatch(t) for t in stamps), f"checked_at not UTC: {stamps}"
    assert result["as_of"] == min(stamps)[:10], (result["as_of"], stamps)
    assert AS_OF_SENTENCE in readme, "README does not say the as_of date is UTC"
    for verdict, status, code in (
        ("FOUND", "NOT_RETRACTED_AS_OF", 0),
        ("FOUND", "UNVERIFIABLE", 0),
        ("FOUND", "RETRACTED", 3),
        ("NOT_FOUND", "RETRACTED", 1),
        ("UNVERIFIABLE", None, 1),
    ):
        evidence = {"verdict": verdict, "retraction": status and {"status": status}}
        got = cli.check_exit_status(evidence)
        assert got == code, f"check exits {got} for {verdict}/{status}; the README says {code}"
    for sentence in EXIT_SENTENCES:
        assert sentence in readme, f"README lost its exit-status sentence: {sentence!r}"


def _cli_block(argv: list[str], log: str, replay: ReplayTransport) -> str:
    shown = argv + ([] if argv[0] == "verify-log" else ["--log"]) + ["<LOG>"]
    full = argv + ([log] if argv[0] == "verify-log" else ["--log", log])
    out = io.StringIO()
    code = cli.main(full, transport=replay, clock=lambda: FIXTURE_DAY, out=out, log_label="<LOG>")
    command = "$ ./litcheck " + " ".join(shlex.quote(a) for a in shown)
    return f"{command}\n{out.getvalue()}(exit status {code})\n"


async def _mcp_blocks(steps, log: str, replay: ReplayTransport) -> dict[str, str]:
    import os

    from mcp.client.client import Client

    from litcheck_mcp import server as module

    module.transport = replay
    module.clock = lambda: FIXTURE_DAY
    os.environ["LITCHECK_LOG"] = log
    blocks = {}
    async with Client(module.server, raise_exceptions=True) as client:
        for block_id, (tool, args) in steps:
            result = await client.call_tool(tool, args)
            body = json.dumps(result.structured_content, indent=2, ensure_ascii=False)
            body = body.replace(json.dumps(log)[1:-1], "<LOG>")
            call = f"{tool}({json.dumps(args, ensure_ascii=False)})"
            blocks[block_id] = f"> {call}\n{body}\n"
    return blocks


def derive() -> dict[str, str]:
    blocks = {}
    with tempfile.TemporaryDirectory() as tmp:
        cli_log, mcp_log = str(Path(tmp) / "cli.jsonl"), str(Path(tmp) / "mcp.jsonl")
        replay = ReplayTransport(FIXTURES)
        for block_id, kind, args in STEPS:
            if kind == "cli":
                blocks[block_id] = _cli_block(list(args), cli_log, replay)
        mcp_steps = [(b, a) for b, k, a in STEPS if k == "mcp"]
        blocks.update(asyncio.run(_mcp_blocks(mcp_steps, mcp_log, replay)))
    for block_id, body in blocks.items():
        assert tmp not in body, f"{block_id} leaks the temporary path"
    return blocks


def check_example(write: bool = False) -> int:
    text = EXAMPLE.read_text(encoding="utf-8")
    blocks = derive()
    found = {m.group(1): m.group(2) for m in MARKER.finditer(text)}
    assert set(found) == set(blocks), (
        f"docs/EXAMPLE.md output blocks {sorted(found)} differ from the steps {sorted(blocks)}"
    )
    if write:
        new = MARKER.sub(
            lambda m: f"<!-- output: {m.group(1)} -->\n```text\n{blocks[m.group(1)]}```\n", text
        )
        EXAMPLE.write_text(new, encoding="utf-8")
        return len(blocks)
    stale = [b for b in blocks if found[b] != blocks[b]]
    assert not stale, (
        f"docs/EXAMPLE.md blocks {stale} are not what the code produces from the fixtures; "
        "run `uv run python scripts/check_readme.py --write` and review the diff"
    )
    return len(blocks)


def main() -> None:
    write = "--write" in sys.argv[1:]
    positions = check_install_lines()
    check_documented_facts()
    count = check_example(write=write)
    verb = "re-derived" if write else "match the code"
    print(
        f"README ok: install lines at words {positions} (limit {WORD_LIMIT}) match examples/; "
        f"docs/EXAMPLE.md: {count} output blocks {verb}; as_of (UTC) and exit statuses bound"
    )


if __name__ == "__main__":
    main()
