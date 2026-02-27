import httpx
from typing import Optional, List
from models import JobResult


async def search_themuse(client, query, location, limit):
    params = {"page": 1, "descending": "true"}
    if query:
        params["query"] = query
    if location:
        params["location"] = location
    resp = await client.get("https://www.themuse.com/api/public/jobs", params=params)
    resp.raise_for_status()
    data = resp.json()
    jobs = []
    for item in data.get("results", [])[:limit]:
        locations = item.get("locations", [])
        loc_str = ", ".join(l.get("name", "") for l in locations) if locations else None
        is_remote = any("remote" in l.get("name", "").lower() for l in locations)
        categories = item.get("categories", [])
        jobs.append(JobResult(
            id=f"themuse-{item.get('id', '')}",
            title=item.get("name", "N/A"),
            company=item.get("company", {}).get("name", "Unknown"),
            location=loc_str,
            is_remote=is_remote,
            job_type=item.get("levels", [{}])[0].get("name") if item.get("levels") else None,
            category=categories[0].get("name") if categories else None,
            description=(item.get("contents", "")[:500]) if item.get("contents") else None,
            url=item.get("refs", {}).get("landing_page", ""),
            posted_at=item.get("publication_date", ""),
            source="themuse",
        ))
    return jobs
