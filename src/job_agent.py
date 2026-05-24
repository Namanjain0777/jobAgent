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
    prompt = prompt[:1500]
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
            logger.error(f"Groq 400: {resp.text[:200]}")
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

# ── Cover Letter (with fallback) ──────────────────────────────────────────────
def generate_cover_letter(job: dict, resume_summary: str) -> str:
    prompt = f"""Write a short 3-paragraph job cover letter.
Role: {job['title'][:80]}
Company: {job['company'][:80]}
About me: {resume_summary[:250]}
Output only the cover letter text, under 150 words."""
    result = groq_chat(prompt, max_tokens=300)

    if not result:
        # Fallback hardcoded cover letter — never fails
        result = (
            f"I am excited to apply for the {job['title']} position at {job['company']}. "
            f"As a B.Tech Computer Science student at NIIT University, I have built production-grade "
            f"applications using Python, Node.js, React, MongoDB, and LangChain AI agents.\n\n"
            f"My projects include a full-stack finance platform, an AI-powered WhatsApp tax assistant, "
            f"and an inventory management system — all built with SOLID principles and clean architecture. "
            f"I have strong experience in REST APIs, JWT auth, and third-party integrations.\n\n"
            f"I am eager to contribute and grow with your team. "
            f"Thank you for considering my application."
        )
        logger.info(f"Using fallback cover letter for: {job['title']}")
    return result

# ── Job Relevance Filter ──────────────────────────────────────────────────────
def is_job_relevant(job: dict) -> bool:
    title = job.get('title', '').lower()
    skills = str(job.get('skills', '')).lower()
    description = job.get('description', '').lower()

    # Hard reject by title
    reject_keywords = ['sales', 'bpo', 'telecaller', 'accountant', 'hardware',
                       'civil', 'mechanical', 'teacher', 'nurse', 'driver', 'field executive']
    for kw in reject_keywords:
        if kw in title:
            logger.info(f"Hard rejected: {job['title']}")
            return False

    # Auto approve by title — most common tech keywords
    approve_keywords = ['software', 'developer', 'engineer', 'python', 'react',
                        'node', 'full stack', 'fullstack', 'backend', 'frontend',
                        'web', 'ai', 'ml', 'data', 'java', 'javascript', 'tech',
                        'intern', 'programmer', 'devops', 'cloud', 'analyst', 'langchain']
    for kw in approve_keywords:
        if kw in title:
            logger.info(f"Auto-approved: {job['title']}")
            return True

    # Empty description — approve by default
    combined = (skills + description).strip()
    if len(combined) < 50:
        logger.info(f"Auto-approved (empty desc): {job['title']}")
        return True

    # Groq as last resort for ambiguous titles
    prompt = f"""Does this job suit a software/tech fresher? Reply YES or NO only.
Job title: {title[:80]}
Skills: {skills[:100]}"""
    result = groq_chat(prompt, max_tokens=5)
    approved = result.upper().startswith("YES")
    logger.info(f"Groq says {'YES' if approved else 'NO'}: {job['title']}")
    return approved

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
    headers = {
        "Content-Type": "application/json",
        "appid": "109",
        "systemid": "Naukri",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        # Login
        login = session.post(
            "https://www.naukri.com/central-login-services/v1/login",
            json={"username": config["naukri_email"], "password": config["naukri_password"], "type": "login"},
            headers=headers, timeout=15
        )
        logger.info(f"Naukri login status: {login.status_code} | response: {login.text[:200]}")

        if login.status_code != 200:
            logger.error(f"Naukri login failed: {login.status_code} - {login.text[:300]}")
            return False

        # Apply
        apply = session.post(
            f"https://www.naukri.com/jobapi/v4/job/{job['id']}/apply",
            json={"coverletter": cover_letter, "applysource": "NAUKRI"},
            headers=headers, timeout=15
        )
        logger.info(f"Naukri apply status: {apply.status_code} | response: {apply.text[:200]}")
        return apply.status_code in [200, 201]

    except Exception as e:
        logger.error(f"Naukri apply exception: {e}")
        return False

# ── Gmail Monitor ─────────────────────────────────────────────────────────────
def check_gmail_for_replies() -> list:
<<<<<<< HEAD
    creds_data = json.loads(os.environ.get("GMAIL_CREDENTIALS", "{}"))
=======
    raw = os.environ.get("GMAIL_CREDENTIALS", "").strip()
    if not raw:
        logger.info("Gmail credentials not set, skipping.")
        return []
    try:
        creds_data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("GMAIL_CREDENTIALS invalid JSON, skipping.")
        return []
>>>>>>> cd03bfb (Fix Error)
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
    logger.info("Job Agent starting...")

    config = {
        "naukri_email": os.environ.get("NAUKRI_EMAIL", ""),
        "naukri_password": os.environ.get("NAUKRI_PASSWORD", ""),
    }

    resume_summary = os.environ.get("RESUME_SUMMARY",
        "B.Tech CS student at NIIT University. Skills: Python, Node.js, React, MongoDB, LangChain, AI agents. "
        "Built SmartBudget finance app, GharKaCA WhatsApp AI assistant, SmartShelf inventory system. "
        "Looking for software developer, full-stack, or AI engineer roles."
    )

    keywords = ["software developer", "python developer", "full stack developer", "react developer", "AI engineer"]

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

        if not is_job_relevant(job):
            stats["irrelevant"] += 1
            continue

        if job["source"] == "linkedin":
            stats["linkedin_found"] += 1
            save_applied_job(job_id)
            send_telegram(
                f"🔔 *LinkedIn Job — Apply Now*\n"
                f"*Role:* {job['title']}\n"
                f"*Company:* {job['company']}\n"
                f"[Apply Here]({job['apply_url']})"
            )
            continue

        # Naukri — cover letter + apply
        cover_letter = generate_cover_letter(job, resume_summary)
        # cover_letter always returns something now (fallback template)

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
            logger.error(f"Apply failed for: {job['title']} @ {job['company']} | Job ID: {job['id']}")

    # 3. Gmail
    replies = check_gmail_for_replies()
    for reply in replies:
        send_telegram(
            f"📬 *Hiring Email!*\n"
            f"*From:* {reply['from']}\n"
            f"*Subject:* {reply['subject']}\n"
            f"⚡ Check Gmail now!"
        )

    # 4. Detailed summary
    duration = round((datetime.now() - start_time).seconds / 60, 1)
    jobs_list_text = "\n".join(stats["applied_jobs_list"]) if stats["applied_jobs_list"] else "None this run"

    summary = (
        f"📊 *Job Agent Report*\n"
        f"🕐 {start_time.strftime('%d %b %Y, %I:%M %p')}\n"
        f"⏱ Duration: {duration} min\n\n"
        f"🔍 Scanned: {stats['scanned']} jobs\n"
        f"⏭ Already applied: {stats['already_applied']}\n"
        f"❌ Irrelevant: {stats['irrelevant']}\n\n"
        f"✅ *Auto-applied Naukri:* {stats['applied_naukri']}\n"
        f"🔗 *LinkedIn sent to you:* {stats['linkedin_found']}\n"
        f"📬 *Hiring emails:* {len(replies)}\n"
        f"⚠️ Apply failed: {stats['apply_fail']}\n\n"
        f"*Applied this run:*\n{jobs_list_text}"
    )
    send_telegram(summary)
    logger.info("Pipeline complete.")

if __name__ == "__main__":
    run_pipeline()
