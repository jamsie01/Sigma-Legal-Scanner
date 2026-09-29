"""Collector for Morrison Foerster (MoFo careers API)."""
import json
import re
import urllib.request
import urllib.error
import time
from dataclasses import dataclass
from models import ScanResult, Vacancy, utc_now

LAWYER_TITLES = re.compile(r'\b(solicitor|lawyer|associate|partner|legal director|counsel|barrister)\b', re.I)
SUPPORT_ROLES = re.compile(r'\b(paralegal|secretar\w*|admin\w*|it|hr|marketing|assistant|coordinator|manager|specialist|advisor|analyst|engineer|developer|accountant|supervisor|trainee|training contract|open day|vacation scheme)\b', re.I)
PQE_PATTERN = re.compile(r'\bPQE\b|post[\s-]+qualifi(?:cation|ed)|years?[\'\s]+experience', re.I)

@dataclass(frozen=True)
class MofoConfig:
    firm: str = 'Morrison Foerster'
    api_url: str = 'https://mofo.career.page/api/jobs'


def is_lawyer(title: str) -> bool:
    if SUPPORT_ROLES.search(title):
        if not re.search(r'\b(?:solicitor|lawyer|associate|partner|legal director)\b', title, re.I):
            return False
    return bool(LAWYER_TITLES.search(title))


def is_london(location: str) -> bool:
    return bool(re.search(r'\bLondon\b', location, re.I))


def extract_pqe(description: str) -> str | None:
    clean_desc = re.sub(r'<[^>]+>', ' ', description)
    sentences = re.split(r'(?<=[.!?])\s+', clean_desc)
    snippets = []
    for s in sentences:
        if PQE_PATTERN.search(s):
            clean = s.strip()
            if clean and clean not in snippets:
                snippets.append(clean)
    return ' | '.join(snippets) if snippets else None


class MofoCollector:
    def __init__(self, config: MofoConfig, progress=lambda msg: None):
        self.config = config
        self.progress = progress
        self.requests = 0

    def collect(self) -> ScanResult:
        result = ScanResult(self.config.firm, self.config.api_url)
        self.progress(f"Fetching Morrison Foerster API jobs...")
        
        all_jobs = []
        page = 1
        max_pages = 10
        
        while page <= max_pages:
            url = f"{self.config.api_url}?page={page}"
            req = urllib.request.Request(url, headers={
                'User-Agent': 'SigmaLegalSearch/0.1 (local vacancy checker)',
                'Accept': 'application/json'
            })
            self.requests += 1
            time.sleep(0.1)
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    jobs = data.get('jobs', [])
                    if not jobs:
                        break
                    all_jobs.extend(jobs)
                    page += 1
            except Exception as e:
                result.errors.append(f"MoFo API error on page {page}: {e}")
                break

        for item in all_jobs:
            d = item.get('data', {})
            title = d.get('title', '')
            slug = d.get('slug', '')
            loc = d.get('full_location') or (d.get('city', '') + ', ' + d.get('country', ''))
            desc = d.get('description', '')
            job_url = f"https://mofo.career.page/jobs/{slug}"
            
            summary = {
                'title': title,
                'location': loc,
                'url': job_url,
                'job_id': slug
            }
            
            if not is_lawyer(title):
                result.excluded.append({**summary, 'reason': 'Support or non-qualified role'})
                continue

            pqe_text = extract_pqe(desc)
            v = Vacancy(
                firm=self.config.firm,
                job_id=slug,
                reference=f"MOFO-{slug}",
                title=title,
                location=loc,
                url=job_url,
                practice_area=None,
                practice_area_source=None,
                pqe=pqe_text,
                checked_at=utc_now(),
                london=is_london(loc),
                category='Jibe',
                qualification_evidence='Qualified legal role title: ' + title
            )
            result.vacancies.append(v)

        result.coverage = dict(
            board_complete=not result.errors,
            board_vacancies=len(all_jobs),
            adverts_checked=len(result.vacancies),
            http_requests=self.requests
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
