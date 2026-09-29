"""Data models for legal vacancy extraction."""

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass
class Vacancy:
    """Represents a qualified legal vacancy."""
    firm_name: str
    firm_slug: str
    job_title: str
    job_url: str
    location: str
    is_london: bool
    pqe_raw: Optional[str] = None
    pqe_min: Optional[int] = None
    pqe_max: Optional[int] = None
    summary: Optional[str] = None
    source_url: Optional[str] = None
    source_type: Optional[str] = None
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScanResult:
    """Results from scanning a law firm's career board."""
    firm_name: str
    firm_slug: str
    source_url: str
    total_found: int
    london_found: int
    vacancies: List[Vacancy]
    duration_seconds: float = 0.0
    error: Optional[str] = None
