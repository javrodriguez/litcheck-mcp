# Recorded responses: where they came from

Every `<name>.body` here is a response recorded live by `core/tools/record_fixture.py`,
byte for byte; its `<name>.meta.json` holds the URL, status, date, headers, sha256 and
provenance. They belong to the services that served them: NCBI (E-utilities, LitSense 2.0,
the PMC ID Converter), the PMC Cloud Service, Europe PMC (EMBL-EBI), Crossref (including the
Retraction Watch data it distributes) and OpenAlex (OurResearch; its data is CC0).

`pmc-text-pmc10496602.1.body` is the full text of an article distributed under
Creative Commons Attribution 4.0 (https://creativecommons.org/licenses/by/4.0/), as its PMC
metadata (`pmc-meta-pmc10496602.1.body`) records:

Lotufo PA. New findings about atherosclerosis in Brazil from the Brazilian Longitudinal Study
of Adult Health (ELSA-Brasil). São Paulo Medical Journal 2016;134(3):185-186.
doi:10.1590/1516-3180.2016.1344090516. PMCID PMC10496602.

It is kept unchanged, as test data for the quote checker.

`sample.log` is not a recorded response: it is a log litcheck wrote from these fixtures, and
`core/tests/test_cli.py` re-derives it byte for byte.
