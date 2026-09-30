"""Explicitly incomplete sources; loading a careers page never proves zero jobs."""
from dataclasses import dataclass
from collectors.http import FetchError
from models import ScanResult, utc_now


@dataclass(frozen=True)
class PendingConfig:
    firm: str
    board_url: str
    reason: str


class PendingCollector:
    def __init__(self, config, client, progress=lambda _: None):
        self.config, self.client = config, client

    def collect(self):
        r = ScanResult(self.config.firm, self.config.board_url)
        try:
            self.client.get(self.config.board_url)
            r.status = 'LIMITED'
            r.review.append(dict(job_id='source-review', title='Source coverage', location='Unknown',
                                 url=self.config.board_url, reason=self.config.reason))
        except FetchError as exc:
            r.errors.append(str(exc))
        r.coverage = dict(board_complete=False, note=self.config.reason)
        r.finished_at = utc_now()
        return r
