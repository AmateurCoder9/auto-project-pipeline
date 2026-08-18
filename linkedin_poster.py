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

import datetime as dt
import os

import requests

from common import AuthError, RateLimitError, api_retry, check_response, get_logger

logger = get_logger(__name__)

LINKEDIN_API_VERSION = "202401"
POSTS_URL = "https://api.linkedin.com/rest/posts"


class LinkedInTokenExpired(AuthError):
    """Raised specifically on 401s so callers can distinguish from other failures."""


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


def _check_linkedin_response(resp: requests.Response, context: str) -> None:
    if resp.status_code == 401:
        raise LinkedInTokenExpired("LinkedIn returned 401 Unauthorized — the access token has expired or was revoked.")
    if resp.status_code == 403:
        raise AuthError(
            "LinkedIn returned 403 Forbidden — check that the app still "
            "has the 'Share on LinkedIn' product approved under the "
            "Products tab at https://developer.linkedin.com."
        )
    check_response(resp, context)


@api_retry
def upload_image_asset(access_token: str, person_urn: str, image_path: str) -> str | None:
    """
    Registers and uploads an image file to LinkedIn Assets API.
    Returns the media asset URN (e.g. 'urn:li:digitalmediaAsset:C56...') or None if failed.
    """
    if not image_path or not os.path.exists(image_path):
        return None

    register_url = "https://api.linkedin.com/v2/assets?action=registerUpload"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    body = {
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": person_urn,
            "serviceRelationships": [
                {
                    "relationshipType": "OWNER",
                    "identifier": "urn:li:userGeneratedContent"
                }
            ]
        }
    }
    
    reg_resp = requests.post(register_url, headers=headers, json=body, timeout=30)
    _check_linkedin_response(reg_resp, "Image registration")
    
    reg_data = reg_resp.json().get("value", {})
    asset_urn = reg_data.get("asset")
    upload_mech = reg_data.get("uploadMechanism", {})
    upload_url = upload_mech.get("com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest", {}).get("uploadUrl")

    if not asset_urn or not upload_url:
        logger.error("Image registration succeeded but no asset_urn or upload_url returned.")
        return None

    with open(image_path, "rb") as img_file:
        upload_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "image/png"
        }
        up_resp = requests.put(upload_url, headers=upload_headers, data=img_file, timeout=60)
        _check_linkedin_response(up_resp, "Image binary upload")

    logger.info(f"Image asset uploaded successfully: {asset_urn}")
    return asset_urn


@api_retry
def _call_ugc_posts(access_token: str, author_urn: str, caption: str, image_asset_urn: str | None) -> dict:
    ugc_url = "https://api.linkedin.com/v2/ugcPosts"
    ugc_headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }

    if image_asset_urn:
        share_content = {
            "shareCommentary": {"text": caption},
            "shareMediaCategory": "IMAGE",
            "media": [
                {
                    "status": "READY",
                    "description": {"text": "Project Screenshot Preview"},
                    "media": image_asset_urn,
                    "title": {"text": "Project Preview"}
                }
            ]
        }
    else:
        share_content = {
            "shareCommentary": {"text": caption},
            "shareMediaCategory": "NONE"
        }

    ugc_body = {
        "author": author_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": share_content
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        }
    }

    resp = requests.post(ugc_url, headers=ugc_headers, json=ugc_body, timeout=30)
    _check_linkedin_response(resp, "v2/ugcPosts")
    
    data = resp.json()
    post_id = data.get("id", "")
    numeric_id = post_id.split(":")[-1] if post_id else ""
    post_url = f"https://www.linkedin.com/feed/update/urn:li:ugcPost:{numeric_id}/" if numeric_id else None
    logger.info(f"(v2/ugcPosts) Post succeeded: {post_url}")
    return {"success": True, "post_url": post_url, "error": None}


@api_retry
def _call_rest_posts(access_token: str, author_urn: str, caption: str) -> dict:
    rest_headers = {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": LINKEDIN_API_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }
    rest_body = {
        "author": author_urn,
        "commentary": caption,
        "visibility": "PUBLIC",
        "lifecycleState": "PUBLISHED",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
    }

    resp = requests.post(POSTS_URL, headers=rest_headers, json=rest_body, timeout=30)
    _check_linkedin_response(resp, "rest/posts")

    post_id = resp.headers.get("x-restli-id", "")
    numeric_id = post_id.split(":")[-1] if post_id else ""
    post_url = f"https://www.linkedin.com/feed/update/urn:li:ugcPost:{numeric_id}/" if numeric_id else None
    logger.info(f"(rest/posts) Post succeeded: {post_url or '(no URL returned)'}")
    return {"success": True, "post_url": post_url, "error": None}


def post_to_linkedin(
    caption: str,
    access_token: str,
    person_urn: str,
    image_path: str | None = None,
) -> dict:
    """
    Publishes a text or image post to the given person's LinkedIn profile.
    Tries /v2/ugcPosts first (standard for personal posts), then falls back to /rest/posts.

    Returns a dict: {"success": bool, "post_url": str | None, "error": str | None}
    """
    if not person_urn.startswith("urn:li:"):
        person_urn = f"urn:li:person:{person_urn}"

    # Diagnostics: Verify who the token belongs to and check /v2/me
    real_person_urn = person_urn
    try:
        me_resp = requests.get(
            "https://api.linkedin.com/v2/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if me_resp.status_code == 200:
            me_data = me_resp.json()
            me_id = me_data.get('id')
            if me_id:
                real_person_urn = f"urn:li:person:{me_id}"
                logger.info(f"/v2/me Member ID: {me_id} -> URN: {real_person_urn}")
        else:
            logger.warning(f"/v2/me status: {me_resp.status_code} ({me_resp.text[:150]})")
    except Exception as me_err:
        logger.error(f"/v2/me error: {me_err}")

    try:
        uinfo_resp = requests.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if uinfo_resp.status_code == 200:
            uinfo = uinfo_resp.json()
            logger.info(f"Authenticated Name: {uinfo.get('name')} | Sub: {uinfo.get('sub')} | Target Person URN: {person_urn}")
        else:
            logger.warning(f"/v2/userinfo status: {uinfo_resp.status_code}")
    except Exception as diag_err:
        logger.error(f"Profile check error: {diag_err}")

    author_urn = real_person_urn

    try:
        image_asset_urn = None
        if image_path:
            try:
                image_asset_urn = upload_image_asset(access_token, author_urn, image_path)
            except AuthError:
                raise
            except Exception as e:
                logger.error(f"Failed to upload image asset, proceeding without image: {e}")
                image_asset_urn = None

        try:
            return _call_ugc_posts(access_token, author_urn, caption, image_asset_urn)
        except Exception as e:
            # Let AuthError and RateLimitError bubble up immediately without fallback
            if isinstance(e, (AuthError, RateLimitError)):
                raise
            # If it's a RetryError that contains a 429, we'll catch it at the top level
            if getattr(e, "status_code", None) == 429:
                raise
                
            logger.warning(f"v2/ugcPosts error ({type(e).__name__}: {e}), falling back to /rest/posts...")
            return _call_rest_posts(access_token, author_urn, caption)

    except LinkedInTokenExpired as e:
        logger.error(f"Token expired: {e}")
        return {"success": False, "post_url": None, "error": str(e)}
    except AuthError as e:
        logger.error(f"Auth error: {e}")
        return {"success": False, "post_url": None, "error": str(e)}
    except RateLimitError as e:
        logger.error(f"Rate limit error: {e}")
        return {"success": False, "post_url": None, "error": str(e)}
    except Exception as e:
        if getattr(e, "status_code", None) == 429:
            rl_err = RateLimitError("LinkedIn returned 429 rate-limited.")
            logger.error(str(rl_err))
            return {"success": False, "post_url": None, "error": str(rl_err)}
            
        err_msg = f"Network error contacting LinkedIn: {e}"
        logger.error(err_msg)
        return {"success": False, "post_url": None, "error": err_msg}
