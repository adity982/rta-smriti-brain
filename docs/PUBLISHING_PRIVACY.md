# Publishing Privacy Guide

Rta-Smriti Brain is designed to index private repositories and private agent threads. That makes publishing hygiene important.

## Never Commit

- `.rta-smriti/`
- `*.sqlite`
- `*.sqlite-shm`
- `*.sqlite-wal`
- private thread exports
- local dashboard logs
- screenshots containing real project names, file paths, customer data, or unreleased products
- generated context packs from private projects
- API keys, tokens, cookies, credentials, or `.env` files

## Safe To Commit

- source code
- tests with demo data
- docs with neutral paths
- demo screenshots made from synthetic projects
- static dashboard build assets
- package manifests
- security policy
- contribution guide
- license

## Pre-Publish Scan

Run:

```powershell
$patterns = @(
  'local Windows user paths',
  'private sync-folder names',
  'SQLite brain files',
  'common API-key prefixes',
  'password, token, and secret assignments'
) -join '|'

Get-ChildItem -Force -Recurse |
  Where-Object { $_.FullName -notmatch '\\node_modules\\' } |
  Select-String -Pattern $patterns -CaseSensitive:$false
```

Expected result:

- no real local paths
- no private project names
- no credentials
- no private SQLite brain files

Some safe false positives may appear in docs where the text explicitly warns about secrets.

## Demo Data Rule

Every public screenshot, video, or GIF should be produced from synthetic demo projects such as:

- `demo-web`
- `demo-api`
- `demo-docs`

Do not use personal, client, employer, unreleased, or private product data in public launch assets.

## Default Brain Location For Users

Documentation should use:

```powershell
%USERPROFILE%\Documents\Rta-Smriti\brains
```

Avoid publishing machine-specific examples such as:

```powershell
C:\Users\<real-name>\...
```

## Release Checklist

Before every public release:

```powershell
npm run build
python -m unittest discover -s tests -v
python -m compileall -q rta_brain tests
pip install -e . --dry-run --no-deps
python rta-brain.py publish-readiness --json
```

Then run the privacy scan above.
