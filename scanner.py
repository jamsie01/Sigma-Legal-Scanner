#!/usr/bin/env python3
"""Sigma Legal — official vacancy scanner, change tracking and local reports."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
import sys
import time

from models import ScanResult, utc_now
from registry import FIRMS, make_collector, source_url
from reporting import write_csv, write_json, write_reports, write_text
from storage import Store
from validation import validate_result

ROOT = Path(__file__).resolve().parent


def collect_firm(key, decisions, quiet=False):
    config = FIRMS[key]
    start = time.monotonic()
    progress = (lambda _: None) if quiet else (lambda msg: print(f'[{key}] {msg}', file=sys.stderr, flush=True))
    try:
        collector = make_collector(config, progress)
        result = collector.collect()
        validate_result(result, config, collector, decisions)
    except Exception as exc:
        # A changed response at one firm must not stop the other firms.
        result = ScanResult(config.firm, source_url(config), finished_at=utc_now(),
                            errors=[f'{type(exc).__name__}: {exc}'])
    return result, round(time.monotonic() - start, 2)


def current_scans(store):
    scans = {s['firm']: s for s in store.latest_scans()}
    decisions = {(d['firm'], d['job_id']) for d in store.decisions()}
    from collectors.classify import is_sigma_vacancy
    out = []
    for config in FIRMS.values():
        scan = scans.get(config.firm)
        if scan is None:
            scan = dict(id=None, firm=config.firm, source=source_url(config), status='BLOCKED',
                        finished_at='Never checked', vacancies=[], errors=['No scan recorded'], review=[], coverage={})
        else:
            scan['source'] = scan.get('source') or source_url(config)
            # Pre-upgrade observations did not pass the publication gates.
            if scan.get('baseline') is None:
                scan['vacancies'] = []
                scan['status'] = 'LIMITED'
                scan['errors'].append('Pre-upgrade scan: rescan to verify links and coverage')
            scan['vacancies'] = [r for r in scan['vacancies']
                                 if (r['firm'], r['job_id']) not in decisions and is_sigma_vacancy(r['title'])]
        out.append(scan)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['scan-all', 'scan', 'history', 'report', 'exclude', 'restore', 'decisions'])
    parser.add_argument('firm', nargs='?', choices=list(FIRMS))
    parser.add_argument('--job-id')
    parser.add_argument('--reason')
    parser.add_argument('--db', type=Path, default=ROOT / 'data' / 'vacancies.sqlite3')
    parser.add_argument('--reports', type=Path, default=ROOT / 'reports')
    parser.add_argument('--location', choices=['all', 'london'], default='london')
    parser.add_argument('--new', action='store_true', help='Show only newly discovered roles in the console; all observations are saved')
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=1,
                        help='Independent firms to scan at once (default 1; max 4)')
    args = parser.parse_args(argv)
    if (args.command in ('scan', 'exclude', 'restore')) != bool(args.firm):
        parser.error('A firm is required only for scan, exclude and restore')
    if args.command in ('exclude', 'restore') and not args.job_id:
        parser.error('--job-id is required')
    if args.command == 'exclude' and not (args.reason or '').strip():
        parser.error('exclude requires --reason explaining the recruiter decision')
    store = Store(args.db)
    try:
        if args.command == 'history':
            for row in store.history():
                print(f"#{row['id']} {row['started_at']} {row['firm']} {row['status']} | {row['qualified']} observed | {row['new']} first-seen IDs")
            return 0
        if args.command == 'decisions':
            for row in store.decisions():
                print(f"{row['firm']} / {row['job_id']}: {row['reason']}")
            return 0
        if args.command == 'exclude':
            store.exclude(FIRMS[args.firm].firm, args.job_id, args.reason.strip())
        elif args.command == 'restore':
            store.restore(FIRMS[args.firm].firm, args.job_id)
        exit_code = 0
        refreshed = []
        if args.command in ('scan', 'scan-all'):
            args.reports.mkdir(parents=True, exist_ok=True)
            decisions = {(d['firm'], d['job_id']): d['reason'] for d in store.decisions()}
            keys = [args.firm] if args.command == 'scan' else list(FIRMS)
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                tasks = {pool.submit(collect_firm, key, decisions, args.quiet): key for key in keys}
                for task in as_completed(tasks):
                    key = tasks[task]
                    result, duration = task.result()
                    scan_id, records = store.save(result)
                    # save() preserves identity-level first-seen compatibility;
                    # reports distinguish the initial baseline explicitly.
                    for record in records:
                        record['is_new'] = record['change'] == 'NEW'
                    payload = {**result.to_dict(), 'scan_id': scan_id, 'duration_seconds': duration,
                               'new_count': sum(r['is_new'] for r in records), 'vacancies': records}
                    write_json(args.reports / f'{key}-latest.json', payload)
                    write_json(args.reports / f'{key}-scan-{scan_id:04d}.json', payload)
                    write_csv(args.reports / f'{key}-latest.csv', records)
                    write_csv(args.reports / f'{key}-london.csv', [r for r in records if r['london']])
                    refreshed.append(result.firm)
                    print(f"{result.firm}: {result.status} | {len(records)} observed ({sum(r['london'] for r in records)} London) | {payload['new_count']} NEW | {duration}s", flush=True)
                    for row in records:
                        if args.location == 'london' and not row['london'] or args.new and not row['is_new']:
                            continue
                        print(f"  {row['change']} {row['title']} | {row['location']}\n    {row['url']}")
                    for error in result.errors:
                        print(f'  {error}', file=sys.stderr)
                    if result.status in ('PARTIAL', 'BLOCKED'):
                        exit_code = 2
                    elif result.status == 'LIMITED':
                        exit_code = max(exit_code, 1)
        scans = current_scans(store)
        write_reports(args.reports, scans, refreshed)
        if args.reports.resolve() == (ROOT / 'reports').resolve():
            write_text(ROOT / 'RESULTS.md', (args.reports / 'RESULTS.md').read_text())
        print(f"Dashboard: {args.reports / 'dashboard.html'}\nNew London roles: {args.reports / 'new-london.csv'}\nBrowser checklist: {args.reports / 'CHECKLIST.md'}")
        return exit_code
    finally:
        store.close()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nScan interrupted. Completed firm scans remain saved.', file=sys.stderr)
        raise SystemExit(130)
