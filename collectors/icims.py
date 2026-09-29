import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlencode
from collectors.classify import is_sigma_vacancy
from collectors.html import Tree
from collectors.http import FetchError
from models import ScanResult, Vacancy, utc_now

@dataclass(frozen=True)
class IcimsConfig:
    firm: str
    board_url: str

PQE = re.compile(r'\bPQE\b|post[\s-]+qualifi(?:cation|ed)|years?[\'\s]+experience', re.I)

class IcimsCollector:
    def __init__(self, config: IcimsConfig, client, progress=lambda msg: None):
        self.config = config
        self.client = client
        self.progress = progress

    def extract_pqe(self, description):
        sentences = re.split(r'(?<=[.!?])\s+', description)
        snippets = []
        for s in sentences:
            if PQE.search(s) and s not in snippets:
                snippets.append(s.strip())
        return ' | '.join(snippets) if snippets else None

    def collect(self) -> ScanResult:
        result = ScanResult(self.config.firm, self.config.board_url)
        self.progress(f"Fetching iCIMS board for {self.config.firm}...")
        
        cards = {}
        page = 0
        
        while True:
            # iCIMS uses p param for pagination (sometimes 'pr') but let's just append or add if it exists
            url = self.config.board_url
            if '?' in url:
                url += f"&pr={page}"
            else:
                url += f"?pr={page}"
                
            try:
                html = self.client.get(url)
            except FetchError as e:
                result.errors.append(f"List API error: {e}")
                break
                
            root = Tree(html).root
            items = root.find(cls='iCIMS_JobCardItem')
            if not items:
                items = root.find(cls='iCIMS_JobListingRow') # Some icims use this class
                
            if not items:
                break
                
            new_cards = 0
            for item in items:
                link_node = item.find('a', cls='iCIMS_Anchor') or item.find('a')
                if not link_node or not link_node[0].attrs.get('href'):
                    continue
                href = link_node[0].attrs.get('href')
                
                title_node = item.find('h3') or item.find('h2') or link_node
                title = title_node[0].text().strip() if title_node else ''
                
                job_id = href.split('/')[-2] if '/' in href else title
                
                loc_node = item.find(cls='iCIMS_JobHeaderData')
                loc = loc_node[0].text().strip() if loc_node else ''
                
                if job_id not in cards:
                    cards[job_id] = {'title': title, 'href': href, 'loc': loc}
                    new_cards += 1
                    
            if new_cards == 0:
                break
                
            page += 1
            if page > 20: # safety limit
                break

        full_complete = not result.errors
        details_checked = 0

        for job_id, card in cards.items():
            title = card['title']
            href = card['href']
            loc = card['loc']
            summary = {'title': title, 'location': loc, 'job_id': job_id, 'url': href}
            
            if not is_sigma_vacancy(title):
                result.excluded.append({**summary, 'reason': 'Not a qualified lawyer title / support role'})
                continue
                
            self.progress(f"Checking {job_id}: {title}")
            try:
                detail_html = self.client.get(href)
                details_checked += 1
                detail_root = Tree(detail_html).root
                desc_node = detail_root.find(cls='iCIMS_JobContent')
                desc = desc_node[0].text() if desc_node else Tree(detail_html).root.text()
                
                london = bool(re.search(r'\blondon\b', loc, re.I))
                pqe_text = self.extract_pqe(desc)
                evidence = 'Qualified legal role title: ' + title
                
                v = Vacancy(
                    firm=self.config.firm,
                    job_id=job_id,
                    reference=job_id,
                    title=title,
                    location=loc,
                    url=href,
                    practice_area=None,
                    practice_area_source=None,
                    pqe=pqe_text,
                    checked_at=utc_now(),
                    london=london,
                    category='iCIMS',
                    qualification_evidence=evidence
                )
                result.vacancies.append(v)
            except FetchError as e:
                result.errors.append(f"Detail error for {job_id}: {e}")

        result.coverage = dict(board_complete=full_complete, board_vacancies=len(cards),
                               adverts_checked=details_checked, http_requests=self.client.requests)
        
        if result.errors:
            result.status = 'PARTIAL' if cards else 'BLOCKED'
        elif result.review:
            result.status = 'LIMITED'
        else:
            result.status = 'SUCCESS'
            
        result.vacancies.sort(key=lambda v: (not v.london, v.title.casefold(), v.job_id))
        result.finished_at = utc_now()
        return result
