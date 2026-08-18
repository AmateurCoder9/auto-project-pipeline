# Contributing to Auto Project Pipeline

Thanks for your interest in contributing! This guide covers how to set up,
test, and submit changes.

---

## Local Setup

1. **Clone the repo**
   ```bash
   git clone https://github.com/<your-fork>/auto-project-pipeline.git
   cd auto-project-pipeline
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Linux/macOS
   .venv\Scripts\activate      # Windows
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```

4. **Copy `.env.example` → `.env`** and fill in your own keys
   ```bash
   cp .env.example .env
   ```

---

## Running Without Posting to LinkedIn

Set `DRY_RUN=true` in your `.env` or export it:

```bash
DRY_RUN=true python pipeline.py
```

This runs the full pipeline (generation → GitHub repo → Vercel deploy →
screenshot) but **skips the actual LinkedIn POST**. The caption and image
path are logged so you can inspect what *would* have been posted.

If you want to skip *all* external writes (GitHub, Vercel, LinkedIn), use
`TEST_MODE=true` instead.

---

## Running Tests

```bash
pytest tests/ -v
```

All external APIs are mocked — no real network calls, no credentials needed.

---

## Code Style

We use [Ruff](https://docs.astral.sh/ruff/) for linting:

```bash
ruff check .
```

CI runs this automatically on every pull request. Please fix any lint errors
before submitting.

---

## Pull Request Process

1. Fork the repo and create a feature branch from `main`
2. Make your changes, add tests if applicable
3. Run `ruff check .` and `pytest tests/ -v` locally
4. Open a PR with a clear description of what changed and why
5. CI will run lint + tests automatically — both must pass

---

## Important Notes

- **Do not commit real credentials.** All secrets come from environment
  variables or GitHub Secrets. The `.gitignore` excludes `.env` files.
- **History rewrites**: This repo underwent a one-time history rewrite before
  going public to scrub PII. If a rewrite is ever needed again post-launch,
  it must be announced in advance since it will break existing forks/clones.
- **LinkedIn ToS**: Automated posting may violate LinkedIn's Terms of Service.
  Contributors should be aware that this tool is provided as-is, and each
  user is responsible for their own compliance.
