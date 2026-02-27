# 🔍 JobHunter API
### Free Replacement for Paid Job APIs (Active Jobs DB, JSearch, Job Posting Feed)

Built with **FastAPI** + free public APIs — no more monthly bills!

## 🆓 Free Data Sources

| Source | Key Required? | Free Limit |
|--------|--------------|------------|
| **Remotive** | ❌ No key needed | Unlimited |
| **The Muse** | ❌ No key needed | Unlimited |
| **Adzuna** | ✅ Free key | 250 req/day |
| **Reed** | ✅ Free key | 1000 req/month |

## 🚀 Quick Start

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Open **http://localhost:8000/docs** for interactive Swagger UI.

## 🔑 Get Free API Keys
- **Adzuna**: https://developer.adzuna.com/
- **Reed**: https://www.reed.co.uk/developers/jobseeker

## 📡 Example Requests

```bash
# No key needed!
curl "http://localhost:8000/jobs/remote?query=python"

# With Adzuna key
curl "http://localhost:8000/jobs/adzuna?query=backend&app_id=YOUR_ID&app_key=YOUR_KEY"
```
