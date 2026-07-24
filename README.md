# Auto Project Pipeline

A fully automated pipeline that builds, deploys, and publishes a new web project every 2 weeks — completely hands-free.

## What it does

Every 1st and 15th of the month, a GitHub Action runs the pipeline, which:
1. 🤖 **Generates** a complete, working HTML/CSS/JS web app using Google Gemini API (gemini-2.0-flash / flash-lite)
2. 📦 **Creates** a public GitHub repo with the code + README
3. 🚀 **Deploys** it live to Vercel
4. ✍️ **Writes** a LinkedIn caption using Gemini
5. 📱 **Posts it directly to LinkedIn** — fully automated via the LinkedIn REST API
6. 📧 **Sends a confirmation email** (as backup)

---

## 🛠️ One-Time Setup Instructions

You must configure a few secrets in GitHub for this pipeline to work.

### Step 1: Get Standard Secrets

Add these 3 secrets to your GitHub repository (**Settings > Secrets and variables > Actions > New repository secret**):

| Secret Name | Where to get it |
|-------------|-----------------|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com) - Needs a project with billing enabled for higher quotas, or a fresh free tier project. |
| `VERCEL_TOKEN` | [Vercel Tokens](https://vercel.com/account/tokens) - Create a token named `github-pipeline` (Scope: Full Account). |
| `GMAIL_APP_PASSWORD`| [Google Account](https://myaccount.google.com/apppasswords) - Must have 2-Step Verification ON. Generate a new App Password (no spaces). |

### Step 2: LinkedIn API Setup

Because LinkedIn requires user authentication (OAuth 2.0) to post, you must complete a one-time setup to get an access token.

1. **Create a LinkedIn App:**
   - Go to the [LinkedIn Developer Portal](https://developer.linkedin.com) and click **Create App**.
   - Name it `Auto Project Pipeline` (link to your company page or create one).
   - Go to the **Products** tab and request access to **Share on LinkedIn** (approved instantly).
   - Go to the **Auth** tab. Copy your **Client ID** and **Client Secret**.
   - Add this Redirect URL: `http://localhost:8585/callback`

2. **Generate the Access Token:**
   - Clone this repository to your local machine.
   - Run the local setup script:
     ```bash
     pip install requests
     python setup_linkedin.py
     ```
   - Enter your Client ID and Client Secret when prompted.
   - A browser window will open. Click **Allow**.
   - The script will exchange the auth code for a 60-day access token and print your credentials.

3. **Add LinkedIn Secrets to GitHub:**
   Add these 4 new secrets to your GitHub Actions:
   - `LINKEDIN_ACCESS_TOKEN`
   - `LINKEDIN_PERSON_URN`
   - `LINKEDIN_CLIENT_ID` (optional, but good for reference)
   - `LINKEDIN_CLIENT_SECRET` (optional, but good for reference)

> **⚠️ Token Expiry:** LinkedIn access tokens expire every **60 days**. You will need to re-run `python setup_linkedin.py` every two months to generate a new token and update the `LINKEDIN_ACCESS_TOKEN` secret in GitHub.

---

## 🚀 How to Run Manually

To test the pipeline without waiting for the scheduled date:
1. Go to the **Actions** tab in this repository.
2. Select **Auto Project Pipeline** on the left.
3. Click **Run workflow** on the right.
4. Set `test_mode` to `true` if you only want to test the Gemini generation without creating repos or posting to LinkedIn. Set to `false` for a full end-to-end run.
5. Click **Run workflow**.

---
*Built with Python, GitHub Actions, Vercel, and Gemini API.*
