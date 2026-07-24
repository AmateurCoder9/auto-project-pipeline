"""
pipeline.py

Runs the full auto-project cycle:
  1. Load projects_log.json (avoid repeating past project ideas)
  2. Pick a working Gemini model (live-tested, see model_selector.py)
  3. Generate a complete HTML/CSS/JS web app
  4. Create a public GitHub repo, push index.html + README
  5. Create a Vercel deployment, poll until live
  6. Update README with the live URL
  7. Generate a LinkedIn caption
  8. Post to LinkedIn (failure here does NOT block steps 9-10)
  9. Send a backup confirmation email (failure here does NOT block anything)
  10. Save to projects_log.json + commit

Every external call that is allowed to fail without killing the run
is wrapped so a partial success (e.g. repo+deploy worked, LinkedIn
token expired) still produces a usable log entry and email instead of
a crashed Action.
"""

import os
import sys
import json
import time
import base64
import datetime as dt
import requests

from model_selector import pick_working_model
from linkedin_poster import post_to_linkedin, check_token_expiry_warning

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
GITHUB_API = "https://api.github.com"
VERCEL_API = "https://api.vercel.com"

LOG_FILE = "projects_log.json"
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def load_log() -> list[dict]:
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r") as f:
        return json.load(f)


def save_log(log: list[dict]) -> None:
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


def gemini_generate(api_key: str, model: str, prompt: str, temperature: float) -> str:
    """One generateContent call, raising with a readable message on failure."""
    url = f"{GEMINI_BASE}/{model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    resp = requests.post(url, params={"key": api_key}, json=body, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Gemini generateContent failed (HTTP {resp.status_code}) "
            f"for model {model}: {resp.text[:500]}"
        )
    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise RuntimeError(f"Gemini response had unexpected shape: {data}")


# ---------------------------------------------------------------------------
# Step: generate project
# ---------------------------------------------------------------------------

def generate_project(api_key: str, model: str, past_titles: list[str]) -> dict:
    avoid_clause = ""
    if past_titles:
        recent = ", ".join(past_titles[-15:])
        avoid_clause = f"\nDo NOT repeat these previous project ideas: {recent}"

    prompt = f"""Generate a complete, working single-file web app idea.
Respond ONLY with valid JSON, no markdown fences, no preamble, in this
exact shape:
{{
  "title": "short project name",
  "description": "one sentence description",
  "html": "the complete, self-contained HTML file including inline <style> and <script>, fully working, no external dependencies except CDN links if needed"
}}
The app should be small but genuinely functional and visually clean.
{avoid_clause}
"""
    raw = gemini_generate(api_key, model, prompt, temperature=0.9)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return json.loads(cleaned.strip())


# ---------------------------------------------------------------------------
# Step: GitHub repo creation + push
# ---------------------------------------------------------------------------

def create_github_repo(token: str, repo_name: str, description: str) -> dict:
    resp = requests.post(
        f"{GITHUB_API}/user/repos",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"},
        json={"name": repo_name, "description": description,
              "private": False, "auto_init": True},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"GitHub repo creation failed "
                            f"(HTTP {resp.status_code}): {resp.text[:500]}")
    return resp.json()


def push_file_to_repo(token: str, owner: str, repo: str, path: str,
                       content: str, message: str) -> None:
    b64_content = base64.b64encode(content.encode()).decode()
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"

    # Check if file exists (needed for the initial README from auto_init)
    existing = requests.get(
        url, headers={"Authorization": f"Bearer {token}"}, timeout=30
    )
    sha = existing.json().get("sha") if existing.status_code == 200 else None

    body = {"message": message, "content": b64_content}
    if sha:
        body["sha"] = sha

    resp = requests.put(
        url,
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"},
        json=body,
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Pushing {path} failed "
                            f"(HTTP {resp.status_code}): {resp.text[:500]}")


# ---------------------------------------------------------------------------
# Step: Vercel deployment
# ---------------------------------------------------------------------------

def deploy_to_vercel(token: str, project_name: str, html_content: str) -> str:
    resp = requests.post(
        f"{VERCEL_API}/v13/deployments",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": project_name,
            "files": [{"file": "index.html", "data": html_content}],
            "projectSettings": {"framework": None},
            "target": "production",
        },
        timeout=60,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Vercel deployment failed "
                            f"(HTTP {resp.status_code}): {resp.text[:500]}")
    deployment = resp.json()
    deployment_id = deployment["id"]

    # Poll until ready (or error), max ~2 minutes
    for _ in range(24):
        time.sleep(5)
        status_resp = requests.get(
            f"{VERCEL_API}/v13/deployments/{deployment_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        status = status_resp.json().get("readyState")
        if status == "READY":
            return f"https://{deployment['url']}"
        if status in ("ERROR", "CANCELED"):
            raise RuntimeError(f"Vercel deployment ended in state: {status}")

    raise RuntimeError("Vercel deployment did not become READY within timeout")


# ---------------------------------------------------------------------------
# Step: email (best-effort, never raises)
# ---------------------------------------------------------------------------

def send_email_safe(subject: str, body: str) -> dict:
    """Wrapped so a failure here NEVER stops the pipeline."""
    import smtplib
    from email.mime.text import MIMEText

    gmail_user = os.environ.get("GMAIL_USER")
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD")
    to_addr = os.environ.get("NOTIFY_EMAIL", gmail_user)

    if not gmail_user or not gmail_pass:
        msg = "Email skipped: GMAIL_USER or GMAIL_APP_PASSWORD not set."
        print(f"[email] {msg}", file=sys.stderr)
        return {"success": False, "error": msg}

    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = gmail_user
        msg["To"] = to_addr

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, [to_addr], msg.as_string())
        print("[email] Sent successfully.", file=sys.stderr)
        return {"success": True, "error": None}
    except Exception as e:
        msg = f"Email failed but pipeline continues: {e}"
        print(f"[email] {msg}", file=sys.stderr)
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_pipeline():
    gemini_key = os.environ["GEMINI_API_KEY"]
    github_token = os.environ["GITHUB_TOKEN"]
    github_owner = os.environ["GITHUB_REPOSITORY_OWNER"]
    vercel_token = os.environ["VERCEL_TOKEN"]

    linkedin_token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    linkedin_urn = os.environ.get("LINKEDIN_PERSON_URN")

    log = load_log()
    past_titles = [entry["title"] for entry in log]

    print("[pipeline] Selecting a working Gemini model...")
    model = pick_working_model(gemini_key)

    print("[pipeline] Generating project idea...")
    project = generate_project(gemini_key, model, past_titles)
    print(f"[pipeline] Generated: {project['title']}")

    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    raw_name = f"{project['title'].lower().replace(' ', '-')}-{timestamp}"
    # GitHub repo names must be ASCII alphanumerics + hyphens only. Python's
    # str.isalnum() returns True for accented/non-Latin letters (e.g. "ñ",
    # "é", CJK characters), which GitHub's API rejects with a 422 — so we
    # explicitly restrict to ASCII here rather than relying on isalnum().
    repo_name = "".join(
        c for c in raw_name if (c.isalnum() and c.isascii()) or c == "-"
    )[:90]
    while "--" in repo_name:
        repo_name = repo_name.replace("--", "-")
    repo_name = repo_name.strip("-")
    if not repo_name:
        # Defensive fallback only — the timestamp suffix is always ASCII
        # digits/hyphens, so repo_name never actually ends up empty even
        # for a fully non-ASCII title. Kept in case the timestamp format
        # above is ever changed to something that could be stripped too.
        repo_name = f"auto-project-{timestamp}"

    live_url = None
    repo_url = None
    linkedin_result = {"success": False, "post_url": None, "error": "not attempted"}

    if TEST_MODE:
        print("[pipeline] TEST_MODE active — skipping GitHub/Vercel/LinkedIn writes.")
    else:
        print(f"[pipeline] Creating GitHub repo: {repo_name}")
        repo_data = create_github_repo(github_token, repo_name, project["description"])
        repo_url = repo_data["html_url"]

        print("[pipeline] Pushing index.html...")
        push_file_to_repo(github_token, github_owner, repo_name,
                           "index.html", project["html"],
                           "Add generated project")

        print("[pipeline] Deploying to Vercel...")
        live_url = deploy_to_vercel(vercel_token, repo_name, project["html"])
        print(f"[pipeline] Live at: {live_url}")

        readme = (f"# {project['title']}\n\n{project['description']}\n\n"
                  f"**Live:** {live_url}\n")
        push_file_to_repo(github_token, github_owner, repo_name,
                           "README.md", readme, "Update README with live URL")

        print("[pipeline] Generating LinkedIn caption...")
        caption_prompt = (
            f"Write a short, engaging LinkedIn caption (max 3 sentences, "
            f"no hashtags spam, 2-3 relevant hashtags max) announcing a "
            f"new project called '{project['title']}': "
            f"{project['description']}. Live at {live_url}. "
            f"Respond with ONLY the caption text, nothing else."
        )
        caption = gemini_generate(gemini_key, model, caption_prompt, temperature=0.7).strip()

        if linkedin_token and linkedin_urn:
            expiry_warning = check_token_expiry_warning()
            if expiry_warning:
                print(f"[pipeline] WARNING: {expiry_warning}", file=sys.stderr)

            print("[pipeline] Posting to LinkedIn...")
            linkedin_result = post_to_linkedin(caption, linkedin_token, linkedin_urn)
        else:
            linkedin_result = {"success": False, "post_url": None,
                                "error": "LINKEDIN_ACCESS_TOKEN or "
                                         "LINKEDIN_PERSON_URN not set"}
            print(f"[pipeline] Skipping LinkedIn: {linkedin_result['error']}",
                  file=sys.stderr)

    # Email is best-effort and always attempted, regardless of what failed above
    email_body_lines = [
        f"Project: {project['title']}",
        f"Description: {project['description']}",
        f"GitHub: {repo_url or '(skipped - TEST_MODE)'}",
        f"Live URL: {live_url or '(skipped - TEST_MODE)'}",
        "",
        f"LinkedIn post: {'SUCCESS - ' + str(linkedin_result['post_url']) if linkedin_result['success'] else 'FAILED - ' + str(linkedin_result['error'])}",
    ]
    send_email_safe(
        subject=f"Auto Project Pipeline: {project['title']}",
        body="\n".join(email_body_lines),
    )

    if not TEST_MODE:
        log.append({
            "title": project["title"],
            "description": project["description"],
            "repo_url": repo_url,
            "live_url": live_url,
            "linkedin_success": linkedin_result["success"],
            "timestamp": dt.datetime.now().isoformat(),
        })
        save_log(log)
        print("[pipeline] Saved to projects_log.json")

    print("[pipeline] Run complete.")


if __name__ == "__main__":
    try:
        run_pipeline()
    except Exception as e:
        print(f"[pipeline] FATAL: {e}", file=sys.stderr)
        sys.exit(1)
