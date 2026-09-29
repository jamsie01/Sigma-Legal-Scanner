from dataclasses import dataclass
from models import ScanResult, utc_now
from urllib.request import urlopen, Request
import urllib.error
import time

@dataclass(frozen=True)
class ContactOnlyConfig:
    firm: str
    careers_url: str
    contact_email: str

class ContactOnlyCollector:
    def __init__(self, config: ContactOnlyConfig, progress=lambda msg: None):
        self.config = config
        self.progress = progress

    def collect(self) -> ScanResult:
        result = ScanResult(self.config.firm, self.config.careers_url)
        self.progress(f"Verifying contact-only careers page for {self.config.firm}...")
        
        req = Request(self.config.careers_url, headers={
            'User-Agent': 'SigmaLegalSearch/0.1 (local vacancy checker)',
            'Accept': 'text/html'
        })
        
        try:
            with urlopen(req, timeout=20) as response:
                if response.status != 200:
                    result.errors.append(f"Unexpected HTTP {response.status}")
                # We just need to check the page loads
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            result.errors.append(f"Fetch failed: {e}")
            
        result.coverage = {
            'note': f'Firm does not publish individual vacancies. Contact: {self.config.contact_email}'
        }
        
        if result.errors:
            result.status = 'BLOCKED'
        else:
            result.status = 'LIMITED'
            result.review.append({
                'title': 'Contact Only',
                'location': 'N/A',
                'job_id': 'contact',
                'url': self.config.careers_url,
                'reason': f"No public job board. Vacancies by direct application only. Contact {self.config.contact_email}"
            })
            
        result.finished_at = utc_now()
        return result
