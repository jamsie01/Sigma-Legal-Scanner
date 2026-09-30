"""Reports use latest observations per firm; historical identities never imply live jobs."""
import csv
import html
import json
import os
import re
from pathlib import Path
from models import utc_now

FIELDS = ['firm', 'change', 'title', 'location', 'practice_area', 'practice_area_source',
          'pqe', 'url', 'job_id', 'reference', 'checked_at', 'first_seen', 'last_seen',
          'london', 'is_new', 'changed_fields']


def clean_pqe_snippet(text):
    if not text:
        return ''
    text = html.unescape(text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = ' '.join(text.split())
    m = re.search(r'\b([0-2]?\d\s*[-–to]+\s*[0-2]?\d\s*(?:years?\'?|yrs?)?\s*(?:PQE|post[\s-]qualifi\w*)?)', text, re.I)
    if m and any(k in m.group(0).lower() for k in ['pqe', 'year', 'yr', 'post']):
        return m.group(1).strip()
    m2 = re.search(r'\b([0-2]?\d\+?\s*(?:years?\'?|yrs?)?\s*(?:PQE|post[\s-]qualifi\w*))', text, re.I)
    if m2:
        return m2.group(1).strip()
    m3 = re.search(r'\b(NQ|newly\s+qualified)\b(?:\s*[-–to]+\s*\d\s*years?)?', text, re.I)
    if m3:
        return m3.group(0).strip()
    return ''


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    os.replace(temporary, path)


def write_json(path, value):
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def write_csv(path, records):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, FIELDS, extrasaction='ignore')
        writer.writeheader()
        for record in records:
            row = {}
            for key in FIELDS:
                value = record.get(key, '')
                if isinstance(value, list):
                    value = ', '.join(value)
                if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
                    value = "'" + value
                row[key] = value
            writer.writerow(row)
    os.replace(temporary, path)


def public_status(scan):
    return {'SUCCESS': 'COMPLETE', 'LIMITED': 'PARTIAL'}.get(scan['status'], scan['status'])


def md(value):
    return str(value or '—').replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')


def records_for(scans):
    return sorted([r for s in scans for r in s['vacancies']],
                  key=lambda r: (not r['london'], r.get('change') != 'NEW', r['firm'], r['title']))


def write_reports(directory, scans, refreshed=()):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rows = records_for(scans)
    london = [r for r in rows if r['london']]
    new = [r for r in rows if r.get('change') == 'NEW']
    generated = utc_now()
    for name, items in [('all-latest', rows), ('all-london', london), ('new-roles', new),
                        ('new-london', [r for r in new if r['london']])]:
        write_csv(directory / (name + '.csv'), items)
    write_json(directory / 'summary.json', {'generated_at': generated, 'refreshed_firms': list(refreshed),
                                           'scans': scans})
    lines = ['# Sigma Legal — latest observations\n', f'Generated: {generated}\n',
             'NEW means first discovered after the initial baseline, not posted today. '
             'Each firm has its own check time. Missing roles are not assumed closed.\n',
             '| Firm | Check | London observed | NEW London | Checked at |\n|---|---|---:|---:|---|\n']
    checklist = ['# Browser checks for Jamie / Ryan\n',
                 'Counts below are observed roles. PARTIAL/BLOCKED never means no vacancies. '
                 'Open the board, choose London (including multiple-office roles), and compare the advert links in RESULTS.md.\n']
    for scan in scans:
        jobs = scan['vacancies']
        local = [r for r in jobs if r['london']]
        fresh = sum(r.get('change') == 'NEW' for r in local)
        status = public_status(scan)
        lines.append(f"| {md(scan['firm'])} | {status} | {len(local)} | {fresh} | {md(scan['finished_at'])} |\n")
        issues = scan.get('errors', []) + [r.get('reason', '') for r in scan.get('review', [])]
        checklist += [f"\n## {scan['firm']} — {status}\n", f"- Board: {scan.get('source') or 'See registry.py'}\n",
                      f"- London observed: {len(local)}; NEW: {fresh}. Checked: {scan['finished_at']}\n",
                      '- Compare office, practice, PQE and whether each advert still accepts applications.\n']
        checklist += [f'- Investigate: {md(issue)}\n' for issue in issues]

    london_by_firm = {}
    zero_firms = []
    for scan in scans:
        local = [r for r in scan['vacancies'] if r.get('london')]
        if local:
            london_by_firm[scan['firm']] = (scan, local)
        else:
            zero_firms.append(scan['firm'])

    total_london = sum(len(loc) for _, loc in london_by_firm.values())
    total_new = sum(r.get('change') == 'NEW' for _, loc in london_by_firm.values() for r in loc)
    new_badge = f" (🔥 {total_new} NEW)" if total_new else ""

    whatsapp = [
        '*Sigma Legal — London Vacancies*',
        f'📊 *{total_london} qualified London roles*{new_badge} across {len(london_by_firm)} firms ({len(zero_firms)} firms checked with 0 roles)',
        f'📅 _Updated: {generated}_\n',
    ]

    for firm, (s, jobs) in sorted(london_by_firm.items()):
        fresh = sum(r.get('change') == 'NEW' for r in jobs)
        fresh_tag = f" — {fresh} NEW" if fresh else ""
        whatsapp.append(f"*{firm}* ({len(jobs)} roles{fresh_tag})")
        for r in sorted(jobs, key=lambda x: (x.get('change') != 'NEW', x['title'])):
            pqe = clean_pqe_snippet(r.get('pqe'))
            pqe_str = f" ({pqe})" if pqe and pqe.lower() not in r['title'].lower() else ""
            flag = " 🆕" if r.get('change') == 'NEW' else ""
            whatsapp.append(f"• {r['title']}{pqe_str}{flag}")
            whatsapp.append(f"  {r['url']}")
        whatsapp.append("")

    if zero_firms:
        whatsapp.append("━━━━━━━━━━━━━━━━━━━━")
        whatsapp.append(f"_Firms checked with 0 London roles ({len(zero_firms)}):_")
        whatsapp.append(", ".join(sorted(zero_firms)) + "\n")

    for scan in scans:
        lines.append(f"\n## {scan['firm']} — {public_status(scan)}\n")
        lines.append(f"Checked: {scan['finished_at']}. Source: {scan.get('source') or 'not recorded'}\n")
        for issue in scan.get('errors', []):
            lines.append(f'- {md(issue)}\n')
        for group, label in [(True, 'London'), (False, 'Other offices / location unresolved')]:
            jobs = [r for r in scan['vacancies'] if bool(r['london']) == group]
            if not jobs:
                continue
            lines += [f'\n### {label}\n', '| Change | Role | Office | Practice | PQE | Advert |\n|---|---|---|---|---|---|\n']
            for r in jobs:
                lines.append(f"| {md(r.get('change'))} | {md(r['title'])} | {md(r['location'])} | {md(r.get('practice_area'))} | {md(r.get('pqe'))} | [Advert](<{r['url']}>) |\n")
    write_text(directory / 'RESULTS.md', ''.join(lines))
    write_text(directory / 'CHECKLIST.md', ''.join(checklist))
    write_text(directory / 'whatsapp-summary.txt', '\n'.join(whatsapp).strip() + '\n')
    write_text(directory / 'ryan-london-digest.txt', '\n'.join(whatsapp).strip() + '\n')
    write_dashboard(directory / 'dashboard.html', scans, rows, generated)


def write_dashboard(path, scans, rows, generated):
    esc = lambda x: html.escape(str(x or '—'), quote=True)
    cards = ''.join(f'<article><strong>{esc(s["firm"])}</strong><span class="{public_status(s).lower()}">{public_status(s)}</span><small>{esc(s["finished_at"])}</small><small>{esc("; ".join(s.get("errors", []))) if s.get("errors") else ""}</small></article>' for s in scans)
    table = []
    for r in rows:
        table.append(f'<tr data-london="{int(bool(r["london"]))}" data-new="{int(r.get("change") == "NEW")}"><td><b>{esc(r.get("change"))}</b></td><td>{esc(r["firm"])}</td><td><a href="{esc(r["url"])}" target="_blank" rel="noopener noreferrer">{esc(r["title"])}</a></td><td>{esc(r["location"])}</td><td>{esc(r.get("practice_area"))}</td><td>{esc(r.get("pqe"))}</td><td>{esc(r.get("checked_at"))}</td></tr>')
    write_text(path, '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sigma Legal — vacancies</title>
<style>:root{font:16px system-ui;color:#18263a;background:#f4f6fa}body{max-width:1500px;margin:auto;padding:28px}h1{margin-bottom:8px}p,small{color:#526279}section{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px;margin:24px 0}article{background:white;padding:14px;border-radius:10px;border:1px solid #d9e1eb}article span,small{display:block;margin-top:6px}.complete{color:#087443}.partial{color:#975d00}.blocked{color:#bd2525}input{padding:10px;border:1px solid #b3c1d3;border-radius:6px}label{margin-right:16px}table{border-collapse:collapse;width:100%;background:white}th,td{text-align:left;padding:12px;border-bottom:1px solid #dce3ed;vertical-align:top}th{background:#182d4d;color:white}a{color:#1456a0}.scroll{overflow:auto}td:nth-child(6){max-width:420px;font-size:14px}button{padding:10px}#count{font-weight:600}</style>
<h1>Sigma Legal</h1><p>Latest observed vacancies · Generated ''' + esc(generated) + '''</p><p>NEW = first discovered after baseline. Check times differ by firm. PARTIAL and BLOCKED mean coverage is incomplete.</p>
<label>Search <input id="search" placeholder="Firm, practice, PQE or title"></label><label><input type="checkbox" id="london" checked> London only</label><label><input type="checkbox" id="fresh"> New only</label><p id="count" aria-live="polite"></p>
<div class="scroll"><table><thead><tr><th>Change</th><th>Firm</th><th>Role / advert</th><th>Office</th><th>Practice</th><th>PQE as stated</th><th>Checked</th></tr></thead><tbody>''' + ''.join(table) + '''</tbody></table></div><h2>Firm coverage</h2><section>''' + cards + '''</section>
<script>const rows=[...document.querySelectorAll('tbody tr')];const search=document.getElementById('search'),london=document.getElementById('london'),fresh=document.getElementById('fresh');function filter(){let n=0;for(const r of rows){r.hidden=!(r.textContent.toLowerCase().includes(search.value.toLowerCase())&&(!london.checked||r.dataset.london==='1')&&(!fresh.checked||r.dataset.new==='1'));if(!r.hidden)n++}document.getElementById('count').textContent=n+' roles shown'}for(const el of [search,london,fresh])el.addEventListener('input',filter);filter();</script></html>''')
