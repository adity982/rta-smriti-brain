# Atlas Demo

Atlas is a fictional local-first task service used to demonstrate Rta-Smriti Brain without exposing a real repository.

## Architecture

- `src/api.py` owns the public request boundary.
- `src/service.py` applies task rules and coordinates storage.
- `src/store.py` persists tasks in SQLite.
- `tests/` captures the expected behavior.

## Project rules

1. Keep the HTTP layer thin.
2. Validate task titles before persistence.
3. Store timestamps in UTC.
4. Never log task content.
