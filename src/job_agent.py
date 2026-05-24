"""
Job Agent - Auto applies to Software/Tech roles on Naukri & LinkedIn
Monitors Gmail for replies and sends Telegram alerts
Uses Groq API (FREE) for AI cover letters and job filtering
"""

import os
import json
import time
import logging
import requests
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama3-70b-8192"  # Free, fast, very capable

# ── Groq AI Call ──────────────────────────────────────────────────────────────
def groq_chat(prompt: str, max_tokens: int = 500) -> str:
    # Trim prompt to max 2000 chars to avoid Groq 400 errors
    prompt = prompt[:2000]
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
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Groq API error: {e}")
        return ""

# ── Telegram Alert ────────────────────────────────────────────────────────────
def send_telegram(message: str):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"})
    if resp.status_code == 200:
        logger.info("Telegram alert sent.")
    else:
        logger.error(f"Telegram error: {resp.text}")

# ── AI Cover Letter Generator (Groq/Llama3 - FREE) ───────────────────────────
def generate_cover_letter(job: dict, resume_summary: str) -> str:
    prompt = f"""You are a professional job application assistant. Write a concise, tailored cover letter for this job.

Job Title: {job['title'][:100]}
Company: {job['company'][:100]}
Job Description: {job['description'][:400]}

Candidate Summary:
{resume_summary}

Write a 3-paragraph cover letter:
1. Opening - excitement about the role
2. Why you're a fit - match skills to job
3. Closing - call to action

Keep it under 200 words. Professional but human tone. Output only the cover letter, no extra commentary."""
    return groq_chat(prompt, max_tokens=400)

# ── AI Job Relevance Filter (Groq/Llama3 - FREE) ─────────────────────────────
def is_job_relevant(job: dict, preferences: dict) -> bool:
    prompt = f"""Evaluate if this job matches the candidate's preferences. Reply with ONLY the word YES or NO, nothing else.

Job Title: {job['title'][:100]}
Job Description: {job['description'][:300]}
Required Skills: {str(job.get('skills', 'Not specified'))[:200]}

Candidate Preferences:
- Role type: {preferences['role_type']}
- Skills: {', '.join(preferences['skills'])}
- Experience level: {preferences['experience_level']}
- Avoid: {preferences.get('avoid', 'None')}"""
    result = groq_chat(prompt, max_tokens=5)
    return result.upper().startswith("YES")

# ── Naukri Scraper ────────────────────────────────────────────────────────────
def scrape_naukri_jobs(keywords: list, location: str = "India") -> list:
    jobs = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "systemid": "Naukri",
        "appid": "109"
    }
    for keyword in keywords:
        try:
            url = f"https://www.naukri.com/jobapi/v3/search?noOfResults=20&urlType=search_by_keyword&searchType=adv&keyword={keyword}&location={location}&experience=0&pageNo=1"
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                for j in data.get("jobDetails", []):
                    jobs.append({
                        "id": j.get("jobId", ""),
                        "title": j.get("title", ""),
                        "company": j.get("companyName", ""),
                        "description": j.get("jobDescription", ""),
                        "skills": j.get("tagsAndSkills", ""),
                        "location": j.get("placeholders", [{}])[0].get("label", ""),
                        "apply_url": f"https://www.naukri.com{j.get('jdURL', '')}",
                        "source": "naukri"
                    })
            time.sleep(2)
        except Exception as e:
            logger.error(f"Naukri scrape error for {keyword}: {e}")
    return jobs

# ── LinkedIn Job Fetcher ──────────────────────────────────────────────────────
def fetch_linkedin_jobs(keywords: list, location: str = "India") -> list:
    jobs = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    for keyword in keywords:
        try:
            url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={keyword}&location={location}&start=0"
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")
                for card in soup.find_all("li")[:10]:
                    try:
                        title = card.find("h3").text.strip() if card.find("h3") else ""
                        company = card.find("h4").text.strip() if card.find("h4") else ""
                        job_id = card.find("div", {"data-entity-urn": True})
                        link = f"https://www.linkedin.com/jobs/view/{job_id['data-entity-urn'].split(':')[-1]}/" if job_id else ""
                        if title:
                            jobs.append({
                                "id": link,
                                "title": title,
                                "company": company,
                                "description": title,
                                "skills": "",
                                "location": location,
                                "apply_url": link,
                                "source": "linkedin"
                            })
                    except Exception:
                        continue
            time.sleep(3)
        except Exception as e:
            logger.error(f"LinkedIn fetch error for {keyword}: {e}")
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

# ── Naukri Auto Apply ─────────────────────────────────────────────────────────
def apply_naukri(job: dict, cover_letter: str, config: dict) -> bool:
    session = requests.Session()
    headers = {"Content-Type": "application/json", "appid": "109", "systemid": "Naukri"}
    try:
        login_resp = session.post(
            "https://www.naukri.com/central-login-services/v1/login",
            json={"username": config["naukri_email"], "password": config["naukri_password"], "type": "login"},
            headers=headers, timeout=15
        )
        if login_resp.status_code != 200:
            logger.error("Naukri login failed")
            return False

        apply_resp = session.post(
            f"https://www.naukri.com/jobapi/v4/job/{job['id']}/apply",
            json={"coverletter": cover_letter, "applysource": "NAUKRI"},
            headers=headers, timeout=15
        )
        if apply_resp.status_code in [200, 201]:
            logger.info(f"Applied to {job['title']} at {job['company']} on Naukri")
            return True
        else:
            logger.error(f"Naukri apply failed: {apply_resp.status_code}")
            return False
    except Exception as e:
        logger.error(f"Naukri apply error: {e}")
        return False

def apply_to_job(job: dict, cover_letter: str, config: dict) -> bool:
    if job["source"] == "naukri":
        return apply_naukri(job, cover_letter, config)
    return False  # LinkedIn needs Selenium (v2)

# ── Gmail Monitor ─────────────────────────────────────────────────────────────
def check_gmail_for_replies() -> list:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds_data = json.loads(os.environ.get("GMAIL_CREDENTIALS", "{}"))
    if not creds_data:
        return []
    try:
        creds = Credentials(
            token=creds_data.get("token"),
            refresh_token=creds_data.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=creds_data.get("client_id"),
            client_secret=creds_data.get("client_secret")
        )
        service = build("gmail", "v1", credentials=creds)
        since = (datetime.now() - timedelta(hours=24)).strftime("%Y/%m/%d")
        query = f"after:{since} (subject:interview OR subject:hired OR subject:offer OR subject:shortlisted OR subject:selected)"
        results = service.users().messages().list(userId="me", q=query).execute()
        alerts = []
        for msg in results.get("messages", [])[:5]:
            msg_data = service.users().messages().get(userId="me", id=msg["id"], format="full").execute()
            h = {x["name"]: x["value"] for x in msg_data["payload"]["headers"]}
            alerts.append({"from": h.get("From", ""), "subject": h.get("Subject", ""), "date": h.get("Date", "")})
        return alerts
    except Exception as e:
        logger.error(f"Gmail check error: {e}")
        return []

# ── Main Pipeline ─────────────────────────────────────────────────────────────
def run_pipeline():
    logger.info("🚀 Job Agent pipeline starting... (Powered by Groq - FREE)")

    config = {
        "naukri_email": os.environ.get("NAUKRI_EMAIL", ""),
        "naukri_password": os.environ.get("NAUKRI_PASSWORD", ""),
    }

    preferences = {
        "role_type": "Software/Tech",
        "skills": ["Python", "JavaScript", "React", "Node.js", "Java", "SQL"],
        "experience_level": "Fresher to 3 years",
        "avoid": "Sales, BPO, non-tech"
    }

    resume_summary = os.environ.get("RESUME_SUMMARY", """
    Recent CS graduate with skills in Python, JavaScript, React, and Node.js.
    Built several projects including a web app and REST APIs.
    Looking for software developer / full-stack roles.
    Strong problem-solving skills, eager to learn and contribute.
    """)

    keywords = ["software developer", "python developer", "full stack developer", "junior developer", "react developer"]

    # 1. Scrape jobs
    naukri_jobs = scrape_naukri_jobs(keywords)
    linkedin_jobs = fetch_linkedin_jobs(keywords)
    all_jobs = naukri_jobs + linkedin_jobs
    logger.info(f"Total jobs found: {len(all_jobs)}")

    # 2. Filter & Apply
    applied_jobs = load_applied_jobs()
    applied_count = 0

    for job in all_jobs:
        job_id = job["id"] or job["apply_url"]
        if job_id in applied_jobs:
            continue
        # AI relevance check
        relevant = is_job_relevant(job, preferences)
        if not relevant:
            logger.info(f"Skipping: {job['title']} at {job['company']}")
            continue

        cover_letter = generate_cover_letter(job, resume_summary)
        if not cover_letter:
            logger.warning(f"Cover letter generation failed for {job['title']}, skipping")
            continue
        success = apply_to_job(job, cover_letter, config)

        if success:
            save_applied_job(job_id)
            applied_count += 1
            send_telegram(
                f"✅ *Applied!*\n"
                f"*Role:* {job['title']}\n"
                f"*Company:* {job['company']}\n"
                f"*Platform:* {job['source'].capitalize()}\n"
                f"*Location:* {job.get('location', 'N/A')}\n"
                f"[View Job]({job['apply_url']})"
            )
            time.sleep(5)
        else:
            send_telegram(
                f"🔔 *New Job Found — Apply Manually*\n"
                f"*Role:* {job['title']}\n"
                f"*Company:* {job['company']}\n"
                f"*Platform:* {job['source'].capitalize()}\n"
                f"[Apply Now]({job['apply_url']})"
            )

    # 3. Check Gmail
    replies = check_gmail_for_replies()
    for reply in replies:
        send_telegram(
            f"📬 *Hiring Email Received!*\n"
            f"*From:* {reply['from']}\n"
            f"*Subject:* {reply['subject']}\n"
            f"⚡ Check your Gmail now!"
        )

    # 4. Summary
    send_telegram(
        f"📊 *Hourly Summary*\n"
        f"🕐 {datetime.now().strftime('%d %b %Y, %I:%M %p')}\n"
        f"✅ Auto-applied: {applied_count}\n"
        f"📬 Hiring emails: {len(replies)}\n"
        f"🔍 Jobs scanned: {len(all_jobs)}"
    )

if __name__ == "__main__":
    run_pipeline()
