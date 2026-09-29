import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from collectors.classify import is_sigma_vacancy
from collectors.html import Tree, text_field
from collectors.http import FetchError
from models import ScanResult, Vacancy, utc_now


@dataclass(frozen=True)
class WithersConfig:
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


class WithersCollector:
    def __init__(self, config, client, progress=lambda msg: None):
        self.config = config
        self.client = client
        self.progress = progress

    def collect(self):
        result = ScanResult(self.config.firm, self.config.board_url)
        self.progress('Fetching Withers board...')
        
        cards = {}
        
        try:
            html = self.client.get(self.config.board_url)
            root = Tree(html).root
            
            for section in root.find('section'):
                section_id = section.attrs.get('id', '')
                if not section_id.startswith('vacancy_'):
                    continue
                
                h2 = section.find('h2')
                if not h2:
                    continue
                a = h2[0].find('a')
                if not a:
                    continue
                
                title = a[0].text()
                href = a[0].attrs.get('href', '')
                url = urljoin(self.config.board_url, href)
                
                job_id = section_id.replace('vacancy_', '')
                
                # Extract location from p tag separated by pipes
                location = "Unknown"
                category = "Unknown"
                for p in section.find('p'):
                    text = p.text()
                    if '|' in text:
                        parts = [x.strip() for x in text.split('|')]
                        if len(parts) >= 2:
                            category = parts[0]
                            location = parts[1]
                        break
                
                cards[job_id] = {'title': title, 'url': url, 'location': location, 'category': category}
                
            result.coverage['board_pages'] = 1
            
        except FetchError as e:
            result.errors.append(str(e))
            result.finished_at = utc_now()
            return result
            
        for job_id, card in cards.items():
            title = card['title']
            url = card['url']
            location = card['location']
            category = card['category']
            
            if not is_sigma_vacancy(title):
                result.excluded.append({'job_id': job_id, 'title': title, 'url': url, 'reason': 'Not a qualified lawyer role'})
                continue
                
            self.progress(f'Fetching advert {job_id}...')
            try:
                html = self.client.get(url)
                
                vacancy = Vacancy(
                    firm=self.config.firm,
                    job_id=job_id,
                    reference=job_id,
                    title=title,
                    location=location,
                    url=url,
                    practice_area=category,
                    practice_area_source='Board category',
                    pqe=extract_pqe(html),
                    checked_at=utc_now(),
                    london=is_london(location),
                    category=category,
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
