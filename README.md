# Auto Project Pipeline v2

Runs automatically every 2 weeks (or on-demand): generates a small web
app with Gemini, pushes it to a new GitHub repo, deploys it live to
Vercel, posts about it on LinkedIn, and emails you a backup summary.

## What's actually 100% hands-free, and what isn't

Being upfront about this because the original spec assumed everything
could be zero-touch forever, and one piece genuinely can't be:

| Step | Hands-free? |
|---|---|
| Project generation (Gemini) | ✅ Fully automatic |
| GitHub repo creation | ✅ Fully automatic |
| Vercel deployment | ✅ Fully automatic |
| LinkedIn caption writing | ✅ Fully automatic |
| **LinkedIn posting** | ✅ Automatic **for 60 days at a time** |
| Email backup | ✅ Fully automatic (never blocks anything else) |

**The LinkedIn token expires roughly every 60 days and there is no
refresh-token flow available for this app type.** Every ~2 months
you will need to spend ~30 seconds running `setup_linkedin.py` again
and updating one GitHub secret. This is a LinkedIn platform limit,
not something this code can work around. The pipeline will warn you
in its logs and in the backup email starting 7 days before expiry.

If you'd rather never touch this again, the alternative is dropping
LinkedIn auto-posting and just having the caption emailed to you to
paste manually — say so and I'll strip that piece out.

## One-time setup

### 1. Gemini API key

Your previous key hit `limit: 0` — this is very likely because
`gemini-2.0-flash` (what the old pipeline called) was deprecated in
Feb 2026 and fully retired March 3, 2026, **not** a quota problem
with your account. Also note: quota is per Google Cloud *project*,
not per key — a new key from the same project inherits the same
exhausted pool.

1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. If you're not certain your key is on a fresh project, create one
   explicitly: [console.cloud.google.com](https://console.cloud.google.com)
   → project switcher (top left) → New Project → then generate a key
   while that new project is selected.
3. You do NOT need to hardcode a model name — `model_selector.py`
   asks Gemini live which models are currently free and working, and
   test-calls them in order until one succeeds. This means it keeps
   working even when Google renames or retires models again later.

### 2. GitHub Personal Access Token

**Do not name this secret `GITHUB_TOKEN`** — that name is reserved
and auto-injected by GitHub Actions itself; anything you set under
that name gets silently overridden by GitHub's own token, which
can't create new repos.

1. Go to [github.com/settings/tokens](https://github.com/settings/tokens)
2. Generate a classic token (or fine-grained with Administration:
   write + Contents: write on your account)
3. Save it as the secret `PIPELINE_GITHUB_TOKEN`

### 3. Vercel token

[vercel.com/account/tokens](https://vercel.com/account/tokens) →
save as `VERCEL_TOKEN`

### 4. Gmail app password (optional — email is just a backup)

[myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
→ save as `GMAIL_APP_PASSWORD`, and your Gmail address as `GMAIL_USER`.
Optionally set `NOTIFY_EMAIL` if you want it sent somewhere other
than that same address.

### 5. LinkedIn Developer App

1. [developer.linkedin.com](https://developer.linkedin.com) → **Create App**
2. Under **Products**, request **"Share on LinkedIn"**
3. Under **Auth**, add this exact redirect URL:
   `http://localhost:8585/callback`
4. Copy the **Client ID** and **Client Secret** — you'll need them
   for the next step, but they don't go in GitHub secrets themselves.

### 6. Run the LinkedIn setup script locally

```bash
pip install requests
python setup_linkedin.py
```

Follow the prompts — it opens your browser, you click "Allow," and it
prints three values. Copy all three into your repo's
**Settings → Secrets and variables → Actions**:

- `LINKEDIN_ACCESS_TOKEN`
- `LINKEDIN_PERSON_URN`
- `LINKEDIN_TOKEN_EXPIRES_AT`

**Repeat this step every ~60 days** when the pipeline warns you.

## All GitHub secrets, at a glance

| Secret | Where it comes from |
|---|---|
| `GEMINI_API_KEY` | aistudio.google.com/apikey |
| `PIPELINE_GITHUB_TOKEN` | github.com/settings/tokens |
| `VERCEL_TOKEN` | vercel.com/account/tokens |
| `GMAIL_USER` | your Gmail address |
| `GMAIL_APP_PASSWORD` | myaccount.google.com/apppasswords |
| `NOTIFY_EMAIL` | optional — defaults to `GMAIL_USER` |
| `LINKEDIN_ACCESS_TOKEN` | `setup_linkedin.py` output (expires ~60 days) |
| `LINKEDIN_PERSON_URN` | `setup_linkedin.py` output (permanent) |
| `LINKEDIN_TOKEN_EXPIRES_AT` | `setup_linkedin.py` output (for expiry warnings) |

## Testing before you trust it

Run it manually first with dry-run mode so nothing gets created for
real: go to the **Actions** tab → **Auto Project Pipeline** →
**Run workflow** → set `test_mode` to `true`. This exercises the
Gemini model selection and generation without touching GitHub,
Vercel, or LinkedIn — check the run's logs for the model it picked
and the generated project JSON.

Once that looks right, run it again with `test_mode` set to `false`
for a real end-to-end run, and verify:
1. A new repo appeared under your account
2. The Vercel URL in that repo's README actually loads
3. The post appeared on your LinkedIn profile
4. You got the backup email

## Files

- `pipeline.py` — orchestrates the whole run
- `model_selector.py` — finds a Gemini model that currently works,
  live-tested rather than hardcoded
- `linkedin_poster.py` — posts to LinkedIn, handles expiry clearly
- `setup_linkedin.py` — run locally every ~60 days for a new token
- `projects_log.json` — history, used to avoid repeating ideas
- `.github/workflows/autoproject.yml` — the schedule + trigger
