import json
import re
import urllib.request
import urllib.error
import time
from dataclasses import dataclass
from urllib.parse import urlparse
from collectors.classify import is_sigma_vacancy
from models import ScanResult, Vacancy, utc_now

@dataclass(frozen=True)
class WorkdayConfig:
    firm: str
    base_url: str
    location_filter: str = None

PQE_PATTERN = re.compile(r'\bPQE\b|post[\s-]+qualifi(?:cation|ed)|years?[\'\s]+experience', re.I)

def is_london(location: str, additional_locations: list) -> bool:
    locs = [location] + (additional_locations or [])
    return any('London' in loc for loc in locs if isinstance(loc, str))

def extract_pqe(description: str) -> str | None:
    sentences = re.split(r'(?<=[.!?])\s+', description)
    snippets = []
    for s in sentences:
        if PQE_PATTERN.search(s):
            if s not in snippets:
                snippets.append(s.strip())
    return ' | '.join(snippets) if snippets else None

class WorkdayCollector:
    def __init__(self, config: WorkdayConfig, progress=lambda msg: None):
        self.config = config
        self.progress = progress
        self.requests = 0

    def _fetch_json(self, url: str, data=None):
        self.requests += 1
        time.sleep(0.1)
        req_headers = {
            'User-Agent': 'SigmaLegalSearch/0.1 (local vacancy checker)',
            'Accept': 'application/json'
        }
        req_data = None
        if data is not None:
            req_headers['Content-Type'] = 'application/json'
            req_data = json.dumps(data).encode('utf-8')
        
        req = urllib.request.Request(url, data=req_data, headers=req_headers)
        if data is not None:
            req.method = 'POST'
        
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                return json.loads(response.read().decode('utf-8'))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError) as e:
            raise RuntimeError(f"Fetch failed: {e}")

    def collect(self) -> ScanResult:
        result = ScanResult(self.config.firm, self.config.base_url)
        limit = 20
        offset = 0
        total = None
        jobs_found = []
        
        self.progress('Fetching Workday jobs list...')
        
        while total is None or offset < total:
            url = f"{self.config.base_url}/jobs"
            payload = {"limit": limit, "offset": offset, "searchText": ""}
            try:
                res_data = self._fetch_json(url, data=payload)
                if total is None:
                    total = res_data.get('total', 0)
                postings = res_data.get('jobPostings', [])
                jobs_found.extend(postings)
                offset += limit
            except RuntimeError as e:
                result.errors.append(f"List API error: {e}")
                break

        full_complete = not result.errors
        details_checked = 0

        for job in jobs_found:
            title = job.get('title', '')
            ext_path = job.get('externalPath', '')
            job_id_summary = ext_path.split('/')[-1] if ext_path else title
            
            summary = {
                'title': title,
                'location': job.get('locationsText', ''),
                'url': f"{self.config.base_url.rsplit('/wday', 1)[0]}{ext_path}" if ext_path else '',
                'job_id': job_id_summary
            }
            
            if not is_sigma_vacancy(title):
                result.excluded.append({**summary, 'reason': 'Not a qualified lawyer title / support role'})
                continue
                
            self.progress(f"Checking {job_id_summary}: {title}")
            
            detail_url = f"{self.config.base_url}{ext_path}"
            try:
                detail_data = self._fetch_json(detail_url)
                details_checked += 1
                
                info = detail_data.get('jobPostingInfo', {})
                desc = info.get('jobDescription', '')
                loc = info.get('location', '')
                add_locs = info.get('additionalLocations', [])
                req_id = info.get('jobReqId', job_id_summary)
                
                london_status = is_london(loc, add_locs)
                
                # HTML tag stripping from description for pqe extraction and evidence matching
                clean_desc = re.sub(r'<[^>]+>', ' ', desc)
                pqe_text = extract_pqe(clean_desc)
                evidence = 'Qualified legal role title: ' + title
                
                v = Vacancy(
                    firm=self.config.firm,
                    job_id=req_id,
                    reference=req_id,
                    title=title,
                    location=loc + (", " + ", ".join(add_locs) if add_locs else ""),
                    url=summary['url'],
                    practice_area=None,
                    practice_area_source=None,
                    pqe=pqe_text,
                    checked_at=utc_now(),
                    london=london_status,
                    category='Workday',
                    qualification_evidence=evidence
                )
                result.vacancies.append(v)
            except RuntimeError as e:
                result.errors.append(f"Detail API error for {job_id_summary}: {e}")
                
        result.coverage = dict(
            board_complete=full_complete,
            board_vacancies=len(jobs_found),
            adverts_checked=details_checked,
            http_requests=self.requests
        )
        
        if result.errors:
            result.status = 'PARTIAL' if jobs_found else 'BLOCKED'
        elif result.review:
            result.status = 'LIMITED'
        else:
            result.status = 'SUCCESS'
            
        result.vacancies.sort(key=lambda v: (not v.london, v.title.casefold(), v.job_id))
        result.finished_at = utc_now()
        return result
