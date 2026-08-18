"""
conftest.py - Pytest fixtures and mock objects for testing
"""

import pytest


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    """Ensure required environment variables are present during tests."""
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key")
    monkeypatch.setenv("VERCEL_TOKEN", "test_vercel_token")
    monkeypatch.setenv("GITHUB_TOKEN", "test_github_token")
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "test_owner")
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "test_linkedin_token")
    monkeypatch.setenv("LINKEDIN_PERSON_URN", "urn:li:person:test_person")
    monkeypatch.setenv("TEST_MODE", "false")
    monkeypatch.setenv("DRY_RUN", "true")
