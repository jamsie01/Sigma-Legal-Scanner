import re
from dataclasses import dataclass
from urllib.parse import urljoin

from collectors.html import Tree
from collectors.http import FetchError
from models import ScanResult, Vacancy, utc_now

@dataclass(frozen=True)
class HausfeldConfig:
    firm: str
    board_url: str


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


class HausfeldCollector:
    def __init__(self, config, client, progress=lambda msg: None):
        self.config = config
        self.client = client
        self.progress = progress

    def collect(self):
        result = ScanResult(self.config.firm, self.config.board_url)
        self.progress('Fetching Hausfeld board...')
        
        cards = {}
        
        try:
            html = self.client.get(self.config.board_url)
            root = Tree(html).root
            
            for element in root.find(cls='job-listing__item'):
                a_tags = element.find('a')
                if not a_tags:
                    continue
                    
                href = a_tags[0].attrs.get('href', '')
                if not href:
                    continue
                    
                title = a_tags[0].text().strip()
                if not title:
                    h2 = element.find('h2')
                    h3 = element.find('h3')
                    if h2:
                        title = h2[0].text().strip()
                    elif h3:
                        title = h3[0].text().strip()
                
                url = urljoin(self.config.board_url, href)
                job_id = href.strip('/').split('/')[-1]
                
                cards[job_id] = {'title': title, 'url': url}
            
            result.coverage['board_pages'] = 1
            
        except FetchError as e:
            result.errors.append(str(e))
            result.finished_at = utc_now()
            return result
            
        for job_id, card in cards.items():
            title = card['title']
            url = card['url']
            
            if not is_lawyer(title):
                result.excluded.append({'job_id': job_id, 'title': title, 'url': url, 'reason': 'Not a qualified lawyer role'})
                continue
                
            self.progress(f'Fetching advert {job_id}...')
            try:
                html = self.client.get(url)
                root = Tree(html).root
                
                text = root.text()
                location = "London" if is_london(text) else "Other"
                
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
