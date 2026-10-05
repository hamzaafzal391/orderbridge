# Security policy

OrderBridge is an early-stage portfolio project and is not yet deployed anywhere.

## Reporting a vulnerability

Please report security issues privately using GitHub's
[private vulnerability reporting](https://github.com/hamzaafzal391/orderbridge/security/advisories/new)
rather than opening a public issue.

## Handling of secrets and data

- API keys and secrets are read from environment variables or a git-ignored `.env`; they are
  never committed.
- Error messages and logs must not contain credentials, authorization headers, tokens, response
  bodies or customer data.
