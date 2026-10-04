"""MCP integration: every tool round-trips through a real client.

The in-memory tests drive the actual server object over MCP, on recorded
responses; the stdio test launches the package as a real subprocess, as an
MCP client (Claude Code, Codex) would.
"""

import sys
from pathlib import Path

from mcp import StdioServerParameters
from mcp.client.client import Client

from litcheck_mcp.server import server

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS = {
    "check_quote",
    "resolve_identifier",
    "retraction_status",
    "search_literature",
    "citing_papers",
    "verify_log",
    "record_support",
}
TRUE_QUOTE = "Arteriosclerosis consists of functional depletion of large-artery elasticity."
CHANGED_QUOTE = "Arteriosclerosis consists of functional depletion of small-artery elasticity."


async def test_list_tools_names_and_schemas():
    async with Client(server, raise_exceptions=True) as client:
        tools = (await client.list_tools()).tools
        assert {t.name for t in tools} == TOOLS
        for t in tools:
            assert t.description, f"{t.name} has no description"
            assert t.output_schema is not None, f"{t.name} has no output schema"
            for name, prop in t.input_schema.get("properties", {}).items():
                assert prop.get("description"), f"{t.name}.{name} has no description"


async def test_check_quote_found_and_not_found(replay):
    async with Client(server, raise_exceptions=True) as client:
        r = await client.call_tool(
            "check_quote", {"identifier": "PMC10496602", "quote": TRUE_QUOTE, "claim": "c"}
        )
        assert not r.is_error
        sc = r.structured_content
        assert sc["verdict"] == "FOUND"
        assert sc["license_code"] == "CC BY"
        assert sc["pmc_version"] == 1
        assert sc["text_md5_ok"] is True
        assert sc["text_sha256"] == (
            "ec1fd2908965cd8ff65c09e78786448d7f4b17fdb413ab00764fff7a00e235c0"
        )
        assert sc["quote_offsets"] == [2275, 2352]
        assert sc["paragraph"] == 10
        assert sc["resolved"]["pmid"] == "27355798"
        assert sc["retraction"]["status"] == "NOT_RETRACTED_AS_OF"  # PMC and Crossref both answer
        pmc = [s for s in sc["retraction"]["sources"] if s["source"] == "pmc"][0]
        assert pmc["retracted"] is False
        assert sc["log_seq"] == 1
        assert sc["log_path"] == str(replay)

        r = await client.call_tool(
            "check_quote", {"identifier": "PMID 27355798", "quote": CHANGED_QUOTE}
        )
        sc = r.structured_content
        assert sc["verdict"] == "NOT_FOUND"
        assert sc["quote_offsets"] is None
        assert sc["log_seq"] == 2


async def test_check_quote_not_open_access(replay):
    async with Client(server, raise_exceptions=True) as client:
        r = await client.call_tool(
            "check_quote", {"identifier": "PMC13599058", "quote": TRUE_QUOTE}
        )
        sc = r.structured_content
        assert sc["verdict"] == "NOT_CHECKABLE"
        assert sc["license_code"] == "TDM"
        assert sc["pmc_outcome"] == "NOT_OPEN_ACCESS"


async def test_resolve_identifier(replay):
    async with Client(server, raise_exceptions=True) as client:
        r = await client.call_tool(
            "resolve_identifier",
            {"identifier": "https://doi.org/10.1590/1516-3180.2016.1344090516"},
        )
        sc = r.structured_content
        assert sc["status"] == "RESOLVED"
        assert (sc["pmid"], sc["pmcid"]) == ("27355798", "PMC10496602")
        assert sc["source"] == "pmc-idconv"


async def test_retraction_status(replay):
    async with Client(server, raise_exceptions=True) as client:
        r = await client.call_tool("retraction_status", {"identifier": "PMC12829825"})
        sc = r.structured_content
        assert sc["status"] == "RETRACTED"
        assert sc["identifier"] == "PMC12829825"
        r = await client.call_tool("retraction_status", {"identifier": "PMC10496602"})
        sc = r.structured_content
        assert sc["status"] == "NOT_RETRACTED_AS_OF"
        assert [s["source"] for s in sc["sources"]] == ["pmc", "crossref"]


async def test_search_literature(replay):
    async with Client(server, raise_exceptions=True) as client:
        r = await client.call_tool(
            "search_literature",
            {
                "engine": "litsense",
                "query": "arteriosclerosis functional depletion of large-artery elasticity",
                "limit": 3,
            },
        )
        sc = r.structured_content
        assert sc["status"] == "SEARCHED"
        assert sc["hit_count"] == 100
        assert [i["pmcid"] for i in sc["items"]][:1] == ["PMC3910517"]
        assert len(sc["items"]) == 3
        assert sc["log_seq"] == 1
        r = await client.call_tool(
            "search_literature",
            {"engine": "europe_pmc", "query": "unrecorded query"},
        )
        sc = r.structured_content
        assert sc["status"] == "UNVERIFIABLE"
        assert sc["items"] == []
        assert sc["log_seq"] == 2


async def test_citing_papers_records_a_failed_search(replay):
    async with Client(server, raise_exceptions=True) as client:
        r = await client.call_tool("citing_papers", {"identifier": "W2741809807"})
        sc = r.structured_content
        assert sc["engine"] == "openalex_citing"
        assert sc["status"] == "UNVERIFIABLE"  # api.openalex.org not recorded
        assert sc["log_seq"] == 1


async def test_verify_log_and_record_support(replay):
    async with Client(server, raise_exceptions=True) as client:
        await client.call_tool("check_quote", {"identifier": "PMC10496602", "quote": TRUE_QUOTE})
        r = await client.call_tool(
            "record_support", {"seq": 1, "support": "supports", "by": "example reviewer"}
        )
        sc = r.structured_content
        assert (sc["seq"], sc["target_seq"], sc["support"]) == (2, 1, "supports")
        r = await client.call_tool("verify_log", {})
        sc = r.structured_content
        assert sc["chain_ok"] is True
        assert sc["lines"] == 2
        assert sc["path"] == str(replay)


async def test_no_bare_error_ever_reaches_the_agent(replay):
    """Every reachable failure names a reason the model can act on."""
    calls = [
        ("check_quote", {"identifier": "twenty-seven", "quote": TRUE_QUOTE}),
        ("check_quote", {"identifier": "PMC10496602", "quote": "   "}),
        ("resolve_identifier", {"identifier": "PMC10496602 PMID 27355798"}),
        ("record_support", {"seq": 5, "support": "absent", "by": "someone"}),
        ("citing_papers", {"identifier": "not an id"}),
    ]
    async with Client(server) as client:
        for name, args in calls:
            r = await client.call_tool(name, args)
            assert r.is_error, f"{name} should have failed"
            text = r.content[0].text
            assert text.strip() != f"Error executing tool {name}", f"{name} gave a bare error"
            assert len(text) > 60, f"{name} error too terse to act on: {text}"


async def test_unexpected_failures_are_wrapped_not_bare(replay, monkeypatch):
    """The backstop turns a genuine bug into something the agent can still read."""
    from litcheck import cli

    def boom(**kwargs):
        raise RuntimeError("simulated internal defect")

    monkeypatch.setattr(cli, "resolve_identifier", boom)
    async with Client(server) as client:
        r = await client.call_tool("resolve_identifier", {"identifier": "PMC10496602"})
        assert r.is_error
        assert "simulated internal defect" in r.content[0].text
        assert "bug in litcheck" in r.content[0].text


async def test_a_bug_inside_check_comes_back_as_unverifiable(replay, monkeypatch):
    from litcheck import quote

    def boom(*args):
        raise RuntimeError("simulated defect in matching")

    monkeypatch.setattr(quote, "check", boom)
    async with Client(server, raise_exceptions=True) as client:
        r = await client.call_tool(
            "check_quote", {"identifier": "PMC10496602", "quote": TRUE_QUOTE}
        )
        sc = r.structured_content
        assert sc["verdict"] == "UNVERIFIABLE"
        assert "simulated defect in matching" in sc["reason"]


async def test_real_stdio_subprocess_roundtrip(tmp_path):
    """The packaged entry point answers over stdio, as a real MCP client launches it."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "litcheck_mcp"],
        cwd=str(REPO_ROOT),
        env={"LITCHECK_LOG": str(tmp_path / "log.jsonl")},
    )
    async with Client(params, raise_exceptions=True) as client:
        tools = (await client.list_tools()).tools
        assert {t.name for t in tools} == TOOLS
        r = await client.call_tool("verify_log", {})
        assert r.structured_content["chain_ok"] is False  # no log written yet
        assert r.structured_content["lines"] == 0


RETRACTED_RULE = (
    "Treat a FOUND quote in a paper whose retraction status is RETRACTED as unusable "
    "support: the passage is in the text, but the paper cannot back a claim."
)


async def test_found_in_a_retracted_paper_carries_the_retraction(replay, monkeypatch):
    """The agent sees FOUND and RETRACTED together, and is told what that pair means."""
    from litcheck_mcp import server as module

    recorded = module.transport
    meta_url = "https://pmc-oa-opendata.s3.amazonaws.com/PMC10496602.1/PMC10496602.1.json"
    flipped = []

    def flagged(url):
        status, body, headers = recorded(url)
        if url == meta_url:
            assert b'"is_retracted": false' in body
            body = body.replace(b'"is_retracted": false', b'"is_retracted": true')
            flipped.append(url)
        return status, body, headers

    monkeypatch.setattr(module, "transport", flagged)
    async with Client(server, raise_exceptions=True) as client:
        sc = (
            await client.call_tool(
                "check_quote", {"identifier": "PMC10496602", "quote": TRUE_QUOTE}
            )
        ).structured_content
    assert flipped == [meta_url]
    assert (sc["verdict"], sc["retraction"]["status"]) == ("FOUND", "RETRACTED")
    assert RETRACTED_RULE in " ".join((server.instructions or "").split())


async def test_every_as_of_description_says_utc():
    async with Client(server, raise_exceptions=True) as client:
        tools = (await client.list_tools()).tools
    texts = {f"tool {t.name}": t.description or "" for t in tools}
    for t in tools:
        for name, prop in (t.output_schema or {}).get("properties", {}).items():
            texts[f"tool {t.name} -> {name}"] = prop.get("description", "")
        for name, sub in (t.output_schema or {}).get("$defs", {}).items():
            for field, prop in sub.get("properties", {}).items():
                texts[f"tool {t.name} $defs {name}.{field}"] = prop.get("description", "")
    texts["server instructions"] = server.instructions or ""
    hits = {k: v for k, v in texts.items() if "as of" in " ".join(v.split())}
    assert "tool retraction_status" in hits
    assert any("as_of" in k for k in hits), sorted(hits)
    for where, text in hits.items():
        assert "UTC" in text, f"{where} says 'as of' without saying the date is UTC"
