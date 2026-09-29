"""Collector for CVMail UK boards (Squire Patton Boggs, Kirkland & Ellis)."""
import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from collectors.classify import is_sigma_vacancy
from collectors.html import Tree
from collectors.http import HttpClient, FetchError
from models import ScanResult, Vacancy, utc_now

PQE_PATTERN = re.compile(r'\bPQE\b|post[\s-]+qualifi(?:cation|ed)|years?[\'\s]+experience', re.I)

@dataclass(frozen=True)
class CvmailConfig:
    firm: str
    board_url: str


def is_london(location: str) -> bool:
    return bool(re.search(r'\bLondon\b', location, re.I))


def extract_pqe(description: str) -> str | None:
    sentences = re.split(r'(?<=[.!?])\s+', description)
    snippets = []
    for s in sentences:
        if PQE_PATTERN.search(s):
            clean = s.strip()
            if clean and clean not in snippets:
                snippets.append(clean)
    return ' | '.join(snippets) if snippets else None


class CvmailCollector:
    def __init__(self, config: CvmailConfig, client: HttpClient, progress=lambda msg: None):
        self.config = config
        self.client = client
        self.progress = progress

    def collect(self) -> ScanResult:
        result = ScanResult(self.config.firm, self.config.board_url)
        self.progress(f"Fetching CVMail board for {self.config.firm}...")
        
        try:
            html = self.client.get(self.config.board_url)
        except FetchError as e:
            result.errors.append(f"Board fetch error: {e}")
            result.status = 'BLOCKED'
            result.finished_at = utc_now()
            return result

        tree = Tree(html)
        seen_ids = set()
        cards = []
        links = [a for a in tree.root.find('a') if 'jobSpecific' in a.attrs.get('href', '')]
        for a in links:
            title = a.text().strip()
            if not title or title.isdigit():
                continue
            href = a.attrs.get('href', '')
            job_id_m = re.search(r'jobId=(\d+)', href)
            job_id = job_id_m.group(1) if job_id_m else title
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            node = a
            while node and node.tag != 'tr':
                node = node.parent
            location = ''
            if node:
                tds = [td.text().strip() for td in node.find('td') if td.text().strip()]
                if len(tds) >= 3 and tds[0].isdigit():
                    location = tds[2]
                elif len(tds) >= 2:
                    location = tds[1]
            cards.append({
                'job_id': job_id,
                'title': title,
                'location': location,
                'url': urljoin(self.config.board_url, href)
            })

        details_checked = 0
        for card in cards:
            title = card['title']
            location = card['location']
            url = card['url']
            job_id = card['job_id']
            summary = dict(card)

            if not is_sigma_vacancy(title):
                result.excluded.append({**summary, 'reason': 'Support or non-qualified role'})
                continue

            self.progress(f"Checking {job_id}: {title}")
            try:
                advert_html = self.client.get(url)
                details_checked += 1
                adv_tree = Tree(advert_html)
                clean_text = adv_tree.root.text()
                pqe_text = extract_pqe(clean_text)
                
                v = Vacancy(
                    firm=self.config.firm,
                    job_id=job_id,
                    reference=f"{self.config.firm}-{job_id}",
                    title=title,
                    location=location,
                    url=url,
                    practice_area=None,
                    practice_area_source=None,
                    pqe=pqe_text,
                    checked_at=utc_now(),
                    london=is_london(location) or 'Any UK Office' in location,
                    category='CVMail',
                    qualification_evidence='Qualified legal role title: ' + title
                )
                result.vacancies.append(v)
            except FetchError as e:
                result.errors.append(f"Detail fetch error for {job_id}: {e}")

        result.coverage = dict(
            board_complete=not result.errors,
            board_vacancies=len(cards),
            adverts_checked=details_checked,
            http_requests=self.client.requests
        )

        if result.errors:
            result.status = 'PARTIAL' if result.vacancies else 'BLOCKED'
        elif result.review:
            result.status = 'LIMITED'
        else:
            result.status = 'SUCCESS'

        result.vacancies.sort(key=lambda v: (not v.london, v.title.casefold(), v.job_id))
        result.finished_at = utc_now()
        return result
