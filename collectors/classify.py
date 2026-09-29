"""Centralised role classification for Sigma Legal Scanner.

Every collector imports is_sigma_vacancy() from here so that exclusion
rules are defined in exactly one place. When Jamie or Ryan flags a
role that should be included or excluded, update the patterns below
and the corresponding tests in tests/test_classify.py.
"""
import re

# ── Early careers & non-qualified roles ──────────────────────────────
# Always exclude these even if they contain lawyer keywords
# (e.g. "Trainee Solicitor", "Summer Associate", "Paralegal / Legal Assistant").
NON_QUALIFIED = re.compile(
    r'\b('
    r'trainee|apprentic\w*|intern\w*|summer\s+associate|'
    r'paralegal|vacation\s+scheme|training\s+contract|'
    r'open\s+day|open\s+evening'
    r')\b', re.I)

# ── Internal / non-recruitment legal roles ───────────────────────────
# Knowledge management, risk, compliance, conflicts, OGC, general counsel,
# AI/innovation, etc. Sigma does not recruit for internal operational roles.
INTERNAL_ROLES = re.compile(
    r'\b('
    r'knowledge\s+(?:&?\s+innovation\s+)?(?:management\s+)?(?:lawyer|attorney|counsel|associate|officer|manager)|'
    r'knowledge\s+development|'
    r'professional\s+support\s+lawyer|\bPSL\b|'
    r'compliance\s+(?:lawyer|attorney|counsel|officer|manager|director|associate|advisor)|'
    r'conflicts?\s+(?:lawyer|attorney|counsel|officer|manager|analyst|associate)|'
    r'risk\s+(?:lawyer|attorney|counsel|officer|manager|associate|advisor)|'
    r'OGC\s+(?:senior\s+)?(?:lawyer|attorney)|office\s+of\s+general\s+counsel|'
    r'general\s+counsel|'
    r'content\s+(?:lawyer|attorney)|'
    r'legal\s+operations|legal\s+ops|'
    r'information\s+governance|records\s+management|'
    r'practice\s+development|'
    r'pricing\s+(?:lawyer|attorney|counsel|manager)|'
    r'innovation\s+(?:lawyer|attorney|counsel|manager)|'
    r'artificial\s+intelligence\s+(?:lawyer|attorney)|'
    r'data\s+protection\s+(?:manager|officer|lawyer)'
    r')\b', re.I)

# ── Business support / non-legal roles ───────────────────────────────
# Handles business services roles like "HR Business Partner", "BD Associate",
# "Partner Recruiting Manager", "Associate Development Manager", etc.
SUPPORT_ROLES = re.compile(
    r'\b('
    r'hr\b|human\s+resources|people\s+partner|talent|recruit\w*|'
    r'marketing|business\s+development|\bbd\b|'
    r'product\s+management|end\s+user|it\s+analyst|it\s+specialist|'
    r'accountant|accounting|audit\b|payroll|finance\s+business\s+partner|'
    r'business\s+partner|'
    r'partner\s+(?:recruiting|integration|talent)|'
    r'associate\s+(?:development|life)|'
    r'(?:integration|development)\s+manager|'
    r'coordinator|specialist|assistant|'
    r'secretar\w*|admin\w*|reception\w*|clerk|case\s+handler|'
    r'change\s+trainer|office\s+assistant'
    r')\b', re.I)

# ── Qualified-lawyer title keywords ──────────────────────────────────
LAWYER_TITLES = re.compile(
    r'\b(solicitor|lawyer|associate|partner|legal\s+director|counsel|barrister|attorney)\b', re.I)


def is_sigma_vacancy(title: str) -> bool:
    """Return True if the job title looks like a fee-earning qualified-lawyer
    vacancy that Sigma would recruit for.

    The order matters:
    1. Reject early careers / non-qualified legal roles (trainees, paralegals).
    2. Reject internal operational roles (knowledge, compliance, risk, conflicts, OGC).
    3. Reject business support / corporate services roles.
    4. Accept if the title contains a recognised qualified-lawyer keyword.
    """
    if not title:
        return False

    # Step 1 — early careers & non-qualified are never qualified fee-earners
    if NON_QUALIFIED.search(title):
        return False

    # Step 2 — internal legal roles are not recruitment vacancies for Sigma
    if INTERNAL_ROLES.search(title):
        return False

    # Step 3 — business services / support roles (e.g. HR Business Partner, BD Associate)
    if SUPPORT_ROLES.search(title):
        return False

    # Step 4 — must contain a recognized qualified lawyer title
    return bool(LAWYER_TITLES.search(title))
