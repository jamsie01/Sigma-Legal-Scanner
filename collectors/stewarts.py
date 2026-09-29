import re
from dataclasses import dataclass

from collectors.classify import is_sigma_vacancy
from collectors.html import Tree
from collectors.http import FetchError
from models import ScanResult, Vacancy, utc_now

@dataclass(frozen=True)
class StewartsConfig:
    firm: str
    board_url: str


def is_london(location):
    return bool(re.search(r'\bLondon\b', location, re.I))


class StewartsCollector:
    def __init__(self, config, client, progress=lambda msg: None):
        self.config = config
        self.client = client
        self.progress = progress

    def collect(self):
        result = ScanResult(self.config.firm, self.config.board_url)
        self.progress('Fetching Stewarts board...')
        
        cards = {}
        
        try:
            html = self.client.get(self.config.board_url)
            root = Tree(html).root
            
            for ul in root.find('ul'):
                for li in ul.find('li'):
                    a_tags = li.find('a')
                    if not a_tags:
                        continue
                        
                    href = a_tags[0].attrs.get('href', '')
                    if '.pdf' not in href.lower():
                        continue
                        
                    text = li.text()
                    # Strip 'Job Description' or 'job description'
                    text = re.sub(r'job description\s*$', '', text, flags=re.IGNORECASE).strip()
                    text = text.strip('-').strip('–').strip()
                    
                    parts = re.split(r'\s*[-–]\s*', text)
                    if len(parts) >= 3:
                        title = parts[0]
                        category = parts[1]
                        location = parts[2]
                    elif len(parts) == 2:
                        title = parts[0]
                        location = parts[1]
                        category = 'Unknown'
                    else:
                        title = text
                        location = 'London' if is_london(text) else 'Unknown'
                        category = 'Unknown'
                        
                    job_id = href.split('/')[-1].replace('.pdf', '')
                    
                    cards[job_id] = {'title': title, 'url': href, 'location': location, 'category': category}
            
            result.coverage['board_pages'] = 1
            
        except FetchError as e:
            result.errors.append(str(e))
            result.finished_at = utc_now()
            return result
            
        for job_id, card in cards.items():
            title = card['title']
            url = card['url']
            location = card['location']
            
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
                practice_area=card['category'],
                practice_area_source='List item category',
                pqe=None, # PDFs not parsed yet
                checked_at=utc_now(),
                london=is_london(location),
                category=card['category'],
                qualification_evidence='Lawyer title matched'
            )
            result.vacancies.append(vacancy)
            
        if result.errors:
            result.status = 'PARTIAL' if cards else 'BLOCKED'
        else:
            result.status = 'SUCCESS'
            
        result.finished_at = utc_now()
        return result
