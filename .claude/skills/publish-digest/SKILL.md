---
name: publish-digest
description: Manually run and publish the weekly digest when the scheduled GitHub Actions run failed or did not fire. Use when the user asks to publish the digest, rerun a failed Monday edition, or when a digest-failure issue is open for the current week.
---

# Publish the weekly digest by hand

The digest normally publishes itself: `.github/workflows/main.yml` runs every
Monday 08:00 UTC and commits the regenerated `data/` and `public/` trees to
`main`. This skill is the fallback for when that did not happen — a failed
run, a GitHub outage, a dead model, an expired secret.

## 1. Establish what actually went wrong

Do not skip this. A failed run and a gate refusal are different problems.

```bash
gh run list --workflow "Weekly Tech Digest" --limit 3
gh issue list --label digest-failure --state open
```

- **Gate refusal** (the pipeline log ends in `DigestValidationError`): the run
  worked and the edition was judged unpublishable. Read the reasons in the log
  before overriding anything — `--skip-gate` publishes a broken edition.
- **Model failure / model unavailable**: run
  `uv run python tools/check_models.py` and fix `config.yaml` first.
- **Actions itself broken** (didn't fire, infra error): proceed to step 2.

## 2. Run the pipeline locally, without publishing

From the repository root, on a clean, up-to-date `main`:

```bash
scripts/publish_fallback.sh
```

The script refuses to run off `main`, behind `origin/main`, with a dirty tree,
or when this week's edition is already published. It loads secrets from `.env`
when the environment lacks them, runs the full pipeline (gate included), and
stops before committing anything.

## 3. Review the edition

Read `data/latest.json`: seven stories, summaries present, sources varied,
the intro and `why` lines sensible. Open `public/index.html` in a browser if
anything looks off.

## 4. Publish — with the user's go-ahead

Pushing to `main` publishes the site. Show the user the edition's headlines
first and get an explicit yes, then:

```bash
scripts/publish_fallback.sh --push
```

## 5. Close the loop

Comment on and close the week's `digest-failure` issue, noting the edition
was published manually and why the scheduled run failed.
