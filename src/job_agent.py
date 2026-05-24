"""
Job Agent - Auto applies to Software/Tech roles on Naukri & LinkedIn
Uses Groq API (FREE) | Alerts via Telegram | Monitors Gmail
"""

import os
import json
import time
import logging
import requests
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama3-70b-8192"

# ── Groq AI Call ──────────────────────────────────────────────────────────────
def groq_chat(prompt: str, max_tokens: int = 400) -> str:
    prompt = prompt[:1500]  # hard cap to avoid 400 errors
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": GROQ_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}]
    }
    try:
        resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)
        if resp.status_code == 400:
            logger.error(f"Groq 400 error: {resp.text[:200]}")
            return ""
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return ""

# ── Telegram ──────────────────────────────────────────────────────────────────
def send_telegram(message: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.warning("Telegram not configured")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}, timeout=10)
        logger.info("Telegram sent.")
    except Exception as e:
        logger.error(f"Telegram error: {e}")

# ── Cover Letter ──────────────────────────────────────────────────────────────
def generate_cover_letter(job: dict, resume_summary: str) -> str:
    prompt = f"""Write a short 3-paragraph job cover letter.
Role: {job['title'][:80]}
Company: {job['company'][:80]}
Job Info: {job['description'][:200]}
About me: {resume_summary[:300]}
Output only the cover letter text, under 150 words."""
    return groq_chat(prompt, max_tokens=300)

# ── Job Relevance Filter ──────────────────────────────────────────────────────
def is_job_relevant(job: dict, preferences: dict) -> bool:
    prompt = f"""Does this job match the candidate? Reply YES or NO only.
Job: {job['title'][:80]}
Skills needed: {str(job.get('skills',''))[:150]}
Candidate wants: {preferences['role_type']} roles, skills: {', '.join(preferences['skills'][:5])}
Avoid: {preferences.get('avoid','')}"""
    result = groq_chat(prompt, max_tokens=5)
    return result.upper().startswith("YES")

# ── Naukri Scraper ────────────────────────────────────────────────────────────
def scrape_naukri_jobs(keywords: list) -> list:
    jobs = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "systemid": "Naukri",
        "appid": "109"
    }
    for keyword in keywords:
        try:
            url = f"https://www.naukri.com/jobapi/v3/search?noOfResults=10&urlType=search_by_keyword&searchType=adv&keyword={keyword}&experience=0&pageNo=1"
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                for j in resp.json().get("jobDetails", []):
                    jobs.append({
                        "id": str(j.get("jobId", "")),
                        "title": j.get("title", "")[:100],
                        "company": j.get("companyName", "")[:100],
                        "description": j.get("jobDescription", "")[:300],
                        "skills": str(j.get("tagsAndSkills", ""))[:150],
                        "location": j.get("placeholders", [{}])[0].get("label", ""),
                        "apply_url": f"https://www.naukri.com{j.get('jdURL', '')}",
                        "source": "naukri"
                    })
            time.sleep(2)
        except Exception as e:
            logger.error(f"Naukri error [{keyword}]: {e}")
    return jobs

# ── LinkedIn Fetcher ──────────────────────────────────────────────────────────
def fetch_linkedin_jobs(keywords: list) -> list:
    jobs = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    for keyword in keywords:
        try:
            url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={keyword}&location=India&start=0"
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")
                for card in soup.find_all("li")[:8]:
                    try:
                        title = card.find("h3").text.strip() if card.find("h3") else ""
                        company = card.find("h4").text.strip() if card.find("h4") else ""
                        job_div = card.find("div", {"data-entity-urn": True})
                        link = f"https://www.linkedin.com/jobs/view/{job_div['data-entity-urn'].split(':')[-1]}/" if job_div else ""
                        if title and link:
                            jobs.append({
                                "id": link,
                                "title": title[:100],
                                "company": company[:100],
                                "description": title[:200],
                                "skills": "",
                                "location": "India",
                                "apply_url": link,
                                "source": "linkedin"
                            })
                    except Exception:
                        continue
            time.sleep(2)
        except Exception as e:
            logger.error(f"LinkedIn error [{keyword}]: {e}")
    return jobs

# ── Applied Jobs Tracker ──────────────────────────────────────────────────────
def load_applied_jobs() -> set:
    try:
        with open("applied_jobs.json", "r") as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()

def save_applied_job(job_id: str):
    applied = load_applied_jobs()
    applied.add(job_id)
    with open("applied_jobs.json", "w") as f:
        json.dump(list(applied), f)

# ── Naukri Apply ──────────────────────────────────────────────────────────────
def apply_naukri(job: dict, cover_letter: str, config: dict) -> bool:
    session = requests.Session()
    headers = {"Content-Type": "application/json", "appid": "109", "systemid": "Naukri"}
    try:
        login = session.post(
            "https://www.naukri.com/central-login-services/v1/login",
            json={"username": config["naukri_email"], "password": config["naukri_password"], "type": "login"},
            headers=headers, timeout=15
        )
        if login.status_code != 200:
            logger.error(f"Naukri login failed: {login.status_code}")
            return False
        apply = session.post(
            f"https://www.naukri.com/jobapi/v4/job/{job['id']}/apply",
            json={"coverletter": cover_letter, "applysource": "NAUKRI"},
            headers=headers, timeout=15
        )
        return apply.status_code in [200, 201]
    except Exception as e:
        logger.error(f"Naukri apply error: {e}")
        return False

# ── Gmail Monitor ─────────────────────────────────────────────────────────────
def check_gmail_for_replies() -> list:
    creds_data = json.loads(os.environ.get("GMAIL_CREDENTIALS", "{}"))
    if not creds_data:
        logger.info("Gmail not configured, skipping.")
        return []
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        creds = Credentials(
            token=creds_data.get("token"),
            refresh_token=creds_data.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=creds_data.get("client_id"),
            client_secret=creds_data.get("client_secret")
        )
        service = build("gmail", "v1", credentials=creds)
        since = (datetime.now() - timedelta(hours=1)).strftime("%Y/%m/%d")
        query = f"after:{since} (subject:interview OR subject:hired OR subject:offer OR subject:shortlisted OR subject:selected OR subject:application)"
        results = service.users().messages().list(userId="me", q=query).execute()
        alerts = []
        for msg in results.get("messages", [])[:5]:
            data = service.users().messages().get(userId="me", id=msg["id"], format="full").execute()
            h = {x["name"]: x["value"] for x in data["payload"]["headers"]}
            alerts.append({
                "from": h.get("From", "Unknown"),
                "subject": h.get("Subject", "No subject"),
                "date": h.get("Date", "")
            })
        return alerts
    except Exception as e:
        logger.error(f"Gmail error: {e}")
        return []

# ── Main Pipeline ─────────────────────────────────────────────────────────────
def run_pipeline():
    start_time = datetime.now()
    logger.info("🚀 Job Agent starting...")

    config = {
        "naukri_email": os.environ.get("NAUKRI_EMAIL", ""),
        "naukri_password": os.environ.get("NAUKRI_PASSWORD", ""),
    }

    preferences = {
        "role_type": "Software/Tech",
        "skills": ["Python", "JavaScript", "React", "Node.js", "LangChain", "MongoDB"],
        "experience_level": "Fresher to 2 years",
        "avoid": "Sales, BPO, non-tech, hardware"
    }

    resume_summary = os.environ.get("RESUME_SUMMARY",
        "B.Tech CS student skilled in Python, Node.js, React, LangChain, MongoDB. "
        "Built full-stack apps and AI agents. Looking for software/full-stack/AI roles."
    )

    keywords = ["software developer", "python developer", "full stack developer", "react developer", "AI engineer"]

    # Track stats
    stats = {
        "scanned": 0,
        "already_applied": 0,
        "irrelevant": 0,
        "applied_naukri": 0,
        "linkedin_found": 0,
        "cover_fail": 0,
        "apply_fail": 0,
        "applied_jobs_list": []
    }

    # 1. Scrape
    logger.info("Scraping Naukri...")
    naukri_jobs = scrape_naukri_jobs(keywords)
    logger.info("Fetching LinkedIn...")
    linkedin_jobs = fetch_linkedin_jobs(keywords)
    all_jobs = naukri_jobs + linkedin_jobs
    stats["scanned"] = len(all_jobs)
    logger.info(f"Total found: {len(all_jobs)}")

    applied_jobs = load_applied_jobs()

    # 2. Filter & Apply
    for job in all_jobs:
        job_id = job["id"] or job["apply_url"]

        if job_id in applied_jobs:
            stats["already_applied"] += 1
            continue

        if not is_job_relevant(job, preferences):
            stats["irrelevant"] += 1
            logger.info(f"Irrelevant: {job['title']} @ {job['company']}")
            continue

        if job["source"] == "linkedin":
            stats["linkedin_found"] += 1
            send_telegram(
                f"🔔 *LinkedIn Job Found*\n"
                f"*Role:* {job['title']}\n"
                f"*Company:* {job['company']}\n"
                f"[Apply Now ↗]({job['apply_url']})"
            )
            save_applied_job(job_id)
            continue

        # Naukri — generate cover letter and apply
        cover_letter = generate_cover_letter(job, resume_summary)
        if not cover_letter:
            stats["cover_fail"] += 1
            continue

        success = apply_naukri(job, cover_letter, config)
        if success:
            save_applied_job(job_id)
            stats["applied_naukri"] += 1
            stats["applied_jobs_list"].append(f"• {job['title']} @ {job['company']}")
            send_telegram(
                f"✅ *Auto-Applied on Naukri!*\n"
                f"*Role:* {job['title']}\n"
                f"*Company:* {job['company']}\n"
                f"*Location:* {job.get('location','N/A')}\n"
                f"[View Job]({job['apply_url']})"
            )
            time.sleep(4)
        else:
            stats["apply_fail"] += 1

    # 3. Gmail check
    replies = check_gmail_for_replies()
    for reply in replies:
        send_telegram(
            f"📬 *Hiring Email Received!*\n"
            f"*From:* {reply['from']}\n"
            f"*Subject:* {reply['subject']}\n"
            f"⚡ Open Gmail and respond now!"
        )

    # 4. Detailed Summary to Telegram
    duration = round((datetime.now() - start_time).seconds / 60, 1)
    jobs_list_text = "\n".join(stats["applied_jobs_list"]) if stats["applied_jobs_list"] else "None this run"

    summary = (
        f"📊 *Job Agent — Run Report*\n"
        f"🕐 {start_time.strftime('%d %b %Y, %I:%M %p')}\n"
        f"⏱ Duration: {duration} min\n\n"
        f"🔍 *Scanned:* {stats['scanned']} jobs\n"
        f"⏭ Already applied: {stats['already_applied']}\n"
        f"❌ Irrelevant (AI filtered): {stats['irrelevant']}\n\n"
        f"✅ *Auto-applied (Naukri):* {stats['applied_naukri']}\n"
        f"🔗 *LinkedIn jobs sent to you:* {stats['linkedin_found']}\n"
        f"📬 *Hiring emails found:* {len(replies)}\n\n"
        f"⚠️ Cover letter fails: {stats['cover_fail']}\n"
        f"⚠️ Apply fails: {stats['apply_fail']}\n\n"
        f"*Jobs applied this run:*\n{jobs_list_text}"
    )
    send_telegram(summary)
    logger.info("Pipeline complete.")

if __name__ == "__main__":
    run_pipeline()
