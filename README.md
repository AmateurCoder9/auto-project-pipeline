# 🚀 Auto Project Pipeline

Fully automated biweekly project generation and deployment pipeline. Every 2 weeks, this pipeline automatically:

1. **Generates** a high-quality HTML/CSS/JS project using Google Gemini API
2. **Creates** a public GitHub repository and pushes the code
3. **Deploys** to Vercel and gets a live URL
4. **Generates** a LinkedIn caption using Gemini API
5. **Sends** an email with everything ready to post

Zero input required except manually posting the LinkedIn caption.

## 🗓️ Schedule

Runs automatically on the **1st and 15th of every month** at **9:30 AM IST** (4:00 AM UTC).

Can also be triggered manually from the [Actions tab](../../actions).

## 🔧 Setup

### 1. Add GitHub Secrets

Go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret Name | Where to Get It |
|---|---|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com) → Get API Key |
| `GMAIL_APP_PASSWORD` | [Google Account](https://myaccount.google.com/apppasswords) → Security → App Passwords |
| `VERCEL_TOKEN` | [Vercel](https://vercel.com/account/tokens) → Settings → Tokens → Create (name: `github-pipeline`) |

> **Note:** `GITHUB_TOKEN` is automatically provided by GitHub Actions — no setup needed.

### 2. Verify Vercel-GitHub Integration

Make sure the [Vercel GitHub Integration](https://vercel.com/integrations/github) is installed on your GitHub account.

### 3. Trigger a Test Run

1. Go to the [Actions tab](../../actions)
2. Click **Auto Project Pipeline** in the left sidebar
3. Click **Run workflow**
4. Set `test_mode` to `true` for a dry run (skips GitHub repo creation and Vercel deployment)
5. Click **Run workflow**

## 📁 File Structure

```
auto-project-pipeline/
├── .github/
│   └── workflows/
│       └── autoproject.yml      # GitHub Actions workflow
├── pipeline.py                   # Main pipeline script
├── requirements.txt              # Python dependencies
├── projects_log.json             # Tracks all generated projects
└── README.md                     # This file
```

## 🛠️ Tech Stack

- **Python 3.11** — Pipeline orchestration
- **Google Gemini API** (`google-genai` SDK) — Project & caption generation
- **GitHub REST API** — Repository creation and code pushing
- **Vercel API** — Deployment and hosting
- **Gmail SMTP** — Email notifications

## 📋 Project Categories

The pipeline rotates through four categories to keep projects diverse:

| Category | Theme | Examples |
|---|---|---|
| **A** | Gujarat & India Civic Tools | Bus routes, holiday calendars, pincode lookup |
| **B** | Daily Life Utility Tools | EMI calculator, fuel prices, bill calculator |
| **C** | Student & Developer Tools | CGPA converter, Git cheatsheet, regex tester |
| **D** | Fun & Creative Tools | Gujarati recipes, cricket quiz, name meanings |

## 🔍 Error Handling

- **Gemini invalid JSON** → Retries once, sends failure email if still broken
- **GitHub repo name taken** → Appends `-v2` and retries
- **Vercel deployment fails** → Continues with GitHub URL only
- **Email fails** → Prints everything to GitHub Actions log as fallback
- **API rate limit** → Waits 60 seconds, retries once

## 👨‍💻 Author

Built by [Vedant Kapadia](https://github.com/AmateurCoder9)
B.Tech Computer Engineering, Year 1 @ CHARUSAT, Gujarat, India

---

*Part of a biweekly build-in-public challenge — automating the boring parts so I can focus on building.*
