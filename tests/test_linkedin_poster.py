"""
test_linkedin_poster.py - Unit tests for linkedin_poster module
"""

import datetime as dt

import responses

from linkedin_poster import (
    _days_until_expiry,
    check_token_expiry_warning,
    post_to_linkedin,
)


def test_days_until_expiry():
    future_date = (dt.datetime.now() + dt.timedelta(days=10)).isoformat()
    days = _days_until_expiry(future_date)
    assert days is not None
    assert 9 <= days <= 10

def test_token_expiry_warning_trigger(monkeypatch):
    soon_date = (dt.datetime.now() + dt.timedelta(days=3)).isoformat()
    monkeypatch.setenv("LINKEDIN_TOKEN_EXPIRES_AT", soon_date)
    warning = check_token_expiry_warning()
    assert warning is not None
    assert "expires in" in warning

@responses.activate
def test_post_to_linkedin_handles_error_gracefully():
    # Mock /v2/me to 401
    responses.add(
        responses.GET,
        "https://api.linkedin.com/v2/me",
        status=401,
        json={"message": "Unauthorized"}
    )
    responses.add(
        responses.GET,
        "https://api.linkedin.com/v2/userinfo",
        status=401,
        json={"message": "Unauthorized"}
    )
    responses.add(
        responses.POST,
        "https://api.linkedin.com/v2/ugcPosts",
        status=401,
        json={"message": "Unauthorized"}
    )
    responses.add(
        responses.POST,
        "https://api.linkedin.com/rest/posts",
        status=401,
        json={"message": "Unauthorized"}
    )

    res = post_to_linkedin("Test caption", "invalid_token", "urn:li:person:12345")
    assert res["success"] is False
    assert res["post_url"] is None
    assert "LinkedIn returned 401" in res["error"] or "Unauthorized" in res["error"]
