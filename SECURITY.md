# Security Policy

## Supported version

`0.1.x` receives security fixes while the project remains in its initial release line.

## Report a vulnerability

Do not open a public issue containing credentials, private report contents, repository URLs from a private data store, or exploit details. Use GitHub's private vulnerability reporting for the public repository owner. If that feature is unavailable, contact the owner privately and include only the minimum reproduction data.

## Security model

- The dashboard binds to `127.0.0.1` only and is not designed for reverse-proxy or public deployment.
- All feedback writes require a per-process CSRF token and a local Origin/Referer when provided.
- Private facts live in a separate private repository. The public repository ignores data, SQLite, outbox and `.env` paths.
- MiniMax receives public repository metadata and a public README excerpt only.
- The Git synchronizer refuses to run unless the repository contains `.ai-repo-radar-private`.

If you expose the dashboard beyond localhost, add authentication, TLS, a reviewed proxy configuration and a new threat model first; that is outside v0.1.0.
