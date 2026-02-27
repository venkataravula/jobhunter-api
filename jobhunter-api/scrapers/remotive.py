import httpx
import re
from typing import Optional, List
from models import JobResult


async def search_remotive(client, query, location, limit):
    params = {"limit": limit}
    if query:
        params["search"] = query
    resp = await client.get("https://remotive.com/api/remote-jobs", params=params)
    resp.raise_for_status()
    data = resp.json()
    jobs = []
    for item in data.get("jobs", [])[:limit]:
        jobs.append(JobResult(
            id=f"remotive-{item['id']}",
            title=item.get("title", "N/A"),
            company=item.get("company_name", "Unknown"),
            location=item.get("candidate_required_location") or "Remote",
            is_remote=True,
            salary_display=item.get("salary") or None,
            job_type=item.get("job_type"),
            category=item.get("category"),
            description=re.sub('<.*?>', '', item.get("description", ""))[:500],
            url=item.get("url", ""),
            posted_at=item.get("publication_date", ""),
            source="remotive",
        ))
    return jobs
