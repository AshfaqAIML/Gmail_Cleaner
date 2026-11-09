# Security policy

## Supported deployment

Version 0.1.0 is intended for one user running the application locally. Do not expose the development API to the public internet.

## Sensitive files

Never commit or share:

- `.env`
- `credentials/client_secret.json`
- `credentials/token.json`
- `data/gmail_cleaner.sqlite3`
- mailbox exports, message bodies, attachments, or real user data

These paths are excluded by `.gitignore`. Check `git status` before every commit.

## Gmail permissions

The app requests `gmail.modify` and uses it for search/metadata retrieval and moving confirmed messages to Trash. It does not use the permanent-delete API.

## Reporting a vulnerability

Do not publish OAuth tokens, API keys, mailbox data, or a working exploit in a public issue. Use GitHub's private vulnerability reporting feature when available, or contact the repository maintainer privately.
