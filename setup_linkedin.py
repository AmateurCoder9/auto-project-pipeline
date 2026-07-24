"""
LinkedIn OAuth Setup Helper
============================
One-time setup script to obtain a LinkedIn access token for automated posting.

How it works:
1. You provide your LinkedIn app's Client ID and Client Secret
2. It opens your browser to LinkedIn's authorization page
3. You click "Allow"
4. LinkedIn redirects to localhost where this script captures the auth code
5. Script exchanges the code for an access token
6. Prints the token, person URN, and expiry — paste these as GitHub secrets

Usage:
    python setup_linkedin.py

Prerequisites:
    - A LinkedIn Developer App (create at https://developer.linkedin.com)
    - "Share on LinkedIn" product enabled on your app
    - Redirect URL set to: http://localhost:8585/callback
"""

import http.server
import json
import os
import sys
import threading
import time
import urllib.parse
import webbrowser

try:
    import requests
except ImportError:
    print("Installing requests...")
    os.system(f"{sys.executable} -m pip install requests")
    import requests


# ════════════════════════════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════════════════════════════

REDIRECT_URI = "http://localhost:8585/callback"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
PROFILE_URL = "https://api.linkedin.com/v2/userinfo"
SCOPES = "openid profile w_member_social"
LOCAL_PORT = 8585


def main():
    print("=" * 60)
    print("LinkedIn OAuth Setup for Auto Project Pipeline")
    print("=" * 60)
    print()
    print("Before running this script, make sure you have:")
    print("  1. Created a LinkedIn Developer App at:")
    print("     https://developer.linkedin.com/")
    print("  2. Requested 'Share on LinkedIn' product")
    print("  3. Added this redirect URL in your app's Auth settings:")
    print(f"     {REDIRECT_URI}")
    print()

    # Get credentials
    client_id = input("Enter your LinkedIn Client ID: ").strip()
    if not client_id:
        print("Error: Client ID is required.")
        sys.exit(1)

    client_secret = input("Enter your LinkedIn Client Secret: ").strip()
    if not client_secret:
        print("Error: Client Secret is required.")
        sys.exit(1)

    print()
    print("Opening your browser to LinkedIn authorization page...")
    print("Please click 'Allow' to grant access.")
    print()

    # Build authorization URL
    auth_params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": "auto_project_pipeline_setup",
    })
    auth_full_url = f"{AUTH_URL}?{auth_params}"

    # Set up local server to capture the callback
    auth_code_holder = {"code": None, "error": None}

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)

            if "code" in params:
                auth_code_holder["code"] = params["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"""
                <html><body style="font-family:sans-serif;text-align:center;padding:50px;">
                <h1 style="color:green;">Authorization Successful!</h1>
                <p>You can close this tab and return to the terminal.</p>
                </body></html>
                """)
            elif "error" in params:
                auth_code_holder["error"] = params.get("error_description", params["error"])[0]
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(f"""
                <html><body style="font-family:sans-serif;text-align:center;padding:50px;">
                <h1 style="color:red;">Authorization Failed</h1>
                <p>{auth_code_holder['error']}</p>
                </body></html>
                """.encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass  # Suppress server logs

    server = http.server.HTTPServer(("localhost", LOCAL_PORT), CallbackHandler)
    server.timeout = 120  # 2 minute timeout

    # Open browser
    webbrowser.open(auth_full_url)

    # Wait for callback
    print(f"Waiting for authorization (timeout: 2 minutes)...")
    while auth_code_holder["code"] is None and auth_code_holder["error"] is None:
        server.handle_request()

    server.server_close()

    if auth_code_holder["error"]:
        print(f"\nError: {auth_code_holder['error']}")
        sys.exit(1)

    auth_code = auth_code_holder["code"]
    print("Authorization code received!")
    print()

    # Exchange code for access token
    print("Exchanging authorization code for access token...")
    token_resp = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": auth_code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
    })

    if token_resp.status_code != 200:
        print(f"Error getting token: {token_resp.status_code}")
        print(token_resp.text)
        sys.exit(1)

    token_data = token_resp.json()
    access_token = token_data["access_token"]
    expires_in = token_data.get("expires_in", 5184000)  # Default 60 days

    # Calculate expiry date
    import datetime
    expiry_date = datetime.datetime.now() + datetime.timedelta(seconds=expires_in)
    expiry_str = expiry_date.strftime("%B %d, %Y")

    print("Access token obtained!")
    print()

    # Get person URN (LinkedIn user ID)
    print("Fetching your LinkedIn profile info...")
    profile_resp = requests.get(PROFILE_URL, headers={
        "Authorization": f"Bearer {access_token}",
    })

    if profile_resp.status_code != 200:
        print(f"Warning: Could not fetch profile: {profile_resp.status_code}")
        print("You'll need to find your LinkedIn person URN manually.")
        person_urn = "urn:li:person:YOUR_ID_HERE"
    else:
        profile = profile_resp.json()
        person_id = profile.get("sub", "")
        person_urn = f"urn:li:person:{person_id}"
        name = profile.get("name", "Unknown")
        print(f"  Logged in as: {name}")

    # Print results
    print()
    print("=" * 60)
    print("SETUP COMPLETE — Add these as GitHub Secrets:")
    print("=" * 60)
    print()
    print(f"Go to: https://github.com/AmateurCoder9/auto-project-pipeline/settings/secrets/actions")
    print()
    print(f"Secret: LINKEDIN_ACCESS_TOKEN")
    print(f"Value:  {access_token}")
    print()
    print(f"Secret: LINKEDIN_PERSON_URN")
    print(f"Value:  {person_urn}")
    print()
    print(f"Secret: LINKEDIN_CLIENT_ID")
    print(f"Value:  {client_id}")
    print()
    print(f"Secret: LINKEDIN_CLIENT_SECRET")
    print(f"Value:  {client_secret}")
    print()
    print(f"Token expires: {expiry_str}")
    print(f"(Re-run this script before then to get a new token)")
    print("=" * 60)


if __name__ == "__main__":
    main()
