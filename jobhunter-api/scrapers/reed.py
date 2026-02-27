import httpx
import base64
from typing import Optional, List
from models import JobResult


async def search_reed(client, query, location, limit, api_key):
    token = base64.b64encode(f"{api_key}:".encode()).decode()
    params = {"keywords": query, "resultsToTake": min(limit, 100)}
    if location:
        params["locationName"] = location
    resp = await client.get(
        "https://www.reed.co.uk/api/1.0/search",
        params=params,
        headers={"Authorization": f"Basic {token}"}
    )
    resp.raise_for_status()
    data = resp.json()
    jobs = []
    for item in data.get("results", []):
        sal_min = item.get("minimumSalary")
        sal_max = item.get("maximumSalary")
        sal_display = f"£{sal_min:,.0f} - £{sal_max:,.0f}" if sal_min and sal_max else None
        jobs.append(JobResult(
            id=f"reed-{item.get('jobId', '')}",
            title=item.get("jobTitle", "N/A"),
            company=item.get("employerName", "Unknown"),
            location=item.get("locationName"),
            is_remote="remote" in (item.get("locationName", "") or "").lower(),
            salary_min=sal_min,
            salary_max=sal_max,
            salary_currency="GBP",
            salary_display=sal_display,
            job_type=item.get("contractType"),
            description=item.get("jobDescription", "")[:500],
            url=item.get("jobUrl", ""),
            posted_at=item.get("date", ""),
            source="reed",
        ))
    return jobs
