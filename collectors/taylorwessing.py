"""Collector for Taylor Wessing (Winston Taylor EMEA careers board)."""
import re
from dataclasses import dataclass
from urllib.parse import urljoin
from collectors.html import Tree
from collectors.http import HttpClient, FetchError
from models import ScanResult, Vacancy, utc_now

LAWYER_TITLES = re.compile(r'\b(solicitor|lawyer|associate|partner|legal director|counsel|barrister)\b', re.I)
SUPPORT_ROLES = re.compile(r'\b(paralegal|secretar\w*|admin\w*|it|hr|marketing|assistant|coordinator|manager|specialist|advisor|analyst|engineer|developer|accountant|supervisor|trainee|training contract|open day|vacation scheme)\b', re.I)
PQE_PATTERN = re.compile(r'\bPQE\b|post[\s-]+qualifi(?:cation|ed)|years?[\'\s]+experience', re.I)

@dataclass(frozen=True)
class TaylorWessingConfig:
    firm: str = 'Taylor Wessing'
    board_url: str = 'https://careers.winstontaylor-emea.com/Careeropportunities/go/Career-opportunities/9053755/'


def is_lawyer(title: str) -> bool:
    if SUPPORT_ROLES.search(title):
        if not re.search(r'\b(?:solicitor|lawyer|associate|partner|legal director)\b', title, re.I):
            return False
    return bool(LAWYER_TITLES.search(title))


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


class TaylorWessingCollector:
    def __init__(self, config: TaylorWessingConfig, client: HttpClient, progress=lambda msg: None):
        self.config = config
        self.client = client
        self.progress = progress

    def collect(self) -> ScanResult:
        result = ScanResult(self.config.firm, self.config.board_url)
        self.progress(f"Fetching Taylor Wessing board from {self.config.board_url}...")

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
        for tr in tree.root.find('tr'):
            links = [a for a in tr.find('a') if '/job/' in a.attrs.get('href', '')]
            if links:
                title = links[0].text().strip()
                href = links[0].attrs.get('href', '')
                url = urljoin(self.config.board_url, href)
                
                tds = [td.text().strip() for td in tr.find('td') if td.text().strip()]
                loc = tds[-1] if tds else ''
                
                id_m = re.search(r'/(\d+)/?$', href)
                job_id = id_m.group(1) if id_m else href.split('/')[-2]
                
                if job_id not in seen_ids:
                    seen_ids.add(job_id)
                    cards.append({
                        'job_id': job_id,
                        'title': title,
                        'location': loc,
                        'url': url
                    })

        details_checked = 0
        for card in cards:
            title = card['title']
            location = card['location']
            url = card['url']
            job_id = card['job_id']
            summary = dict(card)

            if not is_lawyer(title):
                result.excluded.append({**summary, 'reason': 'Support or non-qualified role'})
                continue

            self.progress(f"Checking {job_id}: {title}")
            try:
                advert_html = self.client.get(url)
                details_checked += 1
                adv_tree = Tree(advert_html)
                
                desc_nodes = adv_tree.root.find('span', cls='jobdescription')
                desc_text = desc_nodes[0].text() if desc_nodes else adv_tree.root.text()
                pqe_text = extract_pqe(desc_text)
                
                v = Vacancy(
                    firm=self.config.firm,
                    job_id=job_id,
                    reference=f"TW-{job_id}",
                    title=title,
                    location=location,
                    url=url,
                    practice_area=None,
                    practice_area_source=None,
                    pqe=pqe_text,
                    checked_at=utc_now(),
                    london=is_london(location),
                    category='SuccessFactors',
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
