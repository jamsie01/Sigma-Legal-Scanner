# Sigma Legal Search — Vacancy Scanner

A Python tool that checks official law-firm careers boards for qualified-lawyer vacancies, with London shown first. Covers **20 official law firm careers boards** across the UK and US.

Zero external dependencies: 100% Python standard library (Python 3.10+).

## Quick Start

```bash
cd Sigma-Legal-Scanner
python3 scanner.py scan-all
```

Useful commands:
```bash
python3 scanner.py scan tlt                  # One firm
python3 scanner.py scan-all --location london # London-only console output
python3 scanner.py scan-all --quiet          # Hide per-advert progress
python3 scanner.py history                   # Recent scans and counts
python3 -m unittest discover -s tests -v     # Run test suite offline
```


## Outputs

- `data/vacancies.sqlite3`: durable vacancy identities, first/last seen times, scan history and observations.
- `reports/tlt-latest.csv`: qualified-lawyer results for every office, suitable for a spreadsheet.
- `reports/tlt-london.csv`: qualified-lawyer vacancies that explicitly list London, including multiple-office jobs.
- `reports/tlt-latest.json`: latest scan, coverage, errors, exclusions, review cases and full results.
- `reports/tlt-scan-NNNN.json`: retained result for each scan, including failed scans.
- `RESULTS.md`: readable snapshot of all 31 roles, with London and stated PQE first.
- `VALIDATION.md`: observed live results, repeat-scan proof and test results from initial setup.

A CSV is the current scan's **observed results**, not a statement that previously seen but absent jobs are filled. Always read the accompanying JSON status. Missing practice/PQE fields remain null in JSON/SQLite and blank in CSV. Spreadsheet exports escape formula-leading characters; JSON/SQLite retain the original text.

## What NEW means

The permanent identity is `(firm, job_id)`. The first time an ID is successfully collected it is NEW. The first populated scan creates the baseline; its NEW entries are **not claims that the jobs were posted today**. Later scans only report unseen IDs as NEW. Changing a title, URL slug or location does not reset the identity. If an old ID disappears and returns, it is still previously seen.

Each completed collection is saved in one SQLite transaction. Partial scans may save successfully verified adverts. Failures, ambiguous roles and exclusions are recorded separately. This version **never automatically marks a vacancy removed or filled**, even after a successful empty scan. `last_seen` is an observation timestamp, not a claim that a previously seen vacancy is still open. Removing the database intentionally resets the baseline.

## Status and exit codes

| Status | Meaning | Exit code |
| --- | --- | --- |
| SUCCESS | Complete board and London cross-check, all relevant adverts verified, no unresolved role classification | 0 |
| LIMITED | Retrieval completed, but a role needs human qualification review | 1 |
| PARTIAL | Useful listing data found, but a page, advert or London cross-check failed | 2 |
| BLOCKED | No usable listing data; network, access or unexpected page structure | 2 |

A completely checked board with **zero London vacancies can be SUCCESS**. An empty or blocked HTML page is never assumed to mean zero vacancies. The JSON also exposes `board_complete` and `london_filter_complete`, so coverage can be inspected independently of role ambiguity.

## TLT source and collection method

The [official TLT legal careers page](https://www.tlt.com/careers/legal-roles) links to [TLT's careers board](https://apply.tlt.com/vacancies/). The board has Harbour-specific container IDs (`Harbour-Content-Container`); its implementation is a Harbour-style server-rendered careers site. No separate public vacancy API was identified or needed. Official HTML already contains the data, and each advert supplies structured `JobPosting` JSON-LD.

1. Fetch the complete unfiltered board with `urllib.request`.
2. Parse cards using a small standard-library HTML parser, preserving title, exact advert URL, ID, office and official category.
3. Follow the published numbered `/vacancies/page/N/` links. Validate the current page, page continuity and duplicate IDs to catch ignored pagination or changing results.
4. Discover London's current option value from `select#field_4811` (observed value `4420`). Fetch `?c[field_4811]=4420&submit=search`, retaining the filter on every subsequent page. Cross-check its IDs against explicit London locations on the complete board.
5. Exclude explicit training, paralegal and support roles. Examine legal and flexible-resource candidates; business-professional roles with a lawyer title are still checked.
6. Fetch candidate adverts sequentially. Match the JSON-LD job identifier to the URL ID and read the official sidebar reference (`TLT-6146`, for example). Reject mismatched listing/advert data. Keep the ID and reference separately: job ID `6013` currently has official reference `TLT-2290`, so references must not be synthesized from IDs.
7. Classify a qualified role using an explicit lawyer/solicitor/associate/legal-director title or a qualification requirement in the description. Keep unconfirmed cases in `review`; do not guess. Optional attorney admission alone is not a qualified-lawyer requirement.
8. Save observed results and audit records to SQLite, then write JSON and CSV files.

The category filter is `c[field_5559]`: observed values include legal careers `8948`, flexible resource `8949`, training `8947`, and business professionals `8950`. The role-type field is `field_5818`. We deliberately traverse the whole board so flexible-resource lawyer vacancies are not lost by selecting only “Legal careers”.

**Practice area:** use an official practice/department field if present. Otherwise preserve the subject after the separator in the official title, explicitly labelled `practice_area_source = official job-title suffix`. This is an advert subject, not a separately verified firm taxonomy. Titles without a suitable subject leave the value empty.

**PQE:** retain whole source paragraphs/bullets mentioning PQE, post-qualification experience or newly qualified status. This preserves ranges, alternatives and caveats; it does not invent a numeric minimum/maximum. Unstated PQE remains empty.

**London:** determined from the vacancy's office field and official filter, never from boilerplate mentioning the firm's London office. Remote roles are not assumed to be London roles.

## Performance and failure behaviour

There are no third-party Python dependencies, browser processes, Firecrawl calls, language-model calls or credentials in the runtime. Requests run one at a time with a short pause, a 20-second timeout, at most one retry for transient failures, a 2 MB response cap and a 100-page safety cap. HTTPS requests and redirects are restricted to the configured official host. Listing HTML trees are processed one page at a time. Each run reads live adverts again; there is no stale detail cache hiding changes.

If blocked in future, the scanner reports the failure instead of starting Chromium automatically. Investigate direct HTTP first, then consider Firecrawl or one headless Playwright browser only if necessary. Existing local MCP installations are useful for development but are not runtime dependencies.

The board has no observed snapshot token or authoritative total-count API. Cross-page duplicates, missing pages and London inconsistencies are detected, but a board changing during pagination can still shift results without detection. A scan is an observation over an interval. Site markup changes may require an update to the parser; the saved fixtures and tests help catch regressions.

## Source layout

```text
scanner.py              CLI, multi-worker orchestration, exclude/restore commands
registry.py             20 official firm configurations, ATS types, source URLs
validation.py           Live advert verification gates and recruiter exclusion rules
reporting.py            Markdown reports, browser checklist, dashboard, WhatsApp text
storage.py              SQLite transaction persistence, baseline vs NEW change tracking
models.py               Vacancy and ScanResult data structures
collectors/
  classify.py           Centralized fee-earning qualified role vs internal/support policy
  harbour.py            Harbour ATS collector (TLT)
  networx.py            Networx search API collector (Fieldfisher)
  allhires.py           AllHires candidate API collector (Lewis Silkin, Milbank)
  workday.py            Workday CXS API collector (Simpson Thacher, Cooley UK)
  cvmail.py             CVMail UK collector (Squire Patton Boggs, Kirkland & Ellis)
  taylorwessing.py      Winston Taylor EMEA / SuccessFactors collector
  withers.py            Withers careers collector
  fladgate.py           Fladgate collector with Alpine.js JSON extraction
  stewarts.py           Stewarts vacancies collector (HTML & PDF adverts)
  hausfeld.py           Hausfeld UK board collector
  mofo.py               Morrison Foerster Jibe API collector
  icims.py              iCIMS portal collector (Latham & Watkins)
  pending.py            Structured reporting for firms requiring custom workflow (Davis Polk, Paul Hastings)
  contact_only.py       Verified direct-contact careers (Paul, Weiss, Quinn Emanuel)
  html.py               Standard-library HTML tree parser
  http.py               Sequential, bounded official-host HTTPS client
tests/
  test_scanner.py       Offline regression tests, fixtures, and validation tests
  test_classify.py      Fee-earning vs internal role classifier unit tests
reports/
  dashboard.html        Interactive local browser dashboard with search, London & New filters
  CHECKLIST.md          Step-by-step browser checklist for Jamie and Ryan
  RESULTS.md            Complete snapshot of all observed vacancies (London first)
  whatsapp-summary.txt  Formatted executive summary ready to copy into WhatsApp
  all-latest.csv        Complete table of all observed vacancies
  all-london.csv        London-only qualified lawyer vacancies
  new-london.csv        Newly discovered London roles since baseline
```

See `reports/RESULTS.md` for the latest 20-firm scan findings and `reports/CHECKLIST.md` for manual browser verification. All 20 firms are configured and active in `registry.py\.
