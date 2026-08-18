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

import base64
import datetime as dt
import json
import os
import sys
import tempfile
import time

import requests

from common import (
    ContentValidationError,
    DeploymentTimeoutError,
    PipelineError,
    api_retry,
    check_response,
    get_logger,
)
from linkedin_poster import check_token_expiry_warning, post_to_linkedin
from model_selector import pick_working_model
from validators import validate_generated_html

logger = get_logger(__name__)

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
GITHUB_API = "https://api.github.com"
VERCEL_API = "https://api.vercel.com"

LOG_FILE = "projects_log.json"
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

PLAYWRIGHT_WAIT_MS = int(os.environ.get("PLAYWRIGHT_WAIT_MS", "2500"))
VERCEL_POLL_INTERVAL_S = int(os.environ.get("VERCEL_POLL_INTERVAL_S", "5"))
VERCEL_POLL_MAX_ATTEMPTS = int(os.environ.get("VERCEL_POLL_MAX_ATTEMPTS", "24"))

# ---------------------------------------------------------------------------
# Config Validation
# ---------------------------------------------------------------------------

def validate_config():
    if "GEMINI_API_KEY" not in os.environ:
        raise PipelineError("Missing GEMINI_API_KEY")
    if "VERCEL_TOKEN" not in os.environ:
        raise PipelineError("Missing VERCEL_TOKEN")
    if "GITHUB_TOKEN" not in os.environ and "PIPELINE_GITHUB_TOKEN" not in os.environ and "GH_TOKEN" not in os.environ:
        raise PipelineError("Missing GITHUB_TOKEN or PIPELINE_GITHUB_TOKEN or GH_TOKEN")
    if "GITHUB_REPOSITORY_OWNER" not in os.environ:
        raise PipelineError("Missing GITHUB_REPOSITORY_OWNER")
    
    if "LINKEDIN_ACCESS_TOKEN" not in os.environ or "LINKEDIN_PERSON_URN" not in os.environ:
        logger.warning("LINKEDIN_ACCESS_TOKEN or LINKEDIN_PERSON_URN not set. LinkedIn posting will be skipped unless DRY_RUN is set.")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def load_log() -> list[dict]:
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("projects", [])
    if isinstance(data, list):
        return data
    return []


def save_log(log: list[dict]) -> None:
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


def save_temp_html(html_content: str, prefix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".html", prefix=f"{prefix}_")
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(html_content)
    return path


def load_temp_html(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


@api_retry
def gemini_generate(api_key: str, model: str, prompt: str, temperature: float) -> str:
    """One generateContent call, wrapped in @api_retry and raising with check_response."""
    url = f"{GEMINI_BASE}/{model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    resp = requests.post(url, params={"key": api_key}, json=body, timeout=120)
    check_response(resp, f"Gemini generateContent ({model})")
    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise PipelineError(f"Gemini response had unexpected shape: {data}")


# ---------------------------------------------------------------------------
# Step: generate project
# ---------------------------------------------------------------------------

def generate_project(api_key: str, model: str, past_titles: list[str]) -> dict:
    avoid_clause = ""
    if past_titles:
        recent = ", ".join(past_titles[-15:])
        avoid_clause = f"\nDo NOT repeat these previous project ideas: {recent}"

    prompt = f"""Generate a complete, working single-file web app idea. Focus strictly on professional developer tools, productivity utilities, web audio/canvas engines, or data visualizers. Avoid simple, childish, or basic toy concepts.

Respond ONLY with valid JSON, no markdown fences, no preamble, in this exact shape:
{{
  "title": "Short Professional Project Name",
  "description": "One sentence description of the utility/tool",
  "technical_highlights": ["Highlight 1", "Highlight 2", "Highlight 3"],
  "html": "the complete, self-contained HTML file including inline <style> and <script>, fully working, responsive, sleek dark mode theme, no external dependencies except CDN links if needed"
}}
The app should be genuinely useful, highly polished, visually modern (dark mode, crisp UI), and show solid engineering depth.
{avoid_clause}
"""
    raw = gemini_generate(api_key, model, prompt, temperature=0.9)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        cleaned = cleaned.removeprefix("json")
    return json.loads(cleaned.strip())


def generate_project_with_retry(api_key: str, model: str, past_titles: list[str]) -> dict:
    for attempt in range(3):
        logger.info(f"Generating project idea (attempt {attempt + 1})...")
        project = generate_project(api_key, model, past_titles)
        html_content = project.get("html", "")
        is_valid, issues = validate_generated_html(html_content)
        if is_valid:
            return project
        else:
            logger.warning(f"HTML validation failed: {issues}")
    raise ContentValidationError("Failed to generate valid HTML after 3 attempts.")


# ---------------------------------------------------------------------------
# Step: GitHub repo creation + push
# ---------------------------------------------------------------------------

@api_retry
def create_github_repo(token: str, repo_name: str, description: str) -> dict:
    resp = requests.post(
        f"{GITHUB_API}/user/repos",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"},
        json={"name": repo_name, "description": description,
              "private": False, "auto_init": True},
        timeout=30,
    )
    check_response(resp, "GitHub repo creation")
    return resp.json()


@api_retry
def push_file_to_repo(token: str, owner: str, repo: str, path: str,
                       content: str, message: str) -> None:
    b64_content = base64.b64encode(content.encode()).decode()
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"

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
    check_response(resp, f"Pushing {path} to GitHub")


# ---------------------------------------------------------------------------
def capture_screenshot(html_content: str, output_path: str = "screenshot.png") -> str | None:
    """Captures a 1280x800 PNG screenshot of the generated web app using Playwright."""
    try:
        from playwright.sync_api import sync_playwright
        logger.info("Capturing web app screenshot with Playwright...")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content(html_content)
            page.wait_for_timeout(PLAYWRIGHT_WAIT_MS)
            page.screenshot(path=output_path)
            browser.close()
        logger.info(f"Screenshot captured: {output_path}")
        return output_path
    except Exception as e:
        logger.warning(f"Screenshot capture notice: {e}")
        return None


@api_retry
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
    check_response(resp, "Vercel deployment creation")
    
    deployment = resp.json()
    deployment_id = deployment["id"]

    for _ in range(VERCEL_POLL_MAX_ATTEMPTS):
        time.sleep(VERCEL_POLL_INTERVAL_S)
        status_resp = requests.get(
            f"{VERCEL_API}/v13/deployments/{deployment_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        check_response(status_resp, "Vercel deployment status")
        status = status_resp.json().get("readyState")
        if status == "READY":
            return f"https://{deployment['url']}"
        if status in ("ERROR", "CANCELED"):
            raise PipelineError(f"Vercel deployment ended in state: {status}")

    raise DeploymentTimeoutError("Vercel deployment did not become READY within timeout")


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
        logger.warning(msg)
        return {"success": False, "error": msg}

    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = gmail_user
        msg["To"] = to_addr

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, [to_addr], msg.as_string())
        logger.info("Email sent successfully.")
        return {"success": True, "error": None}
    except Exception as e:
        msg = f"Email failed but pipeline continues: {e}"
        logger.warning(msg)
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_pipeline():
    validate_config()
    
    gemini_key = os.environ["GEMINI_API_KEY"]
    github_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("PIPELINE_GITHUB_TOKEN") or os.environ.get("GH_TOKEN", "")
    github_owner = os.environ["GITHUB_REPOSITORY_OWNER"]
    vercel_token = os.environ["VERCEL_TOKEN"]

    linkedin_token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    linkedin_urn = os.environ.get("LINKEDIN_PERSON_URN")

    log = load_log()

    # Step 1: Scan for incomplete project state
    active_entry = None
    for idx, entry in enumerate(log):
        if entry.get("status") and entry.get("status") != "logged":
            active_entry = entry
            break
            
    if active_entry:
        logger.info(f"Resuming incomplete project '{active_entry['title']}' from state '{active_entry['status']}'")
        project_state = active_entry
    else:
        # Step 2: Check backlog unposted to personal linkedin
        unposted_idx = None
        for idx, entry in enumerate(log):
            if not entry.get("posted_to_personal_linkedin", False):
                unposted_idx = idx
                break
                
        if unposted_idx is not None and not TEST_MODE:
            target = log[unposted_idx]
            title = target["title"]
            description = target["description"]
            live_url = target.get("live_url")
            repo_url = target.get("repo_url")
            logger.info(f"Backlog project found: '{title}'. Reposting to personal LinkedIn...")

            # Fetch index.html from GitHub for screenshot
            html_content = ""
            try:
                repo_name = repo_url.split("/")[-1]
                raw_url = f"https://raw.githubusercontent.com/{github_owner}/{repo_name}/main/index.html"
                r_html = requests.get(raw_url, timeout=15)
                if r_html.status_code == 200:
                    html_content = r_html.text
            except Exception as e:
                logger.warning(f"Could not fetch HTML for screenshot: {e}")

            logger.info("Selecting a working Gemini model...")
            model = pick_working_model(gemini_key)

            caption_prompt = f"""Write an engaging, technical, human-sounding LinkedIn post for a software engineer building in public.

Project Name: {title}
Description: {description}
Live Site: {live_url}
GitHub Repo: {repo_url}

Formatting & Content guidelines:
1. Tone: Authentic developer voice ("Just built...", "Created a new tool for..."). Avoid generic corporate AI clichés ("Delighted to announce", "In today's fast-paced world").
2. Engineering & Technical Depth: Emphasize the underlying technical architecture, engineering implementation, and performance highlights (e.g., client-side processing, HTML5 Canvas/Web Audio API performance, zero external dependencies, responsive UI, data management).
3. Include high-impact, relevant tech keywords & buzzwords naturally (#buildinpublic, #webdev, #softwareengineering, Client-Side Architecture, Modern Web Tech, Zero-Dependency, Responsive UI).
4. Clean structure with line breaks and subtle emojis:
   - Hook line capturing technical interest
   - Concise breakdown of key features & engineering highlights
   - Include ONLY these two exact links (no other URLs):
     🌐 Live Site: {live_url}
     📦 Code Repo: {repo_url}
5. End with 3-4 trending tech hashtags (#buildinpublic #webdev #javascript #softwareengineering).

Respond with ONLY the raw caption text, no markdown code fences."""
            caption = gemini_generate(gemini_key, model, caption_prompt, temperature=0.7).strip()
            screenshot_path = capture_screenshot(html_content) if html_content else None

            linkedin_result = {"success": False, "post_url": None, "error": "not attempted"}
            if DRY_RUN:
                logger.info("DRY_RUN mode active - Skipping LinkedIn backlog post.")
                logger.info(f"Caption would be:\n{caption}")
            else:
                if linkedin_token and linkedin_urn:
                    logger.info("Posting backlog project to personal LinkedIn...")
                    linkedin_result = post_to_linkedin(caption, linkedin_token, linkedin_urn, screenshot_path)

                if linkedin_result.get("success"):
                    log[unposted_idx]["posted_to_personal_linkedin"] = True
                    save_log(log)
                    logger.info(f"Backlog project '{title}' posted successfully to personal LinkedIn and log updated!")

            send_email_safe(
                subject=f"Auto Project Pipeline (Backlog): {title}",
                body=f"Project: {title}\nLive: {live_url}\nGitHub: {repo_url}\nLinkedIn: {linkedin_result.get('post_url')}"
            )
            return
            
        project_state = None

    if not project_state:
        past_titles = [entry["title"] for entry in log]

        logger.info("Selecting a working Gemini model...")
        model = pick_working_model(gemini_key)

        try:
            project = generate_project_with_retry(gemini_key, model, past_titles)
        except ContentValidationError as e:
            logger.error(f"Generation failed: {e}")
            return
            
        logger.info(f"Generated: {project['title']}")

        timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        raw_name = f"{project['title'].lower().replace(' ', '-')}-{timestamp}"
        repo_name = "".join(
            c for c in raw_name if (c.isalnum() and c.isascii()) or c == "-"
        )[:90]
        while "--" in repo_name:
            repo_name = repo_name.replace("--", "-")
        repo_name = repo_name.strip("-")
        if not repo_name:
            repo_name = f"auto-project-{timestamp}"

        html_path = save_temp_html(project["html"], repo_name)

        project_state = {
            "title": project["title"],
            "description": project["description"],
            "repo_name": repo_name,
            "html_path": html_path,
            "status": "generated",
            "model": model,
            "timestamp": dt.datetime.now().isoformat(),
        }
        log.append(project_state)
        save_log(log)

    def update_status(new_status: str):
        project_state["status"] = new_status
        save_log(log)

    if TEST_MODE:
        logger.info("TEST_MODE active — skipping GitHub/Vercel/LinkedIn writes.")
        return

    html_content = ""
    if project_state.get("html_path") and os.path.exists(project_state["html_path"]):
        html_content = load_temp_html(project_state["html_path"])

    if project_state["status"] == "generated":
        logger.info(f"Creating GitHub repo: {project_state['repo_name']}")
        repo_data = create_github_repo(github_token, project_state["repo_name"], project_state["description"])
        project_state["repo_url"] = repo_data["html_url"]

        logger.info("Pushing index.html...")
        push_file_to_repo(github_token, github_owner, project_state["repo_name"],
                           "index.html", html_content,
                           "Add generated project")
        update_status("repo_created")

    if project_state["status"] == "repo_created":
        logger.info("Deploying to Vercel...")
        live_url = deploy_to_vercel(vercel_token, project_state["repo_name"], html_content)
        logger.info(f"Live at: {live_url}")
        project_state["live_url"] = live_url

        readme = (f"# {project_state['title']}\n\n{project_state['description']}\n\n"
                  f"**Live:** {live_url}\n")
        push_file_to_repo(github_token, github_owner, project_state["repo_name"],
                           "README.md", readme, "Update README with live URL")
        update_status("deployed")

    if project_state["status"] == "deployed":
        logger.info("Generating LinkedIn caption...")
        model = project_state.get("model") or pick_working_model(gemini_key)
        
        caption_prompt = f"""Write an engaging, technical, human-sounding LinkedIn post for a software engineer building in public.

Project Name: {project_state['title']}
Description: {project_state['description']}
Live Site: {project_state['live_url']}
GitHub Repo: {project_state['repo_url']}

Formatting & Content guidelines:
1. Tone: Authentic developer voice ("Just built...", "Created a new tool for..."). Avoid generic corporate AI clichés ("Delighted to announce", "In today's fast-paced world").
2. Engineering & Technical Depth: Emphasize the underlying technical architecture, engineering implementation, and performance highlights (e.g., client-side processing, HTML5 Canvas/Web Audio API performance, zero external dependencies, responsive UI, data management).
3. Include high-impact, relevant tech keywords & buzzwords naturally (#buildinpublic, #webdev, #softwareengineering, Client-Side Architecture, Modern Web Tech, Zero-Dependency, Responsive UI).
4. Clean structure with line breaks and subtle emojis:
   - Hook line capturing technical interest
   - Concise breakdown of key features & engineering highlights
   - Include ONLY these two exact links (no other URLs):
     🌐 Live Site: {project_state['live_url']}
     📦 Code Repo: {project_state['repo_url']}
5. End with 3-4 trending tech hashtags (#buildinpublic #webdev #javascript #softwareengineering).

Respond with ONLY the raw caption text, no markdown code fences."""
        caption = gemini_generate(gemini_key, model, caption_prompt, temperature=0.7).strip()
        project_state["caption"] = caption
        
        screenshot_path = capture_screenshot(html_content)
        if screenshot_path:
            project_state["screenshot_path"] = screenshot_path
        update_status("screenshotted")

    if project_state["status"] == "screenshotted":
        linkedin_result = {"success": False, "post_url": None, "error": "not attempted"}
        if DRY_RUN:
            logger.info("[DRY_RUN] LinkedIn post skipped. Caption & image logged below:")
            logger.info(f"[DRY_RUN] Caption:\n{project_state['caption']}")
            logger.info(f"[DRY_RUN] Screenshot path: {project_state.get('screenshot_path')}")
            linkedin_result = {
                "success": True,
                "post_url": "(skipped - DRY_RUN mode)",
                "error": None,
            }
            project_state["linkedin_success"] = True
            project_state["linkedin_post_url"] = "(skipped - DRY_RUN mode)"
        else:
            if linkedin_token and linkedin_urn:
                expiry_warning = check_token_expiry_warning()
                if expiry_warning:
                    logger.warning(expiry_warning)

                logger.info("Posting to LinkedIn (with project screenshot)...")
                linkedin_result = post_to_linkedin(
                    project_state["caption"],
                    linkedin_token,
                    linkedin_urn,
                    project_state.get("screenshot_path"),
                )
                project_state["linkedin_success"] = linkedin_result.get("success", False)
                project_state["linkedin_post_url"] = linkedin_result.get("post_url")
                if not project_state["linkedin_success"]:
                    logger.warning(
                        f"LinkedIn posting failed: {linkedin_result.get('error')}"
                    )
            else:
                logger.warning(
                    "Skipping LinkedIn: LINKEDIN_ACCESS_TOKEN or LINKEDIN_PERSON_URN not set"
                )
                project_state["linkedin_success"] = False
                project_state["linkedin_post_url"] = None

        update_status("posted")

    if project_state["status"] == "posted":
        post_status_str = (
            f"SUCCESS - {project_state.get('linkedin_post_url')}"
            if project_state.get("linkedin_success")
            else "FAILED"
        )
        email_body_lines = [
            f"Project: {project_state['title']}",
            f"Description: {project_state['description']}",
            f"GitHub: {project_state.get('repo_url') or '(skipped - TEST_MODE)'}",
            f"Live URL: {project_state.get('live_url') or '(skipped - TEST_MODE)'}",
            "",
            f"LinkedIn post: {post_status_str}",
        ]
        send_email_safe(
            subject=f"Auto Project Pipeline: {project_state['title']}",
            body="\n".join(email_body_lines),
        )

        if project_state.get("html_path") and os.path.exists(project_state["html_path"]):
            try:
                os.remove(project_state["html_path"])
            except OSError as e:
                logger.warning(f"Could not remove temp html file: {e}")

        if "caption" in project_state:
            del project_state["caption"]
        if "screenshot_path" in project_state:
            del project_state["screenshot_path"]

        update_status("logged")
        logger.info("Saved to projects_log.json")

    logger.info("Run complete.")


if __name__ == "__main__":
    try:
        run_pipeline()
    except Exception as e:
        logger.error(f"FATAL: {e}", exc_info=True)
        sys.exit(1)
