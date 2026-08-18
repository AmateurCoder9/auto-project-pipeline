---
name: Bug Report
about: Report a pipeline failure or unexpected behavior
title: "[BUG] "
labels: bug
assignees: ''
---

## Which pipeline step failed?

<!-- Check one -->
- [ ] Project generation (Gemini API)
- [ ] GitHub repo creation
- [ ] Vercel deployment
- [ ] Screenshot capture (Playwright)
- [ ] LinkedIn caption generation
- [ ] LinkedIn posting
- [ ] Email notification
- [ ] Log commit / state machine
- [ ] Other (describe below)

## What happened?

<!-- A clear description of the bug -->

## Expected behavior

<!-- What you expected to happen instead -->

## Relevant log output

<!-- Paste the JSON log lines from the GitHub Actions run, or local stderr output.
     Redact any tokens/secrets before pasting! -->

```
(paste logs here)
```

## Environment

- **Python version**: 
- **OS**: (e.g., ubuntu-latest in Actions, Windows 11 locally)
- **Pipeline mode**: (e.g., DRY_RUN=true, TEST_MODE=true, normal)
- **Trigger**: (cron / manual dispatch / local run)

## Additional context

<!-- Any other info — screenshots, links to the failed Actions run, etc. -->
