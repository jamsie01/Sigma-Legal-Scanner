import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from collectors.html import Tree, text_field
from collectors.http import FetchError
from models import ScanResult, Vacancy, utc_now


@dataclass(frozen=True)
class EployConfig:
    firm: str
    board_url: str
    max_pages: int = 20


LAWYER = re.compile(r'\b(solicitor|lawyer|associate|partner|legal director|counsel|barrister)\b', re.I)
SUPPORT = re.compile(r'\b(paralegal|secretar\w*|admin|it|marketing|hr|assistant|trainee|apprentice)\b', re.I)


def is_london(location):
    return bool(re.search(r'\bLondon\b', location, re.I))


def is_lawyer(title):
    return bool(LAWYER.search(title)) and not bool(SUPPORT.search(title))


def extract_pqe(description):
    snippets = []
    for node in Tree(description).root.walk():
        if node.tag in {'p', 'li'}:
            value = node.text()
            if re.search(r'\bpqe\b|post[\s-]+qualifi(?:cation|ed)|newly[\s-]+qualified', value, re.I):
                if value not in snippets:
                    snippets.append(value)
    return ' | '.join(snippets) or None


class EployCollector:
    def __init__(self, config, client, progress=lambda msg: None):
        self.config = config
        self.client = client
        self.progress = progress

    def collect(self):
        result = ScanResult(self.config.firm, self.config.board_url)
        self.progress('Fetching Eploy board...')
        
        cards = {}
        pages_visited = 0
        errors = []
        
        for page in range(1, self.config.max_pages + 1):
            url = f"{self.config.board_url}?page={page}"
            try:
                html = self.client.get(url)
                pages_visited += 1
                root = Tree(html).root
                
                job_links = []
                for a in root.find('a'):
                    href = a.attrs.get('href', '')
                    if '/Jobs/Advert/' in href:
                        job_links.append(href)
                
                if not job_links:
                    break
                
                for link in job_links:
                    full_link = urljoin(url, link)
                    job_id_match = re.search(r'/Jobs/Advert/(\d+)', link)
                    if not job_id_match:
                        continue
                    job_id = job_id_match.group(1)
                    if job_id not in cards:
                        cards[job_id] = full_link
                        
            except FetchError as e:
                errors.append(str(e))
                break
                
        result.errors.extend(errors)
        result.coverage['board_pages'] = pages_visited
        
        for job_id, url in cards.items():
            self.progress(f'Fetching advert {job_id}...')
            try:
                html = self.client.get(url)
                root = Tree(html).root
                
                title_node = root.find('h1')
                title = title_node[0].text() if title_node else ''
                
                text = root.text()
                location = "London" if is_london(text) else "Other"
                
                if not is_lawyer(title):
                    result.excluded.append({'job_id': job_id, 'title': title, 'url': url, 'reason': 'Not a qualified lawyer role'})
                    continue
                
                vacancy = Vacancy(
                    firm=self.config.firm,
                    job_id=job_id,
                    reference=job_id,
                    title=title,
                    location=location,
                    url=url,
                    practice_area=None,
                    practice_area_source=None,
                    pqe=extract_pqe(html),
                    checked_at=utc_now(),
                    london=is_london(location),
                    category='legal',
                    qualification_evidence='Lawyer title matched'
                )
                result.vacancies.append(vacancy)
            except FetchError as e:
                result.errors.append(str(e))
                
        if result.errors:
            result.status = 'PARTIAL' if cards else 'BLOCKED'
        else:
            result.status = 'SUCCESS'
            
        result.finished_at = utc_now()
        return result
