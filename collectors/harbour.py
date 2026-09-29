"""Reusable collector for the observed Harbour server-rendered board format.

Configuration supplies firm, board URL and location field. Other Harbour boards
must be verified against their actual markup before adding them to the registry.
"""
import json
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlencode
from collectors.html import Tree, text_field
from collectors.http import FetchError
from models import ScanResult, Vacancy, utc_now


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class HarbourConfig:
    firm: str
    board_url: str
    location_field: str
    location_name: str = 'London'
    max_pages: int = 100


JOB_PATH = re.compile(r'^/vacancies/(\d+)/(?:[^/?#]*)/?$')
LAWYER = re.compile(r'\b(solicitor|lawyer|associate|partner|legal director|legal counsel|barrister)\b', re.I)
SUPPORT = re.compile(r'\b(paralegal|secretar\w*|office assistant|case handler|apprentic\w*|trainee|training contract|vacation scheme|open evening|change trainer)\b', re.I)
EMPTY = 'Sorry, there are no vacancies that match your searched criteria at the moment.'
QUALIFICATION = re.compile(r'(?:qualified|admitted|practising)\s+(?:\w+\s+){0,3}(?:solicitor|lawyer|attorney|barrister)|(?:solicitor|lawyer|attorney|barrister)\s+(?:with\s+)?\d', re.I)


def is_london(location):
    return bool(re.search(r'\bLondon\b', location, re.I))


def lawyer_title(title, category):
    if category == 'business_professionals':
        return bool(re.search(r'\b(solicitor|lawyer|legal counsel|barrister)\b', title, re.I))
    return bool(LAWYER.search(title))


def parse_board(html, url):
    root = Tree(html).root
    if not root.find('form', id='vacancy-search-form'):
        raise ParseError('Careers search form missing (block page or changed markup)')
    cards = []
    for card in root.find(cls='bio'):
        title = text_field(card, 'vacancy_title')
        location = text_field(card, 'value_location')
        links = [urljoin(url, n.attrs.get('href', '')) for n in card.find('a')
                 if JOB_PATH.match(urlparse(urljoin(url, n.attrs.get('href', ''))).path)]
        if not title or not location or len(set(links)) != 1:
            raise ParseError('Incomplete vacancy card: title, location or advert link missing')
        link = links[0]
        if urlparse(link).netloc != urlparse(url).netloc:
            raise ParseError('Advert link outside official host')
        media = card.find(cls='bio-media')
        category = next((c.removeprefix('category_') for node in media
                         for c in node.attrs.get('class', '').split() if c.startswith('category_')), '')
        if not category:
            raise ParseError('Vacancy category missing')
        cards.append(dict(job_id=JOB_PATH.match(urlparse(link).path).group(1),
                          title=title, location=location, url=link, category=category))
    if len({c['job_id'] for c in cards}) != len(cards):
        raise ParseError('Duplicate job IDs on a listing page')
    pages = {1}
    current = 1
    for pagination in root.find(cls='pagination'):
        for link in pagination.find('a'):
            href = link.attrs.get('href')
            if not href:
                continue
            match = re.fullmatch(r'/vacancies/page/(\d+)/', urlparse(urljoin(url, href)).path)
            if not match:
                raise ParseError('Unrecognised pagination link')
            number = int(match.group(1))
            pages.add(number)
            if link.parent and 'current' in link.parent.attrs.get('class', '').split():
                current = number
    if not cards and EMPTY not in root.text():
        raise ParseError('No cards and no explicit empty-results message')
    if not cards and len(pages) > 1:
        raise ParseError('Empty page unexpectedly has pagination')
    return root, cards, pages, current


def extract_pqe(description):
    """Return source sentences, preserving ranges, plus signs and caveats."""
    root = Tree(description).root
    snippets = []
    for node in root.walk():
        if node.tag not in {'p', 'li'}:
            continue
        if any(n.tag in {'p', 'li'} for n in list(node.walk())[1:]):
            continue
        value = node.text()
        if re.search(r'\bPQE\b|post[\s-]+qualifi(?:cation|ed)|newly[\s-]+qualified', value, re.I):
            if value not in snippets:
                snippets.append(value)
    return ' | '.join(snippets) or None


def job_postings(value):
    if isinstance(value, dict):
        types = value.get('@type', [])
        if types == 'JobPosting' or isinstance(types, list) and 'JobPosting' in types:
            yield value
        for key in ('@graph', 'mainEntity'):
            if key in value:
                yield from job_postings(value[key])
    elif isinstance(value, list):
        for entry in value:
            yield from job_postings(entry)


def parse_advert(html, card, firm):
    root = Tree(html).root
    postings = []
    for script in root.find('script'):
        if script.attrs.get('type') == 'application/ld+json':
            try:
                postings.extend(job_postings(json.loads(script.raw())))
            except json.JSONDecodeError as exc:
                raise ParseError('Invalid structured advert JSON') from exc
    if len(postings) != 1:
        raise ParseError('Expected exactly one structured JobPosting')
    posting = postings[0]
    identifier = posting.get('identifier', {})
    if not isinstance(identifier, dict) or str(identifier.get('value')) != card['job_id']:
        raise ParseError('Advert ID does not match listing ID')
    if not isinstance(posting.get('title'), str) or not isinstance(posting.get('description'), str):
        raise ParseError('Advert title/description must be text')
    title = posting['title'].strip()
    description = posting.get('description', '')
    location = text_field(root, 'value_location')
    reference = text_field(root, 'value_reference')
    if not title or not description or not location or not reference:
        raise ParseError('Advert missing title, description, location or reference')
    if title != card['title'] or location != card['location']:
        raise ParseError('Advert/listing changed during scan; retry next scan')
    plain = Tree(description).root.text()
    qualification = QUALIFICATION.search(plain)
    evidence = 'Qualified legal role title: ' + title if lawyer_title(title, card['category']) else None
    if qualification:
        evidence = plain[max(0, qualification.start()-45):qualification.end()+150]
    if not evidence:
        optional = re.search(r'Admission as an attorney is an added advantage', plain, re.I)
        if optional:
            return None, 'exclude', optional.group(0)
        return None, 'review', 'No explicit qualified-lawyer title or qualification requirement found'
    practice = text_field(root, 'value_practice_area') or text_field(root, 'value_department')
    practice_source = 'official advert field' if practice else None
    if not practice:
        parts = re.split(r'\s*[-–—]\s*', title, maxsplit=1)
        if len(parts) == 2 and parts[1]:
            practice, practice_source = parts[1], 'official job-title suffix (not a separate practice field)'
    return Vacancy(firm, card['job_id'], reference, title, location, card['url'],
                   practice or None, practice_source, extract_pqe(description), utc_now(),
                   is_london(location), card['category'], evidence), 'include', evidence


class HarbourCollector:
    def __init__(self, config, client, progress=lambda message: None):
        self.config, self.client, self.progress = config, client, progress

    def listings(self, first_html, filters=None):
        config = self.config
        pending, visited, cards = {1}, set(), {}
        errors = []
        location_id = None
        while pending:
            page = min(pending)
            pending.remove(page)
            if page in visited:
                continue
            if page < 1 or page > config.max_pages:
                errors.append('Pagination exceeded configured safety limit')
                break
            url = config.board_url if page == 1 else urljoin(config.board_url, f'page/{page}/')
            if filters:
                url += '?' + urlencode(filters)
            try:
                html = first_html if page == 1 else self.client.get(url)
                root, found, pages, current = parse_board(html, url)
                if current != page:
                    raise ParseError(f'Requested page {page}, received page {current}')
                if page == 1:
                    selects = root.find('select', id=config.location_field)
                    options = [n for select in selects for n in select.find('option')
                               if n.text().casefold() == config.location_name.casefold()]
                    if len(options) != 1 or not options[0].attrs.get('value'):
                        raise ParseError('Official London location option missing or ambiguous')
                    location_id = options[0].attrs['value']
                for card in found:
                    if card['job_id'] in cards:
                        raise ParseError('Repeated ID across pages (pagination drift or ignored page)')
                    cards[card['job_id']] = card
                visited.add(page)
                pending.update(pages - visited)
            except (FetchError, ParseError) as exc:
                errors.append(str(exc))
        if visited and visited != set(range(1, max(visited)+1)):
            errors.append('Non-contiguous pagination')
        return cards, location_id, len(visited), errors

    def collect(self):
        config = self.config
        result = ScanResult(config.firm, config.board_url)
        self.progress('Reading complete official board and pagination…')
        try:
            html = self.client.get(config.board_url)
        except FetchError as exc:
            result.errors.append(str(exc))
            result.finished_at = utc_now()
            return result
        cards, location_id, pages, errors = self.listings(html)
        result.errors.extend(errors)
        full_complete = not errors
        london_complete = False
        london_pages = 0
        london_cards = {}
        if location_id:
            filters = {f'c[{config.location_field}]': location_id, 'submit': 'search'}
            london_url = config.board_url + '?' + urlencode(filters)
            try:
                london_html = self.client.get(london_url)
                london_cards, _, london_pages, london_errors = self.listings(london_html, filters)
                result.errors.extend(london_errors)
                expected = {key for key, card in cards.items() if is_london(card['location'])}
                if set(london_cards) != expected or any(not is_london(c['location']) for c in london_cards.values()):
                    result.errors.append('Official London filter and full-board locations disagree; board may have changed')
                else:
                    london_complete = not london_errors and full_complete
                for key, card in london_cards.items():
                    cards.setdefault(key, card)
            except FetchError as exc:
                result.errors.append(str(exc))
        details = 0
        for card in cards.values():
            summary = dict(card)
            title, category = card['title'], card['category']
            if category == 'training_and_apprenticeships' or SUPPORT.search(title):
                result.excluded.append({**summary, 'reason': 'Training or non-qualified support role title/category'})
                continue
            if category == 'business_professionals' and not lawyer_title(title, category):
                result.excluded.append({**summary, 'reason': 'Official business-professionals category, no lawyer title'})
                continue
            self.progress(f"Checking {card['job_id']}: {title}")
            try:
                advert = self.client.get(card['url'])
                vacancy, decision, reason = parse_advert(advert, card, config.firm)
                details += 1
                if vacancy:
                    result.vacancies.append(vacancy)
                elif decision == 'exclude':
                    result.excluded.append({**summary, 'reason': reason})
                else:
                    result.review.append({**summary, 'reason': reason})
            except (FetchError, ParseError) as exc:
                result.errors.append(f"Job {card['job_id']}: {exc}")
        result.coverage = dict(board_complete=full_complete, board_pages=pages,
                               board_vacancies=len(cards), london_filter_complete=london_complete,
                               london_filter_pages=london_pages, london_filter_vacancies=len(london_cards),
                               london_filter_value=location_id, adverts_checked=details,
                               http_requests=self.client.requests)
        if result.errors:
            result.status = 'PARTIAL' if cards else 'BLOCKED'
        elif result.review:
            result.status = 'LIMITED'
        else:
            result.status = 'SUCCESS'
        result.vacancies.sort(key=lambda v: (not v.london, v.title.casefold(), v.job_id))
        result.finished_at = utc_now()
        return result
