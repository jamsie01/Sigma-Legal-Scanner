"""Conservative shared extraction: only vacancy-specific fields count as office evidence."""
import json
import re
from collectors.html import Tree
from collectors.harbour import job_postings


def explicit_location(html):
    root = Tree(html).root
    locations = []
    for script in root.find('script'):
        if script.attrs.get('type') != 'application/ld+json':
            continue
        try:
            postings = list(job_postings(json.loads(script.raw())))
        except (ValueError, TypeError):
            continue
        for post in postings:
            entries = post.get('jobLocation', [])
            for entry in entries if isinstance(entries, list) else [entries]:
                if not isinstance(entry, dict):
                    continue
                address = entry.get('address', {})
                if isinstance(address, dict) and address.get('addressLocality'):
                    locations.append(address['addressLocality'])
    for node in root.find('dt'):
        if re.fullmatch(r'(?:office|location)s?\s*:?', node.text(), re.I) and node.parent:
            siblings = node.parent.children
            for following in siblings[siblings.index(node)+1:]:
                if isinstance(following, str):
                    continue
                if following.tag == 'dd':
                    locations.append(following.text())
                break
    return ', '.join(dict.fromkeys(locations)) or 'Unknown'


def practice_from_title(title):
    parts = re.split(r'\s+[-–—]\s+', title, maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else None
