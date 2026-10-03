# Worked example

One paper, one true quote, the same quote with one word changed, the paper's retraction
status, and the log checked afterwards: first on the command line, then as MCP tool calls.

Every output block on this page is produced by the code from responses recorded live on
3 October 2026 (`core/tests/fixtures/`), with the clock pinned to that date and the log path
shown as `<LOG>`. `scripts/check_readme.py` re-runs every step and fails if any block differs
from what the code produces, so the page cannot drift from the code.

## The paper

Lotufo PA. *New findings about atherosclerosis in Brazil from the Brazilian Longitudinal Study
of Adult Health (ELSA-Brasil).* São Paulo Medical Journal 2016;134(3):185–186.
doi:[10.1590/1516-3180.2016.1344090516](https://doi.org/10.1590/1516-3180.2016.1344090516),
PMCID PMC10496602, PMID 27355798.

Its PMC metadata records the licence as `CC BY` (Creative Commons Attribution 4.0,
<https://creativecommons.org/licenses/by/4.0/>). The one sentence quoted on this page is taken
from it unchanged, under that licence, with this attribution.

The quote: *"Arteriosclerosis consists of functional depletion of large-artery elasticity."*

## On the command line

The core needs only Python 3.6 or newer; `./litcheck` runs it from a clone.

A true quote is `FOUND`. The offsets are character positions in the normalised text
(normalisation `q1`), and the paragraph is a 0-based index of blank-line-separated blocks of
the PMC text, its header blocks included (block 0 is the journal header):

<!-- output: cli-found -->
```text
$ ./litcheck check --id PMC10496602 --quote 'Arteriosclerosis consists of functional depletion of large-artery elasticity.' --claim 'Arteriosclerosis is a loss of large-artery elasticity.' --log '<LOG>'
verdict     FOUND
identifier  PMC10496602
resolved    pmid 27355798 · pmcid PMC10496602 · doi 10.1590/1516-3180.2016.1344090516
pmc text    version 1 · licence CC BY · FETCHED · md5 ok · sha256 ec1fd2908965cd8ff65c09e78786448d7f4b17fdb413ab00764fff7a00e235c0
retraction  NOT_RETRACTED_AS_OF 2026-10-03
            pmc: not retracted (checked 2026-10-03T21:32:25Z)
            crossref: not retracted (checked 2026-10-03T21:32:25Z)
quote       FOUND at characters 2275-2352 of the normalised (q1) text, paragraph 10
log         line 1 of <LOG>
(exit status 0)
```

The same sentence with *large* changed to *small* is `NOT_FOUND`, and the exit status says so:

<!-- output: cli-changed -->
```text
$ ./litcheck check --id PMC10496602 --quote 'Arteriosclerosis consists of functional depletion of small-artery elasticity.' --log '<LOG>'
verdict     NOT_FOUND
identifier  PMC10496602
resolved    pmid 27355798 · pmcid PMC10496602 · doi 10.1590/1516-3180.2016.1344090516
pmc text    version 1 · licence CC BY · FETCHED · md5 ok · sha256 ec1fd2908965cd8ff65c09e78786448d7f4b17fdb413ab00764fff7a00e235c0
retraction  NOT_RETRACTED_AS_OF 2026-10-03
            pmc: not retracted (checked 2026-10-03T21:32:25Z)
            crossref: not retracted (checked 2026-10-03T21:32:25Z)
quote       NOT_FOUND; ignoring case: not found
log         line 2 of <LOG>
(exit status 1)
```

Both runs appended a line to the log; the chain checks out:

<!-- output: cli-verify -->
```text
$ ./litcheck verify-log '<LOG>'
chain intact: 2 lines in <LOG>; head sha256 7468ba42a0e8f0b638f49a1bf45804e890220094358ef9a29646483ec29603fd
(exit status 0)
```

### About the retraction line

PMC's own metadata says the paper is not retracted, and Crossref's notices about the DOI
(the recorded `filter=updates:` response) list none. Both sources answered, so litcheck says
`NOT_RETRACTED_AS_OF` with the date of the check, never a bare "not retracted". Had either
source gone unread, it would say `UNVERIFIABLE` and name the missing source instead.

## As MCP tool calls

The same steps through the MCP server, as an agent sees them (`structuredContent`, on a
fresh log):

<!-- output: mcp-found -->
```text
> check_quote({"identifier": "PMC10496602", "quote": "Arteriosclerosis consists of functional depletion of large-artery elasticity."})
{
  "verdict": "FOUND",
  "reason": null,
  "identifier": "PMC10496602",
  "claim": null,
  "resolved": {
    "identifier": "PMC10496602",
    "status": "RESOLVED",
    "pmid": "27355798",
    "pmcid": "PMC10496602",
    "doi": "10.1590/1516-3180.2016.1344090516",
    "source": "pmc-idconv",
    "reason": null
  },
  "pmc_outcome": "FETCHED",
  "pmc_version": 1,
  "text_sha256": "ec1fd2908965cd8ff65c09e78786448d7f4b17fdb413ab00764fff7a00e235c0",
  "text_md5_ok": true,
  "license_code": "CC BY",
  "retraction": {
    "identifier": "PMC10496602",
    "status": "NOT_RETRACTED_AS_OF",
    "as_of": "2026-10-03",
    "concern": false,
    "reason": null,
    "sources": [
      {
        "source": "pmc",
        "url": "https://pmc-oa-opendata.s3.amazonaws.com/PMC10496602.1/PMC10496602.1.json",
        "checked_at": "2026-10-03T21:32:25Z",
        "response_sha256": "e55f38fe81f85325efd03351b3ffd660b513c318b213c36fc7634fde5292188f",
        "retracted": false,
        "concern": false,
        "notices": [],
        "error": null
      },
      {
        "source": "crossref",
        "url": "https://api.crossref.org/v1/works?filter=updates:10.1590/1516-3180.2016.1344090516",
        "checked_at": "2026-10-03T21:32:25Z",
        "response_sha256": "6ec0a900b362c5149fd8a58cf16525b414923941dd1284fb1f8083a4e7d54c97",
        "retracted": false,
        "concern": false,
        "notices": [],
        "error": null
      }
    ]
  },
  "quote": "Arteriosclerosis consists of functional depletion of large-artery elasticity.",
  "normalisation": "q1",
  "quote_offsets": [
    2275,
    2352
  ],
  "paragraph": 10,
  "casefold_found": true,
  "log_seq": 1,
  "log_path": "<LOG>"
}
```

<!-- output: mcp-changed -->
```text
> check_quote({"identifier": "PMC10496602", "quote": "Arteriosclerosis consists of functional depletion of small-artery elasticity."})
{
  "verdict": "NOT_FOUND",
  "reason": null,
  "identifier": "PMC10496602",
  "claim": null,
  "resolved": {
    "identifier": "PMC10496602",
    "status": "RESOLVED",
    "pmid": "27355798",
    "pmcid": "PMC10496602",
    "doi": "10.1590/1516-3180.2016.1344090516",
    "source": "pmc-idconv",
    "reason": null
  },
  "pmc_outcome": "FETCHED",
  "pmc_version": 1,
  "text_sha256": "ec1fd2908965cd8ff65c09e78786448d7f4b17fdb413ab00764fff7a00e235c0",
  "text_md5_ok": true,
  "license_code": "CC BY",
  "retraction": {
    "identifier": "PMC10496602",
    "status": "NOT_RETRACTED_AS_OF",
    "as_of": "2026-10-03",
    "concern": false,
    "reason": null,
    "sources": [
      {
        "source": "pmc",
        "url": "https://pmc-oa-opendata.s3.amazonaws.com/PMC10496602.1/PMC10496602.1.json",
        "checked_at": "2026-10-03T21:32:25Z",
        "response_sha256": "e55f38fe81f85325efd03351b3ffd660b513c318b213c36fc7634fde5292188f",
        "retracted": false,
        "concern": false,
        "notices": [],
        "error": null
      },
      {
        "source": "crossref",
        "url": "https://api.crossref.org/v1/works?filter=updates:10.1590/1516-3180.2016.1344090516",
        "checked_at": "2026-10-03T21:32:25Z",
        "response_sha256": "6ec0a900b362c5149fd8a58cf16525b414923941dd1284fb1f8083a4e7d54c97",
        "retracted": false,
        "concern": false,
        "notices": [],
        "error": null
      }
    ]
  },
  "quote": "Arteriosclerosis consists of functional depletion of small-artery elasticity.",
  "normalisation": "q1",
  "quote_offsets": null,
  "paragraph": null,
  "casefold_found": false,
  "log_seq": 2,
  "log_path": "<LOG>"
}
```

<!-- output: mcp-retraction -->
```text
> retraction_status({"identifier": "PMC10496602"})
{
  "identifier": "PMC10496602",
  "status": "NOT_RETRACTED_AS_OF",
  "as_of": "2026-10-03",
  "concern": false,
  "reason": null,
  "sources": [
    {
      "source": "pmc",
      "url": "https://pmc-oa-opendata.s3.amazonaws.com/PMC10496602.1/PMC10496602.1.json",
      "checked_at": "2026-10-03T21:32:25Z",
      "response_sha256": "e55f38fe81f85325efd03351b3ffd660b513c318b213c36fc7634fde5292188f",
      "retracted": false,
      "concern": false,
      "notices": [],
      "error": null
    },
    {
      "source": "crossref",
      "url": "https://api.crossref.org/v1/works?filter=updates:10.1590/1516-3180.2016.1344090516",
      "checked_at": "2026-10-03T21:32:25Z",
      "response_sha256": "6ec0a900b362c5149fd8a58cf16525b414923941dd1284fb1f8083a4e7d54c97",
      "retracted": false,
      "concern": false,
      "notices": [],
      "error": null
    }
  ]
}
```

<!-- output: mcp-verify -->
```text
> verify_log({})
{
  "path": "<LOG>",
  "lines": 2,
  "chain_ok": true,
  "first_bad_seq": null,
  "reason": null,
  "head_sha256": "185fbdb4fa9e8d00f2fdde1938e76656fb1973ddfac1df89814dd665a37c936b"
}
```

## What this example does not show

- Whether the sentence *supports* a claim. litcheck computes no support verdict; a person or
  a named judge records one with `record_support` (or `litcheck annotate`).
- Anything about papers outside PubMed Central's open-access text: those come back
  `NOT_CHECKABLE`.
- Searches. `search_literature` and `citing_papers` record every query and its response hash,
  but a search can miss papers, and an empty result is not evidence that nothing exists.
