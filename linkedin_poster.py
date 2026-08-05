"""
linkedin_poster.py

Posts to LinkedIn via the REST Posts API. LinkedIn's OAuth access tokens
last ~60 days and there is currently no refresh-token flow for most
developer apps, so expiry is a REAL recurring manual step (re-run
setup_linkedin.py, update the GitHub secret). This module cannot make
that go away — what it does is:

  1. Warn proactively when the token is within ~7 days of expiring
     (if LINKEDIN_TOKEN_EXPIRES_AT is set as a secret alongside the
     token, see setup_linkedin.py output).
  2. On an actual 401, fail with an unmistakable message rather than
     a generic stack trace, so the email/log makes the next action
     obvious instead of cryptic.
  3. Never crash the whole pipeline — a failed LinkedIn post should
     not prevent the email backup from going out.
"""

import os
import sys
import datetime as dt
import requests

LINKEDIN_API_VERSION = "202401"
POSTS_URL = "https://api.linkedin.com/rest/posts"


class LinkedInTokenExpired(Exception):
    """Raised specifically on 401s so callers can distinguish from other failures."""
    pass


def _days_until_expiry(expires_at_iso: str | None) -> int | None:
    if not expires_at_iso:
        return None
    try:
        expires = dt.datetime.fromisoformat(expires_at_iso)
    except ValueError:
        return None
    now = dt.datetime.now(expires.tzinfo) if expires.tzinfo else dt.datetime.now()
    return (expires - now).days


def check_token_expiry_warning() -> str | None:
    """
    Returns a warning string if the token is close to expiring, else None.
    Reads LINKEDIN_TOKEN_EXPIRES_AT from env if present (optional; set
    this alongside LINKEDIN_ACCESS_TOKEN as a GitHub secret using the
    date setup_linkedin.py prints).
    """
    expires_at = os.environ.get("LINKEDIN_TOKEN_EXPIRES_AT")
    days_left = _days_until_expiry(expires_at)
    if days_left is None:
        return None
    if days_left <= 7:
        return (
            f"LinkedIn token expires in {days_left} day(s). "
            f"Run `python setup_linkedin.py` locally and update the "
            f"LINKEDIN_ACCESS_TOKEN / LINKEDIN_TOKEN_EXPIRES_AT secrets "
            f"before it expires, or the next post will fail."
        )
    return None


def post_to_linkedin(
    caption: str,
    access_token: str,
    person_urn: str,
) -> dict:
    """
    Publishes a text post to the given person's LinkedIn profile.
    Tries /v2/ugcPosts first (standard for personal posts), then falls back to /rest/posts.

    Returns a dict: {"success": bool, "post_url": str | None, "error": str | None}
    """
    if not person_urn.startswith("urn:li:"):
        person_urn = f"urn:li:person:{person_urn}"

    # Method 1: /v2/ugcPosts (proven for personal profiles)
    ugc_url = "https://api.linkedin.com/v2/ugcPosts"
    ugc_headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }
    ugc_body = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": caption
                },
                "shareMediaCategory": "NONE"
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        }
    }

    try:
        resp = requests.post(ugc_url, headers=ugc_headers, json=ugc_body, timeout=30)
        if resp.status_code in (200, 201):
            data = resp.json()
            post_id = data.get("id", "")
            numeric_id = post_id.split(":")[-1] if post_id else ""
            post_url = f"https://www.linkedin.com/feed/update/urn:li:ugcPost:{numeric_id}/" if numeric_id else None
            print(f"[linkedin_poster] (v2/ugcPosts) Post succeeded: {post_url}", file=sys.stderr)
            return {"success": True, "post_url": post_url, "error": None}
        else:
            print(f"[linkedin_poster] v2/ugcPosts returned {resp.status_code}: {resp.text[:300]}, falling back to /rest/posts...", file=sys.stderr)
    except Exception as e:
        print(f"[linkedin_poster] v2/ugcPosts error ({e}), falling back to /rest/posts...", file=sys.stderr)

    # Method 2: /rest/posts (fallback)
    rest_headers = {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": LINKEDIN_API_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }
    rest_body = {
        "author": person_urn,
        "commentary": caption,
        "visibility": "PUBLIC",
        "lifecycleState": "PUBLISHED",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
    }

    try:
        resp = requests.post(POSTS_URL, headers=rest_headers, json=rest_body, timeout=30)
    except requests.RequestException as e:
        return {"success": False, "post_url": None,
                "error": f"Network error contacting LinkedIn: {e}"}

    if resp.status_code == 401:
        msg = (
            "LinkedIn returned 401 Unauthorized — the access token has "
            "expired or was revoked."
        )
        print(f"[linkedin_poster] {msg}", file=sys.stderr)
        return {"success": False, "post_url": None, "error": msg}

    if resp.status_code == 403:
        msg = (
            "LinkedIn returned 403 Forbidden — check that the app still "
            "has the 'Share on LinkedIn' product approved under the "
            "Products tab at https://developer.linkedin.com."
        )
        print(f"[linkedin_poster] {msg}", file=sys.stderr)
        return {"success": False, "post_url": None, "error": msg}

    if resp.status_code == 429:
        msg = "LinkedIn returned 429 rate-limited."
        print(f"[linkedin_poster] {msg}", file=sys.stderr)
        return {"success": False, "post_url": None, "error": msg}

    if resp.status_code not in (200, 201):
        msg = f"LinkedIn returned HTTP {resp.status_code}: {resp.text[:500]}"
        print(f"[linkedin_poster] {msg}", file=sys.stderr)
        return {"success": False, "post_url": None, "error": msg}

    post_id = resp.headers.get("x-restli-id", "")
    numeric_id = post_id.split(":")[-1] if post_id else ""
    post_url = f"https://www.linkedin.com/feed/update/urn:li:ugcPost:{numeric_id}/" if numeric_id else None
    print(f"[linkedin_poster] (rest/posts) Post succeeded: {post_url or '(no URL returned)'}", file=sys.stderr)
    return {"success": True, "post_url": post_url, "error": None}
