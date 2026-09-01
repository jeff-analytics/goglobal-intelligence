# Security Policy

GoGlobal Intelligence is designed to keep API credentials and local project data outside source control.

## Secrets

- Store service credentials in `.env` or through the local Data Sources configuration UI.
- Never commit `.env`, API keys, client secrets, access tokens or exported credential files.
- `.env.example` contains placeholders only and is safe to commit.
- If a credential is accidentally exposed in a commit, screenshot, issue or log, revoke and rotate it immediately.

## Local data

SQLite databases, runtime caches, virtual environments and frontend dependencies/build output are excluded through `.gitignore`. Review staged files before every public push.

Recommended check:

```bash
git status
git diff --cached
```

## Reporting a security issue

For a public repository, avoid posting live credentials or sensitive project data in GitHub Issues. Remove or redact sensitive values before sharing logs or screenshots.
