"""Firm configurations and collector construction. Stable keys preserve history."""
from urllib.parse import urlparse
from collectors.pending import PendingConfig, PendingCollector
from collectors.harbour import HarbourCollector, HarbourConfig
from collectors.workday import WorkdayCollector, WorkdayConfig
from collectors.eploy import EployCollector, EployConfig
from collectors.hfw import HfwCollector, HfwConfig
from collectors.withers import WithersCollector, WithersConfig
from collectors.fladgate import FladgateCollector, FladgateConfig
from collectors.stewarts import StewartsCollector, StewartsConfig
from collectors.hausfeld import HausfeldCollector, HausfeldConfig
from collectors.contact_only import ContactOnlyCollector, ContactOnlyConfig
from collectors.allhires import AllHiresCollector, AllHiresConfig
from collectors.icims import IcimsCollector, IcimsConfig
from collectors.cvmail import CvmailCollector, CvmailConfig
from collectors.taylorwessing import TaylorWessingCollector, TaylorWessingConfig
from collectors.mofo import MofoCollector, MofoConfig
from collectors.http import HttpClient
# 20 Official Law Firm Careers Boards & ATS Configurations
FIRMS = {
    'tlt': HarbourConfig('TLT', 'https://apply.tlt.com/vacancies/', 'field_4811'),
    'squire-patton-boggs': CvmailConfig('Squire Patton Boggs', 'https://fsr.cvmailuk.com/spb/main.cfm?srxksl=1'),
    'taylor-wessing': TaylorWessingConfig('Taylor Wessing', 'https://careers.winstontaylor-emea.com/Careeropportunities/go/Career-opportunities/9053755/'),
    'fieldfisher': EployConfig('Fieldfisher', 'https://fieldfisher.current-vacancies.com/Careers/Fieldfisher%20Vacancy%20Search%20Page-2074'),
    'hfw': HfwConfig('HFW', 'https://www.hfw.com/careers/vacancies/'),
    'lewis-silkin': AllHiresConfig('Lewis Silkin', 'https://lewissilkin.allhires.com/'),
    'withers': WithersConfig('Withers', 'https://www.witherscareers.com/'),
    'fladgate': FladgateConfig('Fladgate', 'https://www.fladgate.com/careers'),
    'stewarts': StewartsConfig('Stewarts', 'https://www.stewartslaw.com/careers/vacancies/'),
    'hausfeld': HausfeldConfig('Hausfeld', 'https://www.hausfeld.com/en-gb/join-us/open-positions'),
    'kirkland-ellis': CvmailConfig('Kirkland & Ellis', 'https://fsr.cvmailuk.com/kirkland/main.cfm?page=jobBoard&fo=1&groupType_8=3011&groupType_4=&groupType_3=&filter'),
    'latham-watkins': IcimsConfig('Latham & Watkins', 'https://uk-associatecareers-lw.icims.com/jobs/search?ss=1&in_iframe=1'),
    'simpson-thacher': WorkdayConfig('Simpson Thacher', 'https://stblaw.wd1.myworkdayjobs.com/wday/cxs/stblaw/careers'),
    'paul-weiss': ContactOnlyConfig('Paul, Weiss', 'https://www.paulweiss.com/careers/laterals-judicial-clerks', 'LegalHiringUK@paulweiss.com'),
    'milbank': AllHiresConfig('Milbank', 'https://milbank.allhires.com/'),
    'davis-polk': PendingConfig('Davis Polk', 'https://www.davispolk.com/careers/laterals-clerks', 'Lawyer recruitment source verified. Embedded open-position listing requires integration; London coverage not established. Contact londonrecruiting@davispolk.com.'),
    'cooley': WorkdayConfig('Cooley UK', 'https://cooley.wd1.myworkdayjobs.com/wday/cxs/cooley/Cooley_UK_LLP'),
    'morrison-foerster': MofoConfig('Morrison Foerster', 'https://mofo.career.page/api/jobs'),
    'paul-hastings': PendingConfig('Paul Hastings', 'https://paulhastingsselfapply.viglobalcloud.com/viRecruitSelfApply/RecDefault.aspx?FilterREID=44', 'Official experienced-lawyer board found. Its application links use form postbacks; stable direct advert links and London coverage require verification.'),
    'quinn-emanuel': ContactOnlyConfig('Quinn Emanuel', 'https://www.quinnemanuel.com/careers/recruiting/recruiting-contacts/', 'londonrecruitment@quinnemanuel.com')
}


COLLECTORS = {
    PendingConfig: PendingCollector,
    HarbourConfig: HarbourCollector, WorkdayConfig: WorkdayCollector,
    EployConfig: EployCollector, HfwConfig: HfwCollector,
    WithersConfig: WithersCollector, FladgateConfig: FladgateCollector,
    StewartsConfig: StewartsCollector, HausfeldConfig: HausfeldCollector,
    ContactOnlyConfig: ContactOnlyCollector, AllHiresConfig: AllHiresCollector,
    IcimsConfig: IcimsCollector, CvmailConfig: CvmailCollector,
    TaylorWessingConfig: TaylorWessingCollector, MofoConfig: MofoCollector,
}


def source_url(config):
    for field in ('board_url', 'base_url', 'careers_url', 'api_url'):
        if hasattr(config, field):
            return getattr(config, field)
    raise ValueError('Missing source URL')


def make_collector(config, progress=lambda _: None):
    factory = COLLECTORS[type(config)]
    if hasattr(config, 'board_url'):
        return factory(config, HttpClient(urlparse(config.board_url).hostname), progress)
    return factory(config, progress)


SOURCE_NOTES = {
    'taylor-wessing': 'Winston Taylor EMEA (legacy Taylor Wessing UK). Verified official careers link on 2026-09-30.',
}
