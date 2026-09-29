import re
import json
import urllib.request
import urllib.error
import time
from dataclasses import dataclass
from models import ScanResult, Vacancy, utc_now
from collectors.html import Tree

@dataclass(frozen=True)
class AllHiresConfig:
    firm: str
    base_url: str

LAWYER = re.compile(r'\b(solicitor|lawyer|associate|partner|legal director|counsel|barrister)\b', re.I)
SUPPORT = re.compile(r'\b(paralegal|secretar\w*|admin\w*|it|hr|marketing|assistant|coordinator|manager|specialist|advisor|analyst|engineer|business development|operations?|finance|talent|recruitment|reception\w*|trainee|apprentice|scheme|intern|clerk)\b', re.I)
PQE = re.compile(r'\bPQE\b|post[\s-]+qualifi(?:cation|ed)|years?[\'\s]+experience', re.I)

class AllHiresCollector:
    def __init__(self, config: AllHiresConfig, progress=lambda msg: None):
        self.config = config
        self.progress = progress
        self.requests = 0
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        self.opener.addheaders = [('User-Agent', 'SigmaLegalSearch/0.1')]
        self.token = None

    def _get_token(self):
        if self.token: return self.token
        self.requests += 1
        url = self.config.base_url.rstrip('/') + '/app/'
        try:
            res = self.opener.open(url, timeout=20)
            html = res.read().decode('utf-8')
            match = re.search(r'<input name="__RequestVerificationToken" type="hidden" value="([^"]+)"', html)
            if match:
                self.token = match.group(1)
            return self.token
        except Exception as e:
            raise RuntimeError(f"Failed to fetch token: {e}")

    def _fetch_api(self, endpoint: str):
        token = self._get_token()
        if not token:
            raise RuntimeError("Anti-forgery token not found in base HTML")
        
        url = self.config.base_url.rstrip('/') + endpoint
        req = urllib.request.Request(url)
        req.add_header('__RequestVerificationToken', token)
        req.add_header('Accept', 'application/json')
        
        self.requests += 1
        time.sleep(0.1)
        try:
            res = self.opener.open(req, timeout=20)
            return json.loads(res.read().decode('utf-8'))
        except urllib.error.URLError as e:
            raise RuntimeError(f"API fetch failed: {e}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"API JSON parse failed: {e}")

    def extract_pqe(self, description):
        sentences = re.split(r'(?<=[.!?])\s+', description)
        snippets = []
        for s in sentences:
            if PQE.search(s) and s not in snippets:
                snippets.append(s.strip())
        return ' | '.join(snippets) if snippets else None

    def collect(self) -> ScanResult:
        result = ScanResult(self.config.firm, self.config.base_url)
        self.progress(f"Fetching AllHires positions for {self.config.firm}...")
        
        try:
            data = self._fetch_api('/webapi/candidate/Positions?isIntranetReq=false')
            positions = data.get('Positions', [])
        except RuntimeError as e:
            result.errors.append(str(e))
            result.status = 'BLOCKED'
            result.finished_at = utc_now()
            return result

        details_checked = 0

        for p in positions:
            title = p.get('CandidateTitle') or p.get('PositionTitle') or ''
            loc = p.get('LocationText', '')
            job_id = str(p.get('ApplyingForID', ''))
            
            href = f"{self.config.base_url.rstrip('/')}/app/vacancies/{job_id}"
            summary = {'title': title, 'location': loc, 'job_id': job_id, 'url': href}
            
            if SUPPORT.search(title) or not LAWYER.search(title):
                result.excluded.append({**summary, 'reason': 'Not a qualified lawyer title / support role'})
                continue
                
            self.progress(f"Checking {job_id}: {title}")
            
            try:
                detail_data = self._fetch_api(f'/webapi/candidate/position/details/?id={job_id}&isIntranetReq=false')
                details_checked += 1
                
                desc_text = ''
                sections = detail_data.get('Sections', [])
                for s in sections:
                    header = s.get('SectionHeader') or ''
                    text = s.get('SectionText') or ''
                    desc_text += f"{header}\n{text}\n"
                    
                clean_desc = re.sub(r'<[^>]+>', ' ', desc_text)
                london = bool(re.search(r'\blondon\b', loc, re.I))
                pqe_text = self.extract_pqe(clean_desc)
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
                    category='AllHires',
                    qualification_evidence=evidence
                )
                result.vacancies.append(v)
            except RuntimeError as e:
                result.errors.append(f"Detail API error for {job_id}: {e}")

        result.coverage = dict(board_complete=not result.errors, board_vacancies=len(positions),
                               adverts_checked=details_checked, http_requests=self.requests)
        
        if result.errors:
            result.status = 'PARTIAL' if positions else 'BLOCKED'
        elif result.review:
            result.status = 'LIMITED'
        else:
            result.status = 'SUCCESS'
            
        result.vacancies.sort(key=lambda v: (not v.london, v.title.casefold(), v.job_id))
        result.finished_at = utc_now()
        return result
