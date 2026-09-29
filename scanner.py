#!/usr/bin/env python3
"""Sigma Legal Search — lightweight local official vacancy scanner."""
import argparse
import csv
import json
import os
from pathlib import Path
import re
from urllib.parse import urlparse
import sys
import time

from collectors.harbour import HarbourCollector, HarbourConfig
from collectors.workday import WorkdayCollector, WorkdayConfig
from collectors.eploy import EployCollector, EployConfig
from collectors.hfw import HfwCollector, HfwConfig
from collectors.withers import WithersCollector, WithersConfig
from collectors.fladgate import FladgateCollector, FladgateConfig
from collectors.stewarts import StewartsCollector, StewartsConfig
from collectors.hausfeld import HausfeldCollector, HausfeldConfig
from collectors.contact_only import ContactOnlyCollector, ContactOnlyConfig
from collectors.allhires import AllHiresCollector, AllHiresConfig
from collectors.icims import IcimsCollector, IcimsConfig
from collectors.cvmail import CvmailCollector, CvmailConfig
from collectors.taylorwessing import TaylorWessingCollector, TaylorWessingConfig
from collectors.mofo import MofoCollector, MofoConfig
from collectors.http import HttpClient
from storage import Store

ROOT = Path(__file__).resolve().parent
# 20 Official Law Firm Careers Boards & ATS Configurations
FIRMS = {
    'tlt': HarbourConfig('TLT', 'https://apply.tlt.com/vacancies/', 'field_4811'),
    'squire-patton-boggs': CvmailConfig('Squire Patton Boggs', 'https://fsr.cvmailuk.com/spb/main.cfm?srxksl=1'),
    'taylor-wessing': TaylorWessingConfig('Taylor Wessing', 'https://careers.winstontaylor-emea.com/Careeropportunities/go/Career-opportunities/9053755/'),
    'fieldfisher': EployConfig('Fieldfisher', 'https://fieldfisher.current-vacancies.com/Careers/Fieldfisher%20Vacancy%20Search%20Page-2074'),
    'hfw': HfwConfig('HFW', 'https://www.hfw.com/careers/vacancies/'),
    'lewis-silkin': AllHiresConfig('Lewis Silkin', 'https://lewissilkin.allhires.com/'),
    'withers': WithersConfig('Withers', 'https://www.witherscareers.com/'),
    'fladgate': FladgateConfig('Fladgate', 'https://www.fladgate.com/careers'),
    'stewarts': StewartsConfig('Stewarts', 'https://www.stewartslaw.com/careers/vacancies/'),
    'hausfeld': HausfeldConfig('Hausfeld', 'https://www.hausfeld.com/en-gb/join-us/open-positions'),
    'kirkland-ellis': CvmailConfig('Kirkland & Ellis', 'https://fsr.cvmailuk.com/kirkland/main.cfm?page=jobBoard&fo=1&groupType_8=3011&groupType_4=&groupType_3=&filter'),
    'latham-watkins': IcimsConfig('Latham & Watkins', 'https://ukcareers-lw.icims.com/jobs/search?ss=1&in_iframe=1'),
    'simpson-thacher': WorkdayConfig('Simpson Thacher', 'https://stblaw.wd1.myworkdayjobs.com/wday/cxs/stblaw/careers'),
    'paul-weiss': ContactOnlyConfig('Paul, Weiss', 'https://www.paulweiss.com/careers/laterals-judicial-clerks', 'LegalHiringUK@paulweiss.com'),
    'milbank': AllHiresConfig('Milbank', 'https://milbank.allhires.com/'),
    'davis-polk': WorkdayConfig('Davis Polk', 'https://davispolk.wd5.myworkdayjobs.com/wday/cxs/davispolk/business-professionals-services-usa'),
    'cooley': WorkdayConfig('Cooley UK', 'https://cooley.wd1.myworkdayjobs.com/wday/cxs/cooley/Cooley_UK_LLP'),
    'morrison-foerster': MofoConfig('Morrison Foerster', 'https://mofo.career.page/api/jobs'),
    'paul-hastings': WorkdayConfig('Paul Hastings', 'https://paulhastings.wd1.myworkdayjobs.com/wday/cxs/paulhastings/PH-Staff'),
    'quinn-emanuel': ContactOnlyConfig('Quinn Emanuel', 'https://www.quinnemanuel.com/careers/recruiting/recruiting-contacts/', 'londonrecruitment@quinnemanuel.com')
}


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def write_csv(path, records):
    fields = ['firm', 'title', 'location', 'job_id', 'reference', 'url', 'practice_area',
              'practice_area_source', 'pqe', 'checked_at', 'london', 'is_new', 'first_seen']
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fields, extrasaction='ignore')
        writer.writeheader()
        for record in records:
            # Preserve source text in JSON/SQLite; protect spreadsheet cells.
            writer.writerow({key: ("'" + value if isinstance(value, str)
                                   and value.startswith(('=', '+', '-', '@')) else value)
                             for key, value in record.items()})
    os.replace(temporary, path)


def clean_pqe_snippet(pqe_text):
    if not pqe_text:
        return '—'
    m = re.search(r'\b([0-2]?\d\s*[-–to]+\s*[0-2]?\d\s*(?:years?\'?|yrs?)?\s*(?:PQE|post[\s-]qualifi\w*)?)', pqe_text, re.I)
    if m and any(k in m.group(0).lower() for k in ['pqe', 'year', 'yr', 'post']):
        return m.group(1).strip()
    m2 = re.search(r'\b([0-2]?\d\+?\s*(?:years?\'?|yrs?)?\s*(?:PQE|post[\s-]qualifi\w*))', pqe_text, re.I)
    if m2:
        return m2.group(1).strip()
    if len(pqe_text) < 50 and any(k in pqe_text.lower() for k in ['pqe', 'year', 'yr']):
        return pqe_text.strip()
    return 'See advert'


def write_results_md(path, all_records, scanned_at):
    """Regenerate RESULTS.md with a clean summary after every scan."""
    from datetime import datetime, timezone
    date_str = datetime.now(timezone.utc).strftime('%d %B %Y %H:%M UTC')

    lines = [f'# Sigma Legal — Vacancy Results\n',
             f'*Last updated: {date_str}*\n',
             f'*Run `python3 scanner.py scan-all` to refresh.*\n']

    firms_seen = {}
    for row in all_records:
        firms_seen.setdefault(row['firm'], {'london': [], 'other': []})
        if row['london']:
            firms_seen[row['firm']]['london'].append(row)
        else:
            firms_seen[row['firm']]['other'].append(row)

    for firm, groups in firms_seen.items():
        london = groups['london']
        other = groups['other']
        lines.append(f'\n## {firm}\n')
        total = len(london) + len(other)
        lines.append(f'{total} qualified-lawyer {"vacancy" if total == 1 else "vacancies"} '
                     f'found — **{len(london)} London**.\n')

        if london:
            lines.append('\n### 🏙️ London roles\n')
            lines.append('| Role | PQE | Link |\n|---|---|---|\n')
            for row in london:
                pqe = clean_pqe_snippet(row.get('pqe'))
                lines.append(f"| {row['title']} | {pqe} | [Apply]({row['url']}) |\n")

        if other:
            lines.append('\n### Other UK roles\n')
            lines.append('| Role | Office | PQE | Link |\n|---|---|---|---|\n')
            for row in other:
                pqe = clean_pqe_snippet(row.get('pqe'))
                lines.append(f"| {row['title']} | {row['location']} | {pqe} | [Apply]({row['url']}) |\n")

    if not firms_seen:
        lines.append('\nNo qualified-lawyer vacancies found in this scan.\n')

    lines.append('\n---\n')
    lines.append('*Source: official firm careers boards only. '
                 'Not LinkedIn, Indeed or any third-party site.*\n')

    temporary = path.with_suffix('.tmp')
    temporary.write_text(''.join(lines), encoding='utf-8')
    os.replace(temporary, path)


def write_whatsapp_summary(path, all_records, all_firms=None):
    """Write a concise, copy-paste ready summary for WhatsApp."""
    from datetime import datetime, timezone
    date_str = datetime.now(timezone.utc).strftime('%d %b %Y')
    london_roles = [r for r in all_records if r['london']]
    
    by_firm = {}
    for r in london_roles:
        by_firm.setdefault(r['firm'], []).append(r)
        
    total_scanned = len(all_firms) if all_firms else 20
    firms_with_roles = len(by_firm)
    firms_zero = total_scanned - firms_with_roles

    lines = [
        f"*Sigma Legal Search — London Vacancies Report*\n",
        f"📅 _Checked: {date_str}_\n",
        f"📊 _Summary: {total_scanned} official firm boards scanned. Found {len(london_roles)} qualified London roles across {firms_with_roles} firms ({firms_zero} firms verified with 0 London roles today)._\n\n",
        f"━━━━━━━━━━━━━━━━━━━\n\n"
    ]
    
    for firm, jobs in sorted(by_firm.items()):
        lines.append(f"*{firm}* ({len(jobs)} {'role' if len(jobs) == 1 else 'roles'})\n")
        for j in jobs:
            pqe = clean_pqe_snippet(j.get('pqe'))
            if not pqe or pqe in ('—', 'See advert') or pqe.lower() in j['title'].lower() or 'pqe' in j['title'].lower():
                pqe_str = ""
            else:
                pqe_str = f" ({pqe})"
            lines.append(f"• {j['title']}{pqe_str}\n  {j['url']}\n")
        lines.append("\n")

    if all_firms:
        zero_firms = sorted([f for f in all_firms if f not in by_firm])
        if zero_firms:
            lines.append("━━━━━━━━━━━━━━━━━━━\n")
            lines.append(f"_Firms checked with 0 London roles today ({len(zero_firms)}):_\n")
            lines.append(', '.join(zero_firms) + '\n\n')

    temporary = path.with_suffix('.tmp')
    temporary.write_text(''.join(lines).strip() + '\n', encoding='utf-8')
    os.replace(temporary, path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['scan-all', 'scan', 'history'])
    parser.add_argument('firm', nargs='?', choices=list(FIRMS))
    parser.add_argument('--db', type=Path, default=ROOT/'data'/'vacancies.sqlite3')
    parser.add_argument('--reports', type=Path, default=ROOT/'reports')
    parser.add_argument('--location', choices=['all', 'london'], default='london',
                        help='Console display only: every scan checks and stores all offices')
    parser.add_argument('--quiet', action='store_true', help='Hide individual HTTP progress')
    args = parser.parse_args(argv)
    if args.command == 'scan' and args.firm is None:
        parser.error('scan requires a firm, for example: scan tlt')
    if args.command != 'scan' and args.firm is not None:
        parser.error('firm is only accepted with scan')
    store = Store(args.db)
    try:
        if args.command == 'history':
            for row in store.history():
                print(f"#{row['id']} {row['started_at']} {row['firm']} {row['status']} | "
                      f"{row['qualified']} qualified | {row['new']} NEW")
            return 0
        exit_code = 0
        all_records_for_md = []
        args.reports.mkdir(parents=True, exist_ok=True)
        for key in ([args.firm] if args.command == 'scan' else FIRMS):
            config = FIRMS[key]
            start = time.monotonic()
            progress = (lambda _: None) if args.quiet else (lambda msg: print(msg, file=sys.stderr, flush=True))
            if isinstance(config, HarbourConfig):
                client = HttpClient(urlparse(config.board_url).hostname)
                result = HarbourCollector(config, client, progress).collect()
            elif isinstance(config, WorkdayConfig):
                result = WorkdayCollector(config, progress).collect()
            elif isinstance(config, ContactOnlyConfig):
                result = ContactOnlyCollector(config, progress).collect()
            elif isinstance(config, AllHiresConfig):
                result = AllHiresCollector(config, progress).collect()
            elif isinstance(config, IcimsConfig):
                client = HttpClient(urlparse(config.board_url).hostname)
                result = IcimsCollector(config, client, progress).collect()
            elif isinstance(config, EployConfig):
                client = HttpClient(urlparse(config.board_url).hostname)
                result = EployCollector(config, client, progress).collect()
            elif isinstance(config, HfwConfig):
                client = HttpClient(urlparse(config.board_url).hostname)
                result = HfwCollector(config, client, progress).collect()
            elif isinstance(config, WithersConfig):
                client = HttpClient(urlparse(config.board_url).hostname)
                result = WithersCollector(config, client, progress).collect()
            elif isinstance(config, FladgateConfig):
                client = HttpClient(urlparse(config.board_url).hostname)
                result = FladgateCollector(config, client, progress).collect()
            elif isinstance(config, StewartsConfig):
                client = HttpClient(urlparse(config.board_url).hostname)
                result = StewartsCollector(config, client, progress).collect()
            elif isinstance(config, HausfeldConfig):
                client = HttpClient(urlparse(config.board_url).hostname)
                result = HausfeldCollector(config, client, progress).collect()
            elif isinstance(config, CvmailConfig):
                client = HttpClient(urlparse(config.board_url).hostname)
                result = CvmailCollector(config, client, progress).collect()
            elif isinstance(config, TaylorWessingConfig):
                client = HttpClient(urlparse(config.board_url).hostname)
                result = TaylorWessingCollector(config, client, progress).collect()
            elif isinstance(config, MofoConfig):
                result = MofoCollector(config, progress).collect()
            else:
                raise ValueError(f"Unknown config type for {key}")
            scan_id, records = store.save(result)
            duration = round(time.monotonic()-start, 2)
            payload = {**result.to_dict(), 'scan_id': scan_id, 'duration_seconds': duration,
                       'new_count': sum(row['is_new'] for row in records), 'vacancies': records}
            write_json(args.reports/f'{key}-latest.json', payload)
            write_csv(args.reports/f'{key}-latest.csv', records)
            write_csv(args.reports/f'{key}-london.csv', [row for row in records if row['london']])
            all_records_for_md.extend(records)
            london = [row for row in records if row['london']]
            print(f"{config.firm}: {result.status} | scan #{scan_id} | {duration}s | "
                  f"{len(records)} qualified ({len(london)} London) | {payload['new_count']} NEW")
            print(f"Coverage: {result.coverage.get('board_pages', 0)} board pages; "
                  f"London filter verified: {result.coverage.get('london_filter_complete', False)}")
            for row in records if args.location == 'all' else london:
                print(f"  {'NEW' if row['is_new'] else 'SEEN'} {row['reference']} | {row['title']} | {row['location']}")
                print(f"       {row['url']}")
            for row in result.review:
                print(f"  REVIEW {row['job_id']}: {row['title']} ({row['location']}) — {row['reason']}")
            for error in result.errors:
                print(f'  ERROR: {error}', file=sys.stderr)
            print(f"SQLite: {args.db}\nReport: {args.reports / f'{key}-latest.json'}")
            if result.status in ('PARTIAL', 'BLOCKED'):
                exit_code = 2
            elif result.status == 'LIMITED' and exit_code == 0:
                exit_code = 1
        all_vacancies = store.all_vacancies()
        write_results_md(ROOT / 'RESULTS.md', all_vacancies, time.time())
        write_csv(args.reports / 'all-latest.csv', all_vacancies)
        write_csv(args.reports / 'all-london.csv', [r for r in all_vacancies if r['london']])
        write_whatsapp_summary(args.reports / 'whatsapp-summary.txt', all_vacancies, [cfg.firm for cfg in FIRMS.values()])
        print(f"Results: {ROOT / 'RESULTS.md'}")
        print(f"Master London CSV: {args.reports / 'all-london.csv'}")
        print(f"WhatsApp text: {args.reports / 'whatsapp-summary.txt'}")
        return exit_code
    finally:
        store.close()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nScan interrupted; previously saved vacancies are unchanged.', file=sys.stderr)
        raise SystemExit(130)
