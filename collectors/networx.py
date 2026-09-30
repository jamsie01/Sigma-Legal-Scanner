"""Networx public search API, discovered from the official board's JavaScript."""
import json
import re
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse, urljoin
from urllib.request import Request, HTTPCookieProcessor, build_opener
from collectors.http import OfficialRedirects, FetchError
from collectors.html import Tree
from collectors.classify import is_sigma_vacancy
from collectors.harbour import extract_pqe
from models import ScanResult, Vacancy, utc_now


@dataclass(frozen=True)
class NetworxConfig:
    firm: str
    board_url: str
    max_pages: int = 100


class NetworxCollector:
    def __init__(self, config, client, progress=lambda _: None):
        self.config, self.client, self.progress = config, client, progress
        host = urlparse(config.board_url).hostname
        self.origin = 'https://' + host
        self.opener = build_opener(HTTPCookieProcessor(), OfficialRedirects(host))
        self.requests = 0

    def request(self, url, data=None, token=None):
        headers = {'User-Agent': 'SigmaLegalSearch/0.1 (local vacancy checker)',
                   'Referer': self.config.board_url, 'Origin': self.origin,
                   'X-Requested-With': 'XMLHttpRequest'}
        if token:
            headers['__RequestVerificationToken'] = token
        self.requests += 1
        with self.opener.open(Request(url, data=data, headers=headers), timeout=20) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise FetchError('Networx response exceeds 2 MB')
            return raw.decode('utf-8-sig')

    def collect(self):
        result = ScanResult(self.config.firm, self.config.board_url)
        jobs = []
        try:
            board = self.request(self.config.board_url)
            root = Tree(board).root
            token = next(n.attrs['value'] for n in root.find('input')
                         if n.attrs.get('name') == '__RequestVerificationToken')
            cid = re.search(r'var cid\s*=\s*(\d+)', board)
            init = re.search(r'InitialiseVacancySearch\(\s*true,\s*(\d+),\s*(?:true|false),\s*RootURL,\s*cid,\s*(-?\d+)', board)
            if not cid or not init:
                raise FetchError('Networx search configuration missing')
            payload = {'ClientID': int(cid.group(1)), 'OnboardingPageID': int(init.group(2)),
                       'DynamicFields': [], 'SearchResultFields': ['ApplyLink', 'VacancyTitle', 'Location', 'Salary', 'ExpiryDate'],
                       'CurrentPage': 1, 'PageSearchResults': True, 'SearchResultPageSize': int(init.group(1)),
                       'keywords': '', 'Locations': ['0']}
            def api(endpoint):
                form = urlencode({'__RequestVerificationToken': token, 'data': json.dumps(payload), 'hdnNewWorld': 'True'}).encode()
                value = json.loads(self.request(self.origin + '/Careers/' + endpoint + '?cid=' + cid.group(1), form, token))
                if value.get('OK') is not True:
                    raise FetchError('Networx API did not confirm a successful search')
                return value
            total = api('SearchVacanciesCount').get('Count')
            if not isinstance(total, int) or total < 0:
                raise FetchError('Networx result count missing')
            seen = set()
            while len(jobs) < total:
                if payload['CurrentPage'] > self.config.max_pages:
                    raise FetchError('Networx pagination limit reached')
                batch = api('SearchVacancies').get('Data')
                if not isinstance(batch, list) or not batch:
                    raise FetchError('Networx pagination ended before reported total')
                ids = [str(j.get('VacancyID', '')) for j in batch]
                if any(not i for i in ids) or len(ids) != len(set(ids)) or seen & set(ids):
                    raise FetchError('Networx missing or repeated vacancy IDs')
                seen.update(ids)
                jobs.extend(batch)
                payload['CurrentPage'] += 1
            if len(jobs) != total or api('SearchVacanciesCount')['Count'] != total:
                raise FetchError('Networx board count changed during scan')
            result.coverage['board_complete'] = True
        except Exception as exc:
            result.errors.append(f'Networx search: {type(exc).__name__}: {exc}')
        for job in jobs:
            title, location = job.get('VacancyTitle', ''), job.get('Location', '')
            summary = dict(job_id=str(job.get('VacancyID', '')), title=title, location=location,
                           url=job.get('ApplyLink', ''))
            if not is_sigma_vacancy(title):
                result.excluded.append({**summary, 'reason': 'Non-fee-earning or non-qualified title'})
                continue
            try:
                advert = self.client.get(summary['url'])
                if title.casefold() not in Tree(advert).root.text().casefold():
                    raise FetchError('Advert title does not match API listing')
                description = job.get('JobDescription', '')
                # Plain API paragraphs become HTML paragraphs for the source-preserving extractor.
                from html import escape
                pqe = extract_pqe(''.join('<p>' + escape(p) + '</p>' for p in description.splitlines() if p.strip()))
                parts = title.split(',', 1)
                practice = parts[1].strip() if len(parts) == 2 else None
                result.vacancies.append(Vacancy(self.config.firm, summary['job_id'], job.get('Reference', ''),
                    title, location, summary['url'], practice, 'Official job-title suffix' if practice else None,
                    pqe, utc_now(), bool(re.search(r'\bLondon\b', location, re.I)), 'Networx', 'Qualified legal title: ' + title))
            except Exception as exc:
                result.errors.append(f"Advert {summary['job_id']}: {exc}")
        result.coverage.update(board_vacancies=len(jobs), adverts_checked=len(result.vacancies), http_requests=self.requests + self.client.requests)
        result.status = ('PARTIAL' if jobs else 'BLOCKED') if result.errors else 'SUCCESS'
        result.finished_at = utc_now()
        return result
