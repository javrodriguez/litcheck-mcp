"""The MCP layer: server construction, the seven tools, stdio entrypoint.

Thin by design: each tool calls the standard-library core (`litcheck`) and
wraps its plain dict in a typed model. Anticipated failures surface as
ToolError so the calling agent can read the reason and correct course;
nothing here prints to stdout, which is the stdio transport.

`transport` and `clock` are module-level so tests can swap in the recorded
fixtures with monkeypatch; no environment switch selects replay.
"""

from collections.abc import Callable
from typing import Annotated, Any, Literal

from litcheck import cli, paths, record
from litcheck import search as core_search
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from litcheck_mcp import __version__, models

transport: Callable[..., Any] | None = None  # None: the live transport
clock: Callable[[], str] | None = None  # None: the system UTC clock

HONESTY_RULE = (
    "It never tells you a hypothesis is novel. It gives you a dated record of what was "
    "searched and what was found, and, where open-access text exists, checks whether each "
    "quoted passage appears in it."
)

server = MCPServer(
    name="litcheck",
    version=__version__,
    instructions=(
        "litcheck is a prior-work checker for scientists and their agents. "
        + HONESTY_RULE
        + " Use check_quote before you cite a passage: it resolves the identifier, fetches the "
        "paper's pinned open-access text from PubMed Central (md5-verified), looks for the "
        "quote, and reports the paper's licence and retraction status. Only open-access text "
        "can be checked; anything else, an identifier that was not found included, comes back "
        "NOT_CHECKABLE (resolved.status and reason say which). Use search_literature and "
        "citing_papers to look for prior work: every search that is sent is recorded, failed "
        "ones too, but a search can miss papers, so an empty result is not evidence that "
        "nothing exists. "
        "Use resolve_identifier to map a DOI, PMID or PMCID to the others, and "
        "retraction_status before relying on a paper. litcheck computes no support verdict: "
        "whether a passage supports, contradicts or is absent from a claim is a judgement for "
        "a person or a named judge, recorded with record_support. verify_log re-walks the "
        "log's hash chain. A verdict of UNVERIFIABLE means a source could not be read or "
        "verified, or "
        "litcheck failed (see reason); report it as such rather than as a negative. "
        "resolve_identifier's NOT_FOUND for a PMID or PMCID means not in PubMed Central, not "
        "that the paper does not exist."
    ),
)

_IDENTIFIER = Annotated[
    str,
    Field(
        description=(
            'One paper: a DOI ("10.1590/1516-3180.2016.1344090516" or a doi.org URL), a PMCID '
            '("PMC10496602") or a PMID written with its cue ("PMID 27355798")'
        )
    ),
]
_LIMIT = Annotated[int, Field(description="How many items to return (1-100)", ge=1, le=100)]


def _log_path() -> str:
    return paths.default_log_path()


def _run(fn: Callable[..., Any], /, **kwargs: Any) -> Any:
    try:
        return fn(**kwargs)
    except (cli.InputError, record.LogError, core_search.SearchError) as e:
        raise ToolError(f"{e}. Change the request and call {fn.__name__} again.") from e
    except Exception as e:  # backstop: an agent must never receive a reason-less failure
        args = ", ".join(f"{k}={v!r}" for k, v in kwargs.items() if k not in ("transport", "clock"))
        raise ToolError(
            f"{fn.__name__} failed unexpectedly on ({args}): {type(e).__name__}: {e}. "
            "This is a bug in litcheck, not in your request; please report it."
        ) from e


def _resolved(identifier: str, data: dict[str, Any]) -> models.ResolvedIds:
    return models.ResolvedIds(
        identifier=identifier,
        status=data["status"],
        pmid=data["pmid"],
        pmcid=data["pmcid"],
        doi=data["doi"],
        source=data["source"],
        reason=data["reason"],
    )


def _retraction(identifier: str | None, data: dict[str, Any]) -> models.RetractionResult:
    return models.RetractionResult(identifier=identifier, **data)


@server.tool()
def check_quote(
    identifier: _IDENTIFIER,
    quote: Annotated[
        str,
        Field(description="The passage exactly as you would quote it (20 characters or more)"),
    ],
    claim: Annotated[
        str | None,
        Field(description="Optional: the claim you are citing this passage for, kept in the log"),
    ] = None,
) -> models.EvidenceResult:
    """Check whether a quoted passage appears in the paper's pinned open-access PMC text.

    Also reports the text's version, sha256 and licence, and the paper's retraction status,
    and appends an evidence line to the log. Exact match after normalisation q1 (Unicode
    NFKC, straight quotes, one dash, collapsed whitespace; case kept). It does not judge
    whether the passage supports the claim.
    """
    log = _log_path()
    ev = _run(
        cli.run_check,
        identifier=identifier,
        quote=quote,
        claim=claim,
        transport=transport,
        log=log,
        clock=clock,
    )
    q, pmc = ev["quote"], ev["pmc"]
    resolved = ev["resolved"] or {
        "status": "UNVERIFIABLE",
        "pmid": None,
        "pmcid": None,
        "doi": None,
        "source": None,
        "reason": ev["reason"],
    }
    return models.EvidenceResult(
        verdict=ev["verdict"],
        reason=ev["reason"],
        identifier=identifier,
        claim=claim,
        resolved=_resolved(identifier, resolved),
        pmc_outcome=pmc["outcome"],
        pmc_version=pmc["version"],
        text_sha256=pmc["text_sha256"],
        text_md5_ok=pmc["text_md5_ok"],
        license_code=pmc["license_code"],
        retraction=_retraction(identifier, ev["retraction"]),
        quote=quote,
        normalisation=q["normalisation"],
        quote_offsets=q["offsets"],
        paragraph=q["paragraph"],
        casefold_found=q["casefold_found"],
        log_seq=ev["log_seq"],
        log_path=log,
    )


@server.tool()
def resolve_identifier(identifier: _IDENTIFIER) -> models.ResolvedIds:
    """Map one DOI, PMID or PMCID to the other two, through the PMC ID converter.

    The converter knows only articles in PubMed Central; a DOI it cannot map is also looked
    up in Europe PMC. NOT_FOUND means not in PMC (and, for a DOI, not in Europe PMC either): a
    PMID or PMCID is not looked up elsewhere, so NOT_FOUND does not mean the paper does not
    exist. UNVERIFIABLE means a service could not be read.
    """
    data = _run(cli.resolve_identifier, identifier=identifier, transport=transport)
    return _resolved(identifier, data)


@server.tool()
def retraction_status(identifier: _IDENTIFIER) -> models.RetractionResult:
    """Is the paper retracted? Reads PMC's is_retracted flag and Crossref's notices.

    Retraction, withdrawal and removal notices count; corrections do not; an expression of
    concern is reported separately. NOT_RETRACTED_AS_OF needs every consulted source to have
    answered, and is dated; if a source could not be read the status is UNVERIFIABLE. A paper
    with no copy in the PMC Cloud Service is checked on Crossref alone; `sources` shows which
    sources answered.
    """
    _, data = _run(cli.retraction_for, identifier=identifier, transport=transport, clock=clock)
    return _retraction(identifier, data)


def _search(engine: str, query: str, limit: int) -> models.SearchResult:
    log = _log_path()
    data = _run(
        cli.run_search,
        engine=engine,
        query=query,
        limit=limit,
        transport=transport,
        log=log,
        clock=clock,
    )
    keys = set(models.SearchItem.model_fields)
    return models.SearchResult(
        engine=data["engine"],
        query=data["query"],
        status=data["status"],
        hit_count=data["hit_count"],
        items=[
            models.SearchItem(**{k: v for k, v in item.items() if k in keys})
            for item in data["items"]
        ],
        reason=data["reason"],
        response_sha256=data["response_sha256"],
        log_seq=data["log_seq"],
        log_path=log,
    )


@server.tool()
def search_literature(
    engine: Annotated[
        Literal["europe_pmc", "litsense", "pubmed"],
        Field(
            description=(
                "europe_pmc: Europe PMC query syntax (TITLE_ABS:, FIRST_PDATE:[a TO b], ...); "
                "litsense: a sentence-level semantic search of PubMed and PMC (no date filter); "
                "pubmed: PubMed query syntax through E-utilities"
            )
        ),
    ],
    query: Annotated[str, Field(description="The query, in the chosen engine's syntax")],
    limit: _LIMIT = 25,
) -> models.SearchResult:
    """Run one literature search and record it, with its response hash, in the log.

    hit_count is what the engine reported; items are the first `limit` of them. A search can
    miss papers: status SEARCHED with few items is a record of this query, not of the field.
    """
    return _search(engine, query, limit)


@server.tool()
def citing_papers(
    identifier: Annotated[
        str, Field(description="The cited work: a DOI or an OpenAlex work id (W123...)")
    ],
    limit: _LIMIT = 25,
) -> models.SearchResult:
    """List works that cite a paper, from OpenAlex, and record the search in the log."""
    return _search("citing", identifier, limit)


@server.tool()
def verify_log() -> models.LogStatus:
    """Re-walk the log's hash chain and report the first line that does not fit, if any.

    This catches accidental and naive edits. The hashes are not keyed, so a rewrite that
    recomputes every later hash, or a cut-off tail, is caught only by comparing head_sha256
    with a copy kept elsewhere. A log that does not exist yet reports chain_ok false.
    """
    log = _log_path()
    data = _run(record.verify, path=log)
    return models.LogStatus(
        path=log,
        lines=data["lines"],
        chain_ok=data["ok"],
        first_bad_seq=data["first_bad_seq"],
        reason=data["reason"],
        head_sha256=data["head_sha256"],
    )


@server.tool()
def record_support(
    seq: Annotated[int, Field(description="The log line (an evidence line) being judged")],
    support: Annotated[
        Literal["supports", "contradicts", "absent"],
        Field(description="The verdict: does the quoted passage support the claim?"),
    ],
    by: Annotated[
        str,
        Field(description="Who judged: a person's name or a named judge; litcheck never does"),
    ],
) -> models.SupportRecorded:
    """Record a person's or a named judge's support verdict about an evidence line.

    litcheck computes no support verdict itself; this stores one that was given, with who
    gave it, as a new line in the log.
    """
    log = _log_path()
    line = _run(record.annotate, path=log, target_seq=seq, support=support, by=by, clock=clock)
    return models.SupportRecorded(
        seq=line["seq"],
        target_seq=line["target_seq"],
        support=line["support"],
        by=line["by"],
        log_path=log,
    )


def main() -> None:
    """Console-script entry point (stdio transport)."""
    server.run()
