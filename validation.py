"""Shared publication gates: persisted decisions, role policy and live advert checks."""
from dataclasses import asdict
import re
from urllib.parse import urlparse
from collectors.classify import is_sigma_vacancy
from collectors.http import HttpClient, FetchError
from collectors.html import Tree
from models import utc_now


def validate_result(result, config, collector, decisions):
    kept = []
    seen = set()
    approved_host = urlparse(result.source).hostname
    cached_client = getattr(collector, 'client', None)
    for vacancy in result.vacancies:
        row = asdict(vacancy)
        reason = decisions.get((vacancy.firm, vacancy.job_id))
        if reason or not is_sigma_vacancy(vacancy.title):
            result.excluded.append({**row, 'reason': reason or 'Excluded by shared fee-earning role policy'})
            continue
        if vacancy.job_id in seen:
            result.errors.append(f'Duplicate vacancy identity: {vacancy.job_id}')
            continue
        seen.add(vacancy.job_id)
        try:
            if not vacancy.job_id or not vacancy.title:
                raise FetchError('Missing advert identity or title')
            parsed = urlparse(vacancy.url)
            if parsed.scheme != 'https' or parsed.hostname != approved_host:
                raise FetchError('Advert URL is outside the configured official source host')
            client = cached_client or HttpClient(approved_host)
            cached = getattr(client, 'pages', {}).get(vacancy.url)
            if parsed.path.lower().endswith('.pdf'):
                client.get(vacancy.url, allow_pdf=True)
                result.review.append({**row, 'reason': 'PDF link verified; practice/PQE content needs browser review'})
            else:
                content = cached if cached is not None else client.get(vacancy.url)
                text = Tree(content).root.text()
                normalized = lambda value: re.sub(r'\W+', '', value).casefold()
                # Workday and AllHires serve JS/React shells; their detail APIs supply identity and content.
                if vacancy.category not in ('Workday', 'AllHires') and normalized(vacancy.title) not in normalized(text):
                    raise FetchError('Advert title is missing from the linked page; possible generic redirect or JS-only page')
            vacancy.checked_at = utc_now()
        except (FetchError, ValueError) as exc:
            result.errors.append(f"Advert {vacancy.job_id}: {exc}")
            result.review.append({**row, 'reason': str(exc)})
            continue
        vacancy.london = bool(re.search(r'\bLondon\b', vacancy.location, re.I))
        if not vacancy.location or vacancy.location.casefold() in ('other', 'unknown', 'n/a'):
            result.review.append({**row, 'reason': 'Office could not be verified from a vacancy-specific field'})
        kept.append(vacancy)
    result.vacancies = kept
    if result.errors:
        result.status = 'PARTIAL' if kept or result.coverage.get('board_vacancies') else 'BLOCKED'
    elif result.review or not result.coverage.get('board_complete', False):
        result.status = 'LIMITED'
    else:
        result.status = 'SUCCESS'
    result.finished_at = utc_now()
    return result
