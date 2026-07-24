"""
setup_linkedin.py

Run this LOCALLY (not in GitHub Actions) to get a LinkedIn access token.

WHY THIS IS NEEDED, AND WHY YOU'LL RUN IT AGAIN:
LinkedIn's OAuth 2.0 requires a real browser login where you click
"Allow" — this cannot be scripted headlessly for a personal-posting app.
The resulting access token lasts ~60 days. LinkedIn does not currently
issue refresh tokens for most developer apps in this product tier, so
when the token expires, you run this script again. There is no way to
avoid this step entirely — it is a LinkedIn platform constraint, not
a limitation of this pipeline.

BEFORE RUNNING THIS:
  1. Create a LinkedIn Developer App at https://developer.linkedin.com
  2. Under "Products", request "Share on LinkedIn" (usually instant)
  3. Under "Auth", add this exact redirect URL:
       http://localhost:8585/callback
  4. Copy your Client ID and Client Secret — this script will ask for them

USAGE:
    python setup_linkedin.py
"""

import http.server
import socketserver
import urllib.parse
import webbrowser
import secrets as pysecrets
import datetime as dt
import sys
import requests

REDIRECT_URI = "http://localhost:8585/callback"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
PROFILE_URL = "https://api.linkedin.com/v2/userinfo"
SCOPES = "openid profile w_member_social"

_captured_code = {"value": None, "error": None}


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "error" in params:
            _captured_code["error"] = params.get(
                "error_description", ["Unknown error"]
            )[0]
            self._respond("Authorization failed. You can close this tab.")
        elif "code" in params:
            _captured_code["value"] = params["code"][0]
            self._respond("Authorization received! You can close this tab "
                           "and return to your terminal.")
        else:
            self._respond("Waiting for LinkedIn redirect...")

    def _respond(self, message: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(f"<html><body><h2>{message}</h2></body></html>".encode())

    def log_message(self, format, *args):
        pass  # suppress default request logging noise


def _run_local_server_until_captured():
    with socketserver.TCPServer(("localhost", 8585), _CallbackHandler) as httpd:
        print("Waiting for LinkedIn redirect on http://localhost:8585 ...")
        while _captured_code["value"] is None and _captured_code["error"] is None:
            httpd.handle_request()


def main():
    print("=" * 60)
    print("LinkedIn OAuth Setup")
    print("=" * 60)
    print()
    client_id = input("Client ID: ").strip()
    client_secret = input("Client Secret: ").strip()

    if not client_id or not client_secret:
        print("Both Client ID and Client Secret are required.", file=sys.stderr)
        sys.exit(1)

    state = pysecrets.token_urlsafe(16)
    auth_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "scope": SCOPES,
    }
    auth_url_full = f"{AUTH_URL}?{urllib.parse.urlencode(auth_params)}"

    print()
    print("Opening your browser to LinkedIn. Click 'Allow' when prompted.")
    print("If it doesn't open automatically, visit this URL manually:")
    print(auth_url_full)
    print()
    webbrowser.open(auth_url_full)

    _run_local_server_until_captured()

    if _captured_code["error"]:
        print(f"\nLinkedIn returned an error: {_captured_code['error']}",
              file=sys.stderr)
        sys.exit(1)

    code = _captured_code["value"]
    print("\nAuthorization code received. Exchanging for access token...")

    token_resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )

    if token_resp.status_code != 200:
        print(f"\nToken exchange failed (HTTP {token_resp.status_code}):",
              file=sys.stderr)
        print(token_resp.text, file=sys.stderr)
        sys.exit(1)

    token_data = token_resp.json()
    access_token = token_data["access_token"]
    expires_in_seconds = token_data.get("expires_in", 60 * 24 * 3600)
    expires_at = dt.datetime.now() + dt.timedelta(seconds=expires_in_seconds)

    print("Fetching your profile URN...")
    profile_resp = requests.get(
        PROFILE_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    if profile_resp.status_code != 200:
        print(f"\nProfile fetch failed (HTTP {profile_resp.status_code}). "
              f"You have the access token below, but need to find your "
              f"person URN manually — see LinkedIn's userinfo docs.",
              file=sys.stderr)
        person_urn = "URN_LOOKUP_FAILED_SEE_ABOVE"
    else:
        sub = profile_resp.json().get("sub", "")
        person_urn = f"urn:li:person:{sub}" if sub else "URN_NOT_FOUND"

    print()
    print("=" * 60)
    print("SUCCESS. Copy these into your GitHub repo secrets:")
    print("(Settings -> Secrets and variables -> Actions -> New repository secret)")
    print("=" * 60)
    print(f"LINKEDIN_ACCESS_TOKEN = {access_token}")
    print(f"LINKEDIN_PERSON_URN   = {person_urn}")
    print(f"LINKEDIN_TOKEN_EXPIRES_AT = {expires_at.isoformat()}")
    print("=" * 60)
    print()
    print(f"This token expires around {expires_at.strftime('%B %d, %Y')} "
          f"(~{expires_in_seconds // 86400} days from now).")
    print("The pipeline will start warning you in its logs and email 7 "
          "days before that date. When it does, run this script again.")


if __name__ == "__main__":
    main()
