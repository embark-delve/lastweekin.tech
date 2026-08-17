# Security Policy

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private
vulnerability reporting instead: **Security → Report a vulnerability** on this
repository. Expect an acknowledgement within a week.

What is in scope:

- Anything that would let a third party publish content to the site, such as an
  injection through the workflows or through a fetched feed or article body.
- Exposure of `OPENROUTER_API_KEY`, `HF_TOKEN`, or the workflow token.
- A dependency or pinned action that has been compromised upstream.

What is not in scope: bad, biased, or wrong story selection in a published
digest. That is a curation bug — open a normal issue for it.

## Supported versions

Only `main` is supported. The site is regenerated every Monday, so a fix ships
with the next scheduled run or with a manual `workflow_dispatch`.
