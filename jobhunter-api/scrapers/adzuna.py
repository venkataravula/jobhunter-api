import httpx
from typing import Optional, List
from models import JobResult


async def search_adzuna(client, query, location, limit, app_id, app_key, country="us"):
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": min(limit, 50),
        "what": query,
        "content-type": "application/json",
        "sort_by": "date",
    }
    if location:
        params["where"] = location
    resp = await client.get(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1", params=params)
    resp.raise_for_status()
    data = resp.json()
    jobs = []
    for item in data.get("results", []):
        sal_min = item.get("salary_min")
        sal_max = item.get("salary_max")
        sal_display = f"${sal_min:,.0f} - ${sal_max:,.0f}" if sal_min and sal_max else None
        loc_str = item.get("location", {}).get("display_name")
        jobs.append(JobResult(
            id=f"adzuna-{item.get('id', '')}",
            title=item.get("title", "N/A"),
            company=item.get("company", {}).get("display_name", "Unknown"),
            location=loc_str,
            is_remote="remote" in (loc_str or "").lower(),
            salary_min=sal_min,
            salary_max=sal_max,
            salary_currency="USD" if country == "us" else "GBP",
            salary_display=sal_display,
            job_type=item.get("contract_type"),
            category=item.get("category", {}).get("label"),
            description=item.get("description", "")[:500],
            url=item.get("redirect_url", ""),
            posted_at=item.get("created", ""),
            source="adzuna",
        ))
    return jobs
