"""Typed response models: the output contract every tool returns.

server.py wraps the plain dicts the core returns into these, so the
outputSchema an MCP client sees is explicit and versioned with the package.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

QuoteVerdict = Literal["FOUND", "NOT_FOUND", "TOO_SHORT", "NOT_CHECKABLE", "UNVERIFIABLE"]
ResolveStatus = Literal["RESOLVED", "NOT_FOUND", "UNVERIFIABLE"]
RetractionStatus = Literal["RETRACTED", "NOT_RETRACTED_AS_OF", "UNVERIFIABLE"]
SearchStatus = Literal["SEARCHED", "UNVERIFIABLE"]
Support = Literal["supports", "contradicts", "absent"]


class ResolvedIds(BaseModel):
    identifier: str = Field(description="The identifier as it was given")
    status: ResolveStatus = Field(
        description="NOT_FOUND: not in PubMed Central (and, for a DOI, not in Europe PMC); a "
        "PMID or PMCID is not looked up elsewhere, so NOT_FOUND does not mean it does not exist"
    )
    pmid: str | None
    pmcid: str | None
    doi: str | None
    source: str | None = Field(description="Which service answered: pmc-idconv or europe-pmc")
    reason: str | None = Field(description="Why it is not RESOLVED, or why there is no PMCID")


class RetractionSource(BaseModel):
    source: Literal["pmc", "crossref"]
    url: str | None
    checked_at: str | None = Field(
        description="UTC time of the response this rests on; null when no response came"
    )
    response_sha256: str | None
    retracted: bool | None = Field(description="null when this source gave no answer")
    concern: bool
    notices: list[dict[str, Any]]
    error: str | None


class RetractionResult(BaseModel):
    identifier: str | None = None
    status: RetractionStatus
    as_of: str | None = Field(
        description="For NOT_RETRACTED_AS_OF: the date of the earliest check; no retraction "
        "notice was found in the sources consulted as of then"
    )
    concern: bool = Field(description="An expression of concern is on record")
    reason: str | None
    sources: list[RetractionSource]


class EvidenceResult(BaseModel):
    verdict: QuoteVerdict = Field(
        description=(
            "FOUND: the quote occurs, as a substring, in the pinned open-access text. "
            "NOT_FOUND: it does not. "
            "TOO_SHORT: under 20 characters, not searched. NOT_CHECKABLE: no open-access text "
            "in PMC, or the identifier was not found (see resolved.status and reason). "
            "UNVERIFIABLE: a source could not be read or verified, or litcheck failed (see "
            "reason); nothing was concluded."
        )
    )
    reason: str | None
    identifier: str
    claim: str | None
    resolved: ResolvedIds
    pmc_outcome: str | None
    pmc_version: int | None
    text_sha256: str | None
    text_md5_ok: bool | None
    license_code: str | None
    retraction: RetractionResult
    quote: str
    normalisation: str
    quote_offsets: list[int] | None = Field(
        description="[start, end) of the match in the normalised text"
    )
    paragraph: int | None = Field(
        description="0-based index of the blank-line-separated block of the text"
    )
    casefold_found: bool | None = Field(description="The quote occurs when case is ignored")
    log_seq: int | None
    log_path: str


class SearchItem(BaseModel):
    source: str
    pmid: str | None
    pmcid: str | None
    doi: str | None
    title: str | None
    year: str | None
    text: str | None = Field(default=None, description="LitSense: the matching sentence or passage")
    section: str | None = None
    score: float | None = None
    openalex_id: str | None = None
    epmc_id: str | None = Field(default=None, description="Europe PMC: source:id")


class SearchResult(BaseModel):
    engine: str
    query: str
    status: SearchStatus = Field(
        description="UNVERIFIABLE means the search did not complete: an empty item list then "
        "says nothing about what exists"
    )
    hit_count: int | None
    items: list[SearchItem]
    reason: str | None
    response_sha256: str | None
    log_seq: int | None
    log_path: str


class LogStatus(BaseModel):
    path: str
    lines: int
    chain_ok: bool
    first_bad_seq: int | None
    reason: str | None
    head_sha256: str | None = Field(
        description="sha256 of the last line. The chain catches accidental and naive edits; "
        "a rewrite that recomputes every hash, or a cut-off tail, is caught only by comparing "
        "against a head hash kept elsewhere"
    )


class SupportRecorded(BaseModel):
    seq: int = Field(description="The annotation's own line number in the log")
    target_seq: int
    support: Support
    by: str
    log_path: str
