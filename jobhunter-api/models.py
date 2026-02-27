from pydantic import BaseModel
from typing import Optional, List, Dict


class JobResult(BaseModel):
    id: str
    title: str
    company: str
    location: Optional[str] = None
    is_remote: bool = False
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    salary_display: Optional[str] = None
    job_type: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    url: str
    posted_at: Optional[str] = None
    source: str


class SearchResponse(BaseModel):
    query: str
    location: Optional[str] = None
    total: int
    sources_used: Dict[str, int]
    errors: Optional[List[str]] = None
    jobs: List[JobResult]
    fetched_at: str
