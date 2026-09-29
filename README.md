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
- `reports/whatsapp-summary.txt`: executive summary of London qualified roles ready to share on WhatsApp.
- `reports/all-london.csv`: consolidated qualified London roles across all firms.
- `reports/all-latest.csv`: all qualified roles across all firms.
- `reports/<firm>-latest.csv`: qualified-lawyer results for each firm.
- `reports/<firm>-london.csv`: qualified-lawyer vacancies explicitly listing London.
- `reports/<firm>-latest.json`: latest scan, coverage, errors, exclusions, review cases and full results.
- `RESULTS.md`: readable snapshot of all roles, with London and stated PQE first.
- `VALIDATION.md`: observed live results, repeat-scan proof and test results from initial setup.

## What NEW means

The permanent identity is `(firm, job_id)`. The first time an ID is successfully collected it is NEW. The first populated scan creates the baseline; its NEW entries are **not claims that the jobs were posted today**. Later scans only report unseen IDs as NEW. Changing a title, URL slug or location does not reset the identity. If an old ID disappears and returns, it is still previously seen.

## Status and exit codes

| Status | Meaning | Exit code |
| --- | --- | --- |
| SUCCESS | Complete board and London cross-check, all relevant adverts verified, no unresolved role classification | 0 |
| LIMITED | Retrieval completed, but a role needs human qualification review | 1 |
| PARTIAL | Useful listing data found, but a page, advert or London cross-check failed | 2 |
| BLOCKED | No usable listing data; network, access or unexpected page structure | 2 |

A completely checked board with **zero London vacancies can be SUCCESS**. An empty or blocked HTML page is never assumed to mean zero vacancies.

## Source layout

```text
scanner.py              CLI, firm registry, CSV/JSON reports
models.py               Vacancy and scan-result data structures
storage.py              SQLite transactions, identities and history
collectors/             Per-firm and ATS-specific vacancy collectors
tests/                  Parsing, coverage, failure and persistence tests
firms/                  20 firm handover packages, evidence, and sample data
reports/                Generated CSV/JSON scan output and WhatsApp summary
data/                   SQLite database
```

See `RESULTS.md` for the latest 20-firm scan findings and `reports/whatsapp-summary.txt` for the London executive summary. All 20 firms are fully registered and active in `scanner.py`.
