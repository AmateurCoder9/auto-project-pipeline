"""
Auto Project Pipeline v2
========================
Fully automated biweekly pipeline that:
1. Generates a project using Google Gemini API
2. Creates a GitHub repository and pushes the code
3. Deploys to Vercel and gets a live URL
4. Generates a LinkedIn caption using Gemini API
5. Posts directly to LinkedIn via the REST Posts API
6. Sends a confirmation email (optional backup)

Author: Vedant Kapadia (@AmateurCoder9)
Schedule: 1st and 15th of every month at 9:30 AM IST
"""

import json
import os
import re
import smtplib
import sys
import time
import base64
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from google import genai
from google.genai import types

# ════════════════════════════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════════════════════════════

# All credentials from environment variables (GitHub Actions secrets)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
VERCEL_TOKEN = os.environ.get("VERCEL_TOKEN", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

# LinkedIn credentials
LINKEDIN_ACCESS_TOKEN = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
LINKEDIN_PERSON_URN = os.environ.get("LINKEDIN_PERSON_URN", "")

# Developer identity
DEVELOPER_NAME = "Vedant Kapadia"
GITHUB_USERNAME = "AmateurCoder9"
UNIVERSITY = "CHARUSAT (Charotar University of Science and Technology)"
DEGREE = "B.Tech Computer Engineering, Year 1"
LOCATION = "Anand, Gujarat, India"
EMAIL_FROM = "vedant1ce1@gmail.com"
EMAIL_TO = "vedant1ce1@gmail.com"

# Timezone: IST (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

# API base URLs
GITHUB_API = "https://api.github.com"
VERCEL_API = "https://api.vercel.com"
LINKEDIN_API = "https://api.linkedin.com"

# Gemini models — primary and fallback
GEMINI_PRIMARY_MODEL = "gemini-2.0-flash"
GEMINI_FALLBACK_MODEL = "gemini-2.0-flash-lite"

# LinkedIn API version (YYYYMM format)
LINKEDIN_VERSION = "202607"

# Project log file path
PROJECTS_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "projects_log.json")


def log(message: str) -> None:
    """Log a message with IST timestamp."""
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    print(f"[{now}] {message}")


# ════════════════════════════════════════════════════════════
# STEP 0 — LOAD PROJECTS LOG
# ════════════════════════════════════════════════════════════

def load_projects_log() -> list:
    """
    Read projects_log.json and return the list of previously built projects.
    Returns an empty list if the file doesn't exist or is invalid.
    """
    try:
        with open(PROJECTS_LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("projects", [])
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log(f"Warning: Could not load projects log: {e}")
        return []


# ════════════════════════════════════════════════════════════
# STEP 1 — PROJECT GENERATION (Gemini API)
# ════════════════════════════════════════════════════════════

def _call_gemini(prompt: str, temperature: float, max_tokens: int, model: str = None) -> str:
    """
    Call Gemini API with the given prompt and settings.
    Tries primary model first, falls back to lite model on 429/quota errors.

    Args:
        prompt: The text prompt
        temperature: Generation temperature
        max_tokens: Max output tokens
        model: Override model name (uses primary by default)

    Returns:
        The response text

    Raises:
        RuntimeError on failure after all retries
    """
    client = genai.Client(api_key=GEMINI_API_KEY)
    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
    )

    models_to_try = [model or GEMINI_PRIMARY_MODEL, GEMINI_FALLBACK_MODEL]

    for model_name in models_to_try:
        for attempt in range(1, 3):  # 2 attempts per model
            log(f"  Gemini call: model={model_name}, attempt={attempt}/2...")
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config,
                )
                return response.text.strip()

            except Exception as e:
                error_str = str(e)
                log(f"  API error: {error_str[:200]}")

                is_rate_limit = "429" in error_str or "RESOURCE_EXHAUSTED" in error_str
                is_quota = "quota" in error_str.lower() or "limit: 0" in error_str

                if is_rate_limit and not is_quota:
                    # Temporary rate limit — wait and retry same model
                    log(f"  Rate limited — waiting 60 seconds...")
                    time.sleep(60)
                elif is_quota:
                    # Quota exhausted — skip to fallback model immediately
                    log(f"  Quota exhausted on {model_name}, trying fallback...")
                    break  # Break inner loop, try next model
                else:
                    # Other error — brief pause and retry
                    time.sleep(5)

                if attempt == 2 and model_name == models_to_try[-1]:
                    raise RuntimeError(f"Gemini API failed after all attempts: {e}")

    raise RuntimeError("Gemini API failed: exhausted all models and retries")


def generate_project(previous_projects: list) -> dict:
    """
    Call Gemini API to generate a complete single-file HTML project.
    Uses temperature=0.9 for creative output.

    Args:
        previous_projects: List of previously built project dicts

    Returns:
        dict with keys: project_name, project_title, tagline, description,
        category, tech_used, key_features, html
    """
    log("Step 1: Generating project with Gemini API...")

    # Build the list of previously built project names
    if previous_projects:
        prev_list = "\n".join(
            f"- {p.get('project_title', p.get('project_name', 'Unknown'))} (Category {p.get('category', '?')})"
            for p in previous_projects
        )
    else:
        prev_list = "None yet — this is the first run."

    prompt = f"""You are an expert frontend developer and creative technologist with deep knowledge of India, Gujarat, and the daily lives of Indian citizens. You build tools that are genuinely useful, visually impressive, and technically interesting. You write clean, well-commented code.

Generate a complete, single-file HTML web application.

QUALITY REQUIREMENTS — this is critical:
- The project must actually WORK. Every button, input, and feature must be functional. No placeholder logic.
- The UI must look modern and professional — not like a basic tutorial project. Use gradients, cards, shadows, smooth transitions, hover effects.
- Must be fully mobile responsive using CSS flexbox or grid.
- Must have a proper app header with a title and subtitle.
- Must have a loading state or spinner where relevant.
- Must have empty state handling (show a helpful message when there is no data yet).
- Must have error state handling (show a friendly error if something goes wrong).
- Code must be well-commented.

TECHNICAL REQUIREMENTS:
- Single self-contained index.html file only
- HTML5, CSS3, vanilla JavaScript (ES6+)
- No React, Vue, Angular, or any JS framework
- No npm, no build steps, no package.json
- External CDN libraries ARE allowed:
  recommended: Tailwind CSS CDN for styling,
  Chart.js CDN if charts are needed,
  Flatpickr CDN if date pickers are needed,
  Lucide icons CDN for icons
- Must work offline after first load if possible
- All data that can be hardcoded should be hardcoded (do not rely on external APIs that need keys)

PROJECT IDEAS — pick ONE of these categories and build something creative within it. Rotate categories each run.
Previously built projects will be listed below — do NOT repeat them.

PREVIOUSLY BUILT PROJECTS:
{prev_list}

CATEGORY A — Gujarat and India Civic Tools:
- GSRTC bus route finder with all major Gujarat routes hardcoded
- Gujarat government holiday calendar with countdowns
- Indian railway station code lookup (hardcoded major stations)
- Gujarat district and taluka explorer with population info
- Pincode to city/state lookup for Gujarat (hardcoded)
- RTO vehicle registration code lookup by state/district
- Indian national highway route explorer
- Gujarat election results explorer (historical data hardcoded)
- BRTS Ahmedabad route and stop finder
- Gujarat university and college directory

CATEGORY B — Daily Life Utility Tools:
- Indian fuel price calculator (petrol/diesel with state tax)
- EMI calculator with Indian bank rates
- Indian income tax calculator (new vs old regime comparison)
- SIP/mutual fund return calculator in INR
- Indian cooking measurement converter
- Electricity bill calculator for Gujarat (DGVCL/UGVCL rates hardcoded)
- Mobile recharge plan comparison tool (Jio/Airtel/BSNL hardcoded plans)
- Indian festival calendar with countdown timers
- Cricket match scoring assistant / scorecard builder
- IPL team stats explorer (hardcoded historical data)

CATEGORY C — Student and Developer Tools:
- CGPA to percentage converter (GTU/CHARUSAT formula)
- Semester grade tracker and predictor
- Programming language syntax quick-reference cards
- Git commands cheat sheet with interactive search
- HTTP status code lookup tool
- JSON formatter and validator
- Regex tester with Indian examples (Aadhaar, PAN, phone formats)
- Resume ATS keyword checker
- DSA problem tracker / progress dashboard
- Competitive programming timer with notes

CATEGORY D — Fun and Creative Tools:
- Indian name meaning and origin finder (hardcoded database)
- Gujarati language learning flashcards
- Indian states quiz with map
- Cricket trivia quiz (India focused)
- Random Gujarati recipe generator (hardcoded recipes)
- Indian movie recommendation quiz
- Personality quiz with Indian cultural context
- Diwali rangoli pattern generator (CSS/canvas based)
- Bollywood music era explorer
- Zodiac birth chart generator

Pick the most interesting and impressive option. Make it something a recruiter would actually be impressed by.

Respond ONLY with a valid JSON object. No markdown, no backticks, no explanation before or after. Raw JSON only, starting with {{ and ending with }}:
{{
  "project_name": "short-kebab-case-max-5-words",
  "project_title": "Human Readable Project Title",
  "tagline": "One punchy sentence what it does",
  "description": "Two sentence description",
  "category": "A or B or C or D",
  "tech_used": ["HTML", "CSS", "JavaScript", "Tailwind CSS"],
  "key_features": ["feature 1", "feature 2", "feature 3"],
  "html": "COMPLETE FULL HTML CODE here"
}}"""

    raw_text = _call_gemini(prompt, temperature=0.9, max_tokens=65536)
    log(f"  Received response ({len(raw_text)} chars)")

    # Strip markdown code fences if present
    raw_text = re.sub(r"^```(?:json)?\s*\n?", "", raw_text)
    raw_text = re.sub(r"\n?```\s*$", "", raw_text)
    raw_text = raw_text.strip()

    # Parse JSON
    try:
        project_data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        log(f"  JSON parse failed, attempting to extract JSON block...")
        # Try to find JSON object in the response
        match = re.search(r'\{[\s\S]*\}', raw_text)
        if match:
            try:
                project_data = json.loads(match.group())
            except json.JSONDecodeError:
                raise RuntimeError(f"Could not parse Gemini response as JSON: {e}")
        else:
            raise RuntimeError(f"No JSON found in Gemini response: {e}")

    # Validate required fields
    required_fields = ["project_name", "project_title", "tagline",
                       "description", "category", "tech_used",
                       "key_features", "html"]
    for field in required_fields:
        if field not in project_data or not project_data[field]:
            raise ValueError(f"Missing or empty field: {field}")

    # Validate HTML content
    html_content = project_data["html"]
    if "<!DOCTYPE" not in html_content.upper() and "<html" not in html_content.lower():
        raise ValueError("HTML field does not contain valid HTML")

    # Sanitize project_name to be a valid GitHub repo name
    project_data["project_name"] = re.sub(
        r"[^a-z0-9-]", "",
        project_data["project_name"].lower().strip()
    )

    log(f"  Project generated: {project_data['project_title']}")
    log(f"     Category: {project_data['category']}")
    log(f"     Name: {project_data['project_name']}")
    return project_data


# ════════════════════════════════════════════════════════════
# STEP 2 — GITHUB REPOSITORY CREATION
# ════════════════════════════════════════════════════════════

def _github_headers() -> dict:
    """Return authorization headers for GitHub API calls."""
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def create_github_repo(project_data: dict) -> str:
    """
    Create a new public GitHub repository and push index.html + README.md.
    Uses the Contents API to bootstrap, then Git Data API for remaining files.

    Args:
        project_data: Dict with project_name, project_title, description, etc.

    Returns:
        The full GitHub repo URL
    """
    log("Step 2: Creating GitHub repository...")

    repo_name = project_data["project_name"]
    headers = _github_headers()

    # 2a. Create the repository
    create_url = f"{GITHUB_API}/user/repos"
    create_payload = {
        "name": repo_name,
        "description": project_data["description"],
        "private": False,
        "auto_init": False,
    }

    resp = requests.post(create_url, json=create_payload, headers=headers)

    # Handle name collision — append -v2
    if resp.status_code == 422 and "name already exists" in resp.text.lower():
        log(f"  Repo name '{repo_name}' taken, trying '{repo_name}-v2'...")
        repo_name = f"{repo_name}-v2"
        project_data["project_name"] = repo_name
        create_payload["name"] = repo_name
        resp = requests.post(create_url, json=create_payload, headers=headers)

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Failed to create GitHub repo: {resp.status_code} — {resp.text}")

    repo_url = f"https://github.com/{GITHUB_USERNAME}/{repo_name}"
    log(f"  Repository created: {repo_url}")

    # Set topics
    topics_url = f"{GITHUB_API}/repos/{GITHUB_USERNAME}/{repo_name}/topics"
    requests.put(topics_url, json={
        "names": ["html", "css", "javascript", "india", "open-source", "web-app", "charusat"]
    }, headers=headers)

    # 2b. Bootstrap repo with README via Contents API (handles empty repo)
    readme_content = _build_readme(project_data, "[Deploying...]")
    encoded_readme = base64.b64encode(readme_content.encode("utf-8")).decode("utf-8")

    requests.put(
        f"{GITHUB_API}/repos/{GITHUB_USERNAME}/{repo_name}/contents/README.md",
        json={
            "message": f"Initial commit — {project_data['project_title']}",
            "content": encoded_readme,
        },
        headers=headers,
    )
    time.sleep(2)

    # 2c. Push index.html via Git Data API on top of the bootstrap commit
    ref_resp = requests.get(
        f"{GITHUB_API}/repos/{GITHUB_USERNAME}/{repo_name}/git/ref/heads/main",
        headers=headers,
    )
    if ref_resp.status_code != 200:
        raise RuntimeError(f"Could not get main ref: {ref_resp.status_code}")

    current_sha = ref_resp.json()["object"]["sha"]
    commit_data = requests.get(
        f"{GITHUB_API}/repos/{GITHUB_USERNAME}/{repo_name}/git/commits/{current_sha}",
        headers=headers,
    ).json()
    base_tree = commit_data["tree"]["sha"]

    # Create blob for index.html
    html_blob = requests.post(
        f"{GITHUB_API}/repos/{GITHUB_USERNAME}/{repo_name}/git/blobs",
        json={"content": project_data["html"], "encoding": "utf-8"},
        headers=headers,
    ).json()

    # Create tree
    tree = requests.post(
        f"{GITHUB_API}/repos/{GITHUB_USERNAME}/{repo_name}/git/trees",
        json={
            "base_tree": base_tree,
            "tree": [{"path": "index.html", "mode": "100644", "type": "blob", "sha": html_blob["sha"]}]
        },
        headers=headers,
    ).json()

    # Create commit
    commit = requests.post(
        f"{GITHUB_API}/repos/{GITHUB_USERNAME}/{repo_name}/git/commits",
        json={
            "message": f"Add index.html — {project_data['project_title']}",
            "tree": tree["sha"],
            "parents": [current_sha],
        },
        headers=headers,
    ).json()

    # Update ref
    requests.patch(
        f"{GITHUB_API}/repos/{GITHUB_USERNAME}/{repo_name}/git/refs/heads/main",
        json={"sha": commit["sha"], "force": True},
        headers=headers,
    )

    log(f"  Files pushed to {repo_url}")
    return repo_url


def _build_readme(project_data: dict, vercel_url: str) -> str:
    """Build the README.md content for the project repository."""
    features = "\n".join(f"- {f}" for f in project_data.get("key_features", []))
    tech = "\n".join(f"- {t}" for t in project_data.get("tech_used", []))

    return f"""# {project_data['project_title']}

> {project_data['tagline']}

{project_data['description']}

## Features
{features}

## Live Demo
{vercel_url}

## Tech Stack
{tech}

## Getting Started
No installation needed. Open index.html in any browser or visit the live demo link.

## Author
Built by [{DEVELOPER_NAME}](https://github.com/{GITHUB_USERNAME})
{DEGREE} @ {UNIVERSITY}, Gujarat, India

---
*Auto-generated project — part of a biweekly build-in-public challenge*
"""


def update_readme_with_url(repo_name: str, project_data: dict, vercel_url: str) -> None:
    """Update the README.md in the GitHub repo with the actual Vercel URL."""
    log("  Updating README.md with Vercel URL...")
    headers = _github_headers()

    get_url = f"{GITHUB_API}/repos/{GITHUB_USERNAME}/{repo_name}/contents/README.md"
    resp = requests.get(get_url, headers=headers)

    if resp.status_code != 200:
        log(f"  Could not fetch README for update: {resp.status_code}")
        return

    current_sha = resp.json()["sha"]
    new_content = _build_readme(project_data, vercel_url)
    encoded = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")

    update_resp = requests.put(get_url, json={
        "message": "Update README with live demo URL",
        "content": encoded,
        "sha": current_sha,
    }, headers=headers)

    if update_resp.status_code in (200, 201):
        log("  README updated with Vercel URL")
    else:
        log(f"  README update failed: {update_resp.status_code}")


# ════════════════════════════════════════════════════════════
# STEP 3 — VERCEL DEPLOYMENT
# ════════════════════════════════════════════════════════════

def _vercel_headers() -> dict:
    """Return authorization headers for Vercel API calls."""
    return {
        "Authorization": f"Bearer {VERCEL_TOKEN}",
        "Content-Type": "application/json",
    }


def deploy_to_vercel(repo_name: str) -> str:
    """
    Create a Vercel project linked to the GitHub repo and wait for deployment.
    Polls every 15 seconds, up to 5 minutes.

    Returns:
        Live deployment URL or fallback string
    """
    log("Step 3: Deploying to Vercel...")

    headers = _vercel_headers()
    github_repo = f"{GITHUB_USERNAME}/{repo_name}"

    # Create Vercel project
    resp = requests.post(f"{VERCEL_API}/v11/projects", json={
        "name": repo_name,
        "framework": None,
        "gitRepository": {"type": "github", "repo": github_repo},
        "buildCommand": "",
        "outputDirectory": "./",
    }, headers=headers)

    if resp.status_code not in (200, 201):
        log(f"  Vercel project creation: {resp.status_code} — {resp.text[:300]}")
        if resp.status_code != 409:
            raise RuntimeError(f"Failed to create Vercel project: {resp.status_code}")

    project_data = resp.json() if resp.status_code in (200, 201) else {}
    project_id = project_data.get("id", "")
    log(f"  Vercel project created: {repo_name}")

    # Wait for auto-deploy
    log("  Waiting for auto-deployment...")
    time.sleep(10)

    # Poll deployment status
    for poll in range(1, 21):
        log(f"  Polling ({poll}/20)...")
        try:
            dep_resp = requests.get(
                f"{VERCEL_API}/v6/deployments",
                params={"projectId": project_id, "limit": 1},
                headers=headers,
            )
            if dep_resp.status_code == 200:
                deployments = dep_resp.json().get("deployments", [])
                if deployments:
                    d = deployments[0]
                    state = d.get("state", d.get("readyState", "UNKNOWN"))
                    url = d.get("url", "")
                    log(f"    State: {state}")

                    if state in ("READY", "ready"):
                        vercel_url = f"https://{url}" if url and not url.startswith("http") else url
                        log(f"  Deployment successful: {vercel_url}")
                        return vercel_url
                    if state in ("ERROR", "CANCELED", "error", "canceled"):
                        return "Deployment failed — check vercel.com"
        except Exception as e:
            log(f"    Poll error: {e}")
        time.sleep(15)

    log("  Deployment timed out after 5 minutes")
    return "Deployment pending — check vercel.com"


# ════════════════════════════════════════════════════════════
# STEP 4 — LINKEDIN CAPTION GENERATION
# ════════════════════════════════════════════════════════════

def generate_linkedin_caption(project_data: dict, github_url: str, vercel_url: str) -> str:
    """
    Call Gemini API to generate a LinkedIn post caption.
    Uses temperature=0.7 for balanced creativity.

    Returns:
        LinkedIn post caption text
    """
    log("Step 4: Generating LinkedIn caption...")

    features_list = ", ".join(project_data.get("key_features", []))
    tech_list = ", ".join(project_data.get("tech_used", []))

    prompt = f"""Write a LinkedIn post for this project deployment.

Developer: {DEVELOPER_NAME}
University: {UNIVERSITY}
Year: First year B.Tech Computer Engineering
Project name: {project_data['project_title']}
What it does: {project_data['description']}
Key features: {features_list}
Tech used: {tech_list}
Live URL: {vercel_url}
GitHub URL: {github_url}

STRICT REQUIREMENTS:
- Length: 150 to 200 words exactly
- Do NOT start with: Excited, Thrilled, Happy, Proud, Delighted, I am pleased
- Start with a hook — a question, bold statement, relatable problem, or interesting fact
- Tone: conversational, like a real 18-year-old developer. Humble but confident.
- Mention built with HTML, CSS, JavaScript only — no frameworks — to show strong fundamentals
- Mention CHARUSAT naturally
- Include live link and GitHub link naturally
- End with 5 hashtags — must include #buildinpublic and #webdev plus 3 relevant ones
- Max 3 emojis total
- Make the reader want to click the live demo

Respond with ONLY the LinkedIn post text. No quotes, no explanation, just the post."""

    try:
        caption = _call_gemini(prompt, temperature=0.7, max_tokens=1024)

        # Remove wrapping quotes if present
        if caption.startswith('"') and caption.endswith('"'):
            caption = caption[1:-1]

        log(f"  LinkedIn caption generated ({len(caption.split())} words)")
        return caption

    except Exception as e:
        log(f"  Caption generation failed: {e}")
        return f"""Just shipped a new project — {project_data['project_title']}!

{project_data['description']}

Built entirely with HTML, CSS, and vanilla JavaScript. No frameworks, just fundamentals. Currently in my first year of B.Tech Computer Engineering at CHARUSAT.

Check it out:
Live: {vercel_url}
Code: {github_url}

#buildinpublic #webdev #javascript #opensource #coding"""


# ════════════════════════════════════════════════════════════
# STEP 5 — LINKEDIN AUTO-POSTING
# ════════════════════════════════════════════════════════════

def post_to_linkedin(caption: str) -> dict:
    """
    Post directly to LinkedIn using the REST Posts API.

    Args:
        caption: The post text to publish

    Returns:
        dict with 'success' (bool), 'post_id' (str or None), 'error' (str or None)
    """
    log("Step 5: Posting to LinkedIn...")

    if not LINKEDIN_ACCESS_TOKEN or not LINKEDIN_PERSON_URN:
        log("  LinkedIn credentials not configured — skipping post")
        return {"success": False, "post_id": None, "error": "LinkedIn credentials not set"}

    headers = {
        "Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": LINKEDIN_VERSION,
    }

    payload = {
        "author": LINKEDIN_PERSON_URN,
        "commentary": caption,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
    }

    try:
        resp = requests.post(
            f"{LINKEDIN_API}/rest/posts",
            headers=headers,
            json=payload,
        )

        if resp.status_code == 201:
            # LinkedIn returns the post URN in the x-restli-id header
            post_id = resp.headers.get("x-restli-id", "unknown")
            log(f"  LinkedIn post published successfully! Post ID: {post_id}")
            return {"success": True, "post_id": post_id, "error": None}

        elif resp.status_code == 401:
            error_msg = "LinkedIn access token expired. Re-run setup_linkedin.py to get a new token."
            log(f"  TOKEN EXPIRED: {error_msg}")
            return {"success": False, "post_id": None, "error": error_msg}

        elif resp.status_code == 429:
            error_msg = f"LinkedIn rate limit hit. Try again later."
            log(f"  RATE LIMITED: {resp.text[:200]}")
            return {"success": False, "post_id": None, "error": error_msg}

        else:
            error_msg = f"LinkedIn API error {resp.status_code}: {resp.text[:300]}"
            log(f"  FAILED: {error_msg}")
            return {"success": False, "post_id": None, "error": error_msg}

    except Exception as e:
        error_msg = f"LinkedIn request failed: {str(e)}"
        log(f"  ERROR: {error_msg}")
        return {"success": False, "post_id": None, "error": error_msg}


# ════════════════════════════════════════════════════════════
# STEP 6 — EMAIL NOTIFICATION (optional backup)
# ════════════════════════════════════════════════════════════

def send_email(project_data: dict, github_url: str, vercel_url: str,
               caption: str, linkedin_result: dict) -> None:
    """
    Send confirmation email. This is a backup notification — if it fails,
    the pipeline continues normally.
    """
    log("Step 6: Sending email notification...")

    now = datetime.now(IST)
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S IST")

    # Calculate next run date
    day = now.day
    if day < 15:
        next_run = now.replace(day=15)
    else:
        if now.month == 12:
            next_run = now.replace(year=now.year + 1, month=1, day=1)
        else:
            next_run = now.replace(month=now.month + 1, day=1)
    next_run_date = next_run.strftime("%B %d, %Y")

    features = "\n".join(f"- {f}" for f in project_data.get("key_features", []))
    tech = ", ".join(project_data.get("tech_used", []))

    # LinkedIn status for email
    if linkedin_result.get("success"):
        li_status = f"POSTED (Post ID: {linkedin_result.get('post_id', 'N/A')})"
    else:
        li_status = f"FAILED — {linkedin_result.get('error', 'Unknown error')}"

    subject = f"New project live: {project_data['project_title']}"

    body = f"""Hey Vedant,

Your auto-pipeline just shipped a new project.

PROJECT DETAILS
Name: {project_data['project_title']}
What it does: {project_data['description']}
Live URL: {vercel_url}
GitHub: {github_url}

Key features:
{features}

Tech used: {tech}

LINKEDIN STATUS: {li_status}

LINKEDIN CAPTION:
{caption}

Pipeline completed: {timestamp}
Next run: {next_run_date}"""

    try:
        _send_smtp_email(subject, body)
        log("  Email sent")
    except Exception as e:
        # Email failure is NOT critical — just log it
        log(f"  Email failed (non-critical): {e}")


def send_failure_email(step: str, error: str) -> None:
    """Send a failure notification email. Non-blocking — logs fallback on failure."""
    log(f"Sending failure email for {step}...")

    timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    subject = f"Pipeline failed at {step}"

    body = f"""Pipeline Error Report

Failed at: {step}
Timestamp: {timestamp}

Error:
{error}

Check logs: https://github.com/{GITHUB_USERNAME}/auto-project-pipeline/actions"""

    try:
        _send_smtp_email(subject, body)
        log("  Failure email sent")
    except Exception as e:
        log(f"  Could not send failure email: {e}")
        log(f"  Step: {step}")
        log(f"  Error: {error}")


def _send_smtp_email(subject: str, body: str) -> None:
    """Send email via Gmail SMTP with STARTTLS on port 587."""
    if not GMAIL_APP_PASSWORD:
        raise RuntimeError("GMAIL_APP_PASSWORD not set")

    msg = MIMEMultipart()
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(EMAIL_FROM, GMAIL_APP_PASSWORD)
        server.send_message(msg)


# ════════════════════════════════════════════════════════════
# STEP 7 — SAVE PROJECTS LOG
# ════════════════════════════════════════════════════════════

def save_projects_log(project_data: dict, github_url: str, vercel_url: str,
                      linkedin_result: dict) -> None:
    """Append new project entry to projects_log.json."""
    log("Saving project to log...")

    projects = load_projects_log()
    projects.append({
        "date": datetime.now(IST).strftime("%Y-%m-%d"),
        "project_name": project_data["project_name"],
        "project_title": project_data["project_title"],
        "category": project_data.get("category", "Unknown"),
        "github_url": github_url,
        "vercel_url": vercel_url,
        "linkedin_posted": linkedin_result.get("success", False),
        "linkedin_post_id": linkedin_result.get("post_id"),
    })

    with open(PROJECTS_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump({"projects": projects}, f, indent=2, ensure_ascii=False)

    log(f"  Project log updated ({len(projects)} total)")


# ════════════════════════════════════════════════════════════
# MAIN PIPELINE ORCHESTRATOR
# ════════════════════════════════════════════════════════════

def run_pipeline() -> None:
    """
    Orchestrate the full pipeline:
    1. Generate project → 2. Create GitHub repo → 3. Deploy to Vercel →
    4. Generate LinkedIn caption → 5. Post to LinkedIn → 6. Send email →
    7. Save log

    Each step is wrapped in try/except. LinkedIn and email failures do NOT
    stop the pipeline.
    """
    log("=" * 60)
    log("AUTO PROJECT PIPELINE v2 — STARTING")
    log(f"Test mode: {TEST_MODE}")
    log("=" * 60)

    github_url = ""
    vercel_url = ""
    project_data = None
    linkedin_result = {"success": False, "post_id": None, "error": "Not attempted"}

    # ── Step 1: Generate project ──
    try:
        previous_projects = load_projects_log()
        project_data = generate_project(previous_projects)
    except Exception as e:
        send_failure_email("Step 1: Project Generation", str(e))
        sys.exit(1)

    # ── Step 2: Create GitHub repo ──
    if TEST_MODE:
        log("TEST MODE: Skipping GitHub repo creation")
        github_url = "https://github.com/AmateurCoder9/test-project"
    else:
        try:
            github_url = create_github_repo(project_data)
        except Exception as e:
            send_failure_email("Step 2: GitHub Repo Creation", str(e))
            sys.exit(1)

    # ── Step 3: Deploy to Vercel ──
    if TEST_MODE:
        log("TEST MODE: Skipping Vercel deployment")
        vercel_url = "https://test-project.vercel.app"
    else:
        try:
            vercel_url = deploy_to_vercel(project_data["project_name"])
            update_readme_with_url(project_data["project_name"], project_data, vercel_url)
        except Exception as e:
            log(f"  Vercel deployment failed: {e}")
            vercel_url = "Deployment failed — check vercel.com"

    # ── Step 4: Generate LinkedIn caption ──
    try:
        caption = generate_linkedin_caption(project_data, github_url, vercel_url)
    except Exception as e:
        log(f"  Caption generation failed: {e}")
        caption = (f"Just shipped: {project_data['project_title']}! "
                   f"Check it out: {vercel_url} | Code: {github_url} "
                   f"#buildinpublic #webdev")

    # ── Step 5: Post to LinkedIn ──
    if TEST_MODE:
        log("TEST MODE: Skipping LinkedIn post")
        log(f"  Caption would be:\n{caption}")
        linkedin_result = {"success": False, "post_id": None, "error": "Test mode"}
    else:
        try:
            linkedin_result = post_to_linkedin(caption)
        except Exception as e:
            log(f"  LinkedIn posting failed: {e}")
            linkedin_result = {"success": False, "post_id": None, "error": str(e)}

    # ── Step 6: Send email (optional backup) ──
    try:
        send_email(project_data, github_url, vercel_url, caption, linkedin_result)
    except Exception as e:
        log(f"  Email failed (non-critical): {e}")

    # ── Step 7: Save project log ──
    try:
        if not TEST_MODE:
            save_projects_log(project_data, github_url, vercel_url, linkedin_result)
        else:
            log("TEST MODE: Skipping project log save")
    except Exception as e:
        log(f"  Failed to save project log: {e}")

    # ── Done ──
    log("=" * 60)
    log("AUTO PROJECT PIPELINE v2 — COMPLETED")
    log(f"  Project:  {project_data['project_title']}")
    log(f"  GitHub:   {github_url}")
    log(f"  Vercel:   {vercel_url}")
    log(f"  LinkedIn: {'POSTED' if linkedin_result.get('success') else 'NOT POSTED — ' + linkedin_result.get('error', '')}")
    log("=" * 60)


if __name__ == "__main__":
    run_pipeline()
