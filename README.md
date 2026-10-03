# litcheck-mcp

[![CI](https://github.com/javrodriguez/litcheck-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/javrodriguez/litcheck-mcp/actions/workflows/ci.yml)

**A prior-work checker for scientists and their AI agents.** litcheck checks quoted passages against pinned open-access PubMed Central texts and checks retraction status; every search it runs goes into an append-only, hash-chained log.

> It never tells you a hypothesis is novel. It gives you a dated record of what was searched and what was found, and, where open-access text exists, checks whether each quoted passage appears in it.

## Install

Clone it, then add it to your MCP client ([`uv`](https://docs.astral.sh/uv/) must be on your PATH):

```bash
git clone https://github.com/javrodriguez/litcheck-mcp
```

**Claude Code:**

```bash
claude mcp add litcheck -- uv --directory /ABS/PATH/TO/litcheck-mcp run litcheck-mcp
```

**Codex:**

```bash
codex mcp add litcheck -- uv --directory /ABS/PATH/TO/litcheck-mcp run litcheck-mcp
```

Replace `/ABS/PATH/TO/litcheck-mcp` with the clone's absolute path. The first launch installs
the server's dependencies (`mcp`, `pydantic`) into the clone's own environment.

## Worked example

[docs/EXAMPLE.md](docs/EXAMPLE.md) takes one CC BY paper through the whole loop: a true quote
comes back `FOUND` with its offsets, the same quote with one word changed comes back
`NOT_FOUND`, the paper's retraction status is reported with its sources, and the log's chain
is verified. Every output on that page is re-derived from recorded responses by
`scripts/check_readme.py`, so it shows what the code does.

## What it checks, and what it does not

- **Quotes**, against the paper's open-access text from the
  [PMC Cloud Service](https://pmc.ncbi.nlm.nih.gov/tools/cloud/), pinned by version and accepted
  only if its bytes match the md5 in PMC's metadata. Matching is exact after a pinned
  normalisation (`q1`: Unicode NFKC, straight quotes, one dash, collapsed whitespace; case
  kept). Verdicts: `FOUND`, `NOT_FOUND`, `TOO_SHORT` (under 20 characters), `NOT_CHECKABLE`
  (no open-access text in PMC), `UNVERIFIABLE` (a source could not be read).
- **Only open-access full text can be quote-checked.** Paywalled papers, and author
  manuscripts PMC does not mark as open access, come back `NOT_CHECKABLE`.
- **Retraction status**, from PMC's `is_retracted` flag and Crossref's notices about the DOI
  (retraction, withdrawal and removal count; corrections do not; an expression of concern is
  reported separately). `NOT_RETRACTED_AS_OF <date>` needs every consulted source to have
  answered; otherwise the status is `UNVERIFIABLE`.
- **No support verdict is computed.** Whether a passage supports, contradicts or is absent
  from a claim is recorded only when a person or a named judge gives it (`record_support`).
- **Searches are recorded, and a search can miss papers.** Europe PMC, LitSense 2.0, PubMed
  and OpenAlex citations are queried as asked; each query, its parameters, the response's
  sha256 and the returned ids go into the log, failed searches included. An empty result is
  a record of one query, not evidence that nothing exists.

## Tools

| Tool | What it does |
|---|---|
| `check_quote` | resolve the paper, fetch its pinned open-access text, look for the quote; licence and retraction status alongside |
| `resolve_identifier` | DOI, PMID or PMCID to the other two (PMC ID converter, Europe PMC fallback for DOIs) |
| `retraction_status` | PMC's flag and Crossref's notices, with the date and response hash of each check |
| `search_literature` | one recorded search on `europe_pmc`, `litsense` or `pubmed` |
| `citing_papers` | works citing a paper, from OpenAlex, recorded |
| `verify_log` | re-walk the log's hash chain |
| `record_support` | store a person's or a named judge's verdict (`supports`, `contradicts`, `absent`) about an evidence line |

## Command line

The core is standard-library Python that runs on Python 3.6 or newer, with no install:

```bash
./litcheck check --id PMC10496602 --quote "Arteriosclerosis consists of functional depletion of large-artery elasticity."
./litcheck search litsense "large-artery elasticity" --limit 5
./litcheck verify-log
./litcheck annotate --seq 1 --support supports --by "your name"
```

`check` exits 0 only for `FOUND`; `verify-log` exits 0 only for an intact chain.

## The log

One JSON object per line: `seq`, a UTC timestamp, the kind (`evidence`, `search`, `annotate`),
the sha256 of the previous line, its payload, and its own sha256. Nothing in litcheck rewrites
a line. `verify-log` (or `verify_log`) reports the first line that does not fit; a cut-off
tail cannot be seen from the file alone, so keep the head hash it prints if that matters.

| System | Default location |
|---|---|
| Windows | `%LOCALAPPDATA%\litcheck\log.jsonl` |
| macOS | `~/Library/Application Support/litcheck/log.jsonl` |
| Linux | `$XDG_DATA_HOME/litcheck/log.jsonl`, else `~/.local/share/litcheck/log.jsonl` |

Set `LITCHECK_LOG` to put it elsewhere (for one project, say); `--log` does the same per call.

## Etiquette

Set `LITCHECK_CONTACT` to an address the services can reach you at. litcheck sends it only
with each request (in the User-Agent and as the `email`/`mailto` parameter NCBI, Europe PMC,
Crossref and OpenAlex ask for); it is never written to the log or to a recorded fixture. With
Claude Code, add `-e LITCHECK_CONTACT=you@example.org` before `--`; with Codex,
`--env LITCHECK_CONTACT=you@example.org`.

Rate limits are honoured per host: NCBI E-utilities and the ID converter 3 requests a second
(no API key), LitSense one a second, Europe PMC 5 a second, OpenAlex and Crossref 10 a second.
429 and 5xx answers are retried at most twice, with backoff; then the result is
`UNVERIFIABLE`.

## Tests

```bash
uv sync --dev
uv run pytest -q                                              # the MCP server
python3 -m unittest discover -s core/tests -t core            # the core, offline
uv run python scripts/check_readme.py                         # README and worked example
```

The core's tests replay responses recorded live by `core/tools/record_fixture.py`; a replay
refuses any URL it was not given and any body whose sha256 differs from its record.
`LITCHECK_NETWORK_TESTS=1` runs the live smoke test against the real services. The Europe
PMC search, Crossref and OpenAlex paths have no recorded responses yet (the recording
environment could not reach those hosts); their tests are skipped and say so.

## Credits

litcheck reads public services and is grateful to the people who run them:
[Europe PMC](https://europepmc.org/) (EMBL-EBI); NCBI, for
[E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25501/),
[LitSense 2.0](https://www.ncbi.nlm.nih.gov/research/litsense2/), the
[PMC Cloud Service](https://pmc.ncbi.nlm.nih.gov/tools/cloud/) and the
[PMC ID Converter](https://pmc.ncbi.nlm.nih.gov/tools/id-converter-api/);
[Crossref](https://www.crossref.org/), including the Retraction Watch data it distributes;
and [OpenAlex](https://openalex.org/).

The pinned-PMC gate and quote matcher are ported from [peerpanel](https://github.com/javrodriguez/peerpanel).

Built by Javier Rodríguez Hernáez · [LinkedIn](https://www.linkedin.com/in/jrodriguezhernaez/) · [GitHub](https://github.com/javrodriguez)

Built for GARS, the [genomics agentic research system](https://github.com/javrodriguez/genomics-agentic-research-system).

## Licence

MIT, for the source code. The recorded responses under `core/tests/fixtures/` belong to the
services that served them; the one article text among them is CC BY and attributed in
[docs/EXAMPLE.md](docs/EXAMPLE.md).
