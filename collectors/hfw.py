import re
from dataclasses import dataclass
from urllib.parse import urlparse

from collectors.classify import is_sigma_vacancy
from collectors.html import Tree
from collectors.http import FetchError
from models import ScanResult, Vacancy, utc_now

@dataclass(frozen=True)
class HfwConfig:
    firm: str
    board_url: str


def is_london(location):
    return bool(re.search(r'\bLondon\b', location, re.I))


def extract_pqe(description):
    snippets = []
    for node in Tree(description).root.walk():
        if node.tag in {'p', 'li'}:
            value = node.text()
            if re.search(r'\bpqe\b|post[\s-]+qualifi(?:cation|ed)|newly[\s-]+qualified', value, re.I):
                if value not in snippets:
                    snippets.append(value)
    return ' | '.join(snippets) or None


class HfwCollector:
    def __init__(self, config, client, progress=lambda msg: None):
        self.config = config
        self.client = client
        self.progress = progress

    def collect(self):
        result = ScanResult(self.config.firm, self.config.board_url)
        self.progress('Fetching HFW board...')
        
        cards = {}
        
        url = self.config.board_url
        try:
            html = self.client.get(url)
            root = Tree(html).root
            
            # Find job links
            for a in root.find('a'):
                href = a.attrs.get('href', '')
                if '/careers/vacancies/' in href and href != url and '?_career_location' not in href:
                    if href.endswith('/'):
                        job_id = href.strip('/').split('/')[-1]
                    else:
                        job_id = href.split('/')[-1]
                    
                    if job_id and job_id != 'vacancies':
                        cards[job_id] = href
                        
            result.coverage['board_pages'] = 1
            
        except FetchError as e:
            result.errors.append(str(e))
            result.finished_at = utc_now()
            return result
            
        for job_id, url in cards.items():
            self.progress(f'Fetching advert {job_id}...')
            try:
                html = self.client.get(url)
                root = Tree(html).root
                
                title_node = root.find('h1')
                title = title_node[0].text() if title_node else job_id.replace('-', ' ').title()
                
                text = root.text()
                location = "London" if is_london(text) else "Other"
                
                if not is_sigma_vacancy(title):
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
