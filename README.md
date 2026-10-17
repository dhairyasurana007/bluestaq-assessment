# Team Notes API

[![CI](https://github.com/dhairyasurana007/bluestaq-assessment/actions/workflows/ci.yml/badge.svg)](https://github.com/dhairyasurana007/bluestaq-assessment/actions/workflows/ci.yml)

A small REST service (Python, FastAPI, SQLite) for notes shared across small teams. Notes live in
**team spaces**. Edits are protected by optimistic concurrency (`ETag` / `If-Match`), and deleted
notes go to a **trash** that can be restored.

## Live demo

- API: https://team-notes-api.onrender.com
- Interactive docs (Swagger UI): https://team-notes-api.onrender.com/docs

Please read these caveats before trying it:

- **No accounts.** Anyone with the URL can read, write, edit and delete anything.
- **Cold starts.** The free Render instance sleeps after about 15 minutes idle, so the first
  request can take up to a minute.
- **The data is temporary.** The instance has an ephemeral disk, so the demo database resets on
  every deploy or restart. At startup it is reseeded with demo data (teams `Platform` and
  `Research`).

To see the main flows end to end, run `bash examples/walkthrough.sh https://team-notes-api.onrender.com`
(needs only bash and curl).

## Quick start

Requires Python 3.13.

**Windows (PowerShell)**

```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
```

**Windows (Git Bash)**

```bash
py -3.13 -m venv .venv
source .venv/Scripts/activate
```

**macOS / Linux**

```bash
python3.13 -m venv .venv
source .venv/bin/activate
```

Then, in any shell with the venv active:

```bash
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs for the interactive API docs. The database is a SQLite file,
`notes.db`, in the current directory (override it with the `DATABASE_URL` environment variable).

Optional demo data (two teams and 12 notes, one of them in the trash). The database must already be
migrated, so run `alembic upgrade head` first:

```bash
python scripts/seed.py --force
```

## Running tests

```bash
pytest tests/unit                  # unit tests (in-process, temporary SQLite database per test)
pytest tests/e2e                   # end-to-end tests against a real local uvicorn process
E2E_BASE_URL=https://team-notes-api.onrender.com pytest tests/e2e   # e2e against the live demo
ruff check .                       # lint
ruff format --check .              # formatting
```

The e2e tests use Playwright's `APIRequestContext` (plain HTTP calls), so **no browser is needed**.
They create their own uniquely named teams and notes, so they are safe to run against the shared
demo. In PowerShell, set the variable first: `$env:E2E_BASE_URL = "https://team-notes-api.onrender.com"`.

CI (GitHub Actions) runs lint, unit and e2e jobs on every push, and Render deploys only commits
whose checks pass.

## API overview

All paths except `/health` are under `/api/v1`. There is no authentication. The table lists the 13
endpoints; the full schema is at `/docs`.

| # | Method and path | Description | Notable status codes |
|---|---|---|---|
| 1 | `GET /health` | Liveness check. Returns `{"status":"ok","commit":"<git sha or local>"}` | 200 |
| 2 | `POST /api/v1/teams` | Create a team. Body `{name}` | 201 with `Location`; 422 |
| 3 | `GET /api/v1/teams` | List teams, newest first. Query `limit` (1-100, default 20) | 200; 422 |
| 4 | `GET /api/v1/teams/{team_id}` | Get one team | 200; 404; 422 (not a UUID) |
| 5 | `PATCH /api/v1/teams/{team_id}` | Rename a team. Body `{name}` (required) | 200; 404; 422 |
| 6 | `DELETE /api/v1/teams/{team_id}` | Delete a team and **permanently** delete all its notes, trashed ones included | 204; 404 |
| 7 | `POST /api/v1/teams/{team_id}/notes` | Create a note. Body `{title, body?, author_name?}` | 201 with `Location` and `ETag: "1"`; 404 (team); 422 |
| 8 | `GET /api/v1/notes` | List active notes, most recently updated first. Query `team_id` (repeatable) and `limit` | 200; 422 |
| 9 | `GET /api/v1/notes/{note_id}` | Get one active note, with its `ETag` | 200; 404 |
| 10 | `PATCH /api/v1/notes/{note_id}` | Edit `title` and/or `body`. Requires an `If-Match` header | 200 with new `ETag`; 404; 412; 422; 428 |
| 11 | `DELETE /api/v1/notes/{note_id}` | Move the note to the trash (soft delete) | 204; 404 (also if already trashed) |
| 12 | `GET /api/v1/teams/{team_id}/trash` | List the team's trashed notes, most recently deleted first. Query `limit` | 200; 404 (team); 422 |
| 13 | `POST /api/v1/notes/{note_id}/restore` | Take a note out of the trash. Bumps `version`, returns a new `ETag` | 200; 404; 409 (not in the trash) |

Notes on behavior:

- **Optimistic concurrency.** A note's `ETag` is its `version` in quotes, for example `"3"`.
  `PATCH /notes/{id}` must send `If-Match` with the `ETag` from your last `GET` or `PATCH`. A missing
  header gives **428**. A version that no longer matches (someone else edited first), or a malformed
  value, gives **412**, and the `detail` field reports the current version. Re-fetch, merge and
  retry. `If-Match: *` matches any version. The update is a single conditional SQL `UPDATE`, so two
  racing edits cannot both win.
- **Errors are `application/problem+json`** (RFC 9457) for every 4xx and 5xx response, with
  `type`, `title`, `status`, `detail` and `instance`. This includes unknown routes (404) and wrong
  methods (405).
- **422 validation.** Request bodies reject unknown fields. Names and titles are trimmed and must be
  non-empty (team name up to 100 characters, note title up to 200, body up to 100,000, `author_name`
  1-100 and settable on create only). `PATCH` needs at least one of `title` or `body`, and explicit
  `null` values are rejected. Non-UUID path IDs and out-of-range `limit` values are also 422. The
  response carries an `errors` list of `{loc, msg}` entries.
- **Listing is minimal in the MVP.** `GET /notes` supports only `team_id` (repeatable; unknown IDs
  match nothing) and `limit`. There is no cursor yet: `next_cursor` is present in list responses
  but is always `null`.
- **Trash.** A trashed note is invisible everywhere except the trash list and restore: `GET`,
  `PATCH` and `DELETE` on it return 404, and it is excluded from `GET /notes`. There is no
  permanent delete of a single note.

## Domain model

SQLite, managed with Alembic migrations (`migrations/versions/0001_teams`, `0002_notes`,
`0003_note_trash`). IDs are UUID strings. All timestamps are UTC, ISO-8601.

**`teams`**

| Column | Notes |
|---|---|
| `id` | UUID, primary key |
| `name` | up to 100 characters |
| `created_at`, `updated_at` | set on create; `updated_at` changes on rename |

**`notes`**

| Column | Notes |
|---|---|
| `id` | UUID, primary key |
| `team_id` | foreign key to `teams.id`, `ON DELETE CASCADE`: deleting a team deletes its notes |
| `title` | up to 200 characters |
| `body` | text, default empty (the API caps it at 100,000 characters) |
| `author_name` | optional, up to 100 characters, set on create only |
| `version` | integer, starts at 1, incremented by every edit and every restore; exposed as the `ETag` |
| `created_at`, `updated_at` | `updated_at` is strictly later after every edit or restore |
| `deleted_at` | `NULL` means active; a timestamp means the note is in the trash (soft delete) |

Indexes: (`team_id`, `updated_at`, `id`) for listing and (`team_id`, `deleted_at`) for the trash.
Moving a note to the trash sets only `deleted_at`; it does not change `version` or `updated_at`.
Restoring clears `deleted_at` and bumps `version`, so an `ETag` captured before the delete no longer
matches.

`NoteOut` also contains a `tags` field. It is always `[]` for now; tags are not implemented.

## Out of scope

Deliberately not built in the MVP:

- Passwords, OIDC/SSO, token expiry (there are no accounts at all)
- Real-time co-editing
- Version history
- Permanent delete or automatic purge of trashed notes
- Attachments and rich text
- Per-note ACLs
- Rate limiting and abuse protection for the public demo
- Metrics
- Persistent production storage (the demo database resets on every deploy, by design)
- Tags, cursor pagination and sorting, and full-text search (planned for a later version, not
  implemented here)

### No accounts in the MVP: why, and how F4-F5 add them later

Leaving out accounts was a deliberate scope cut, made to ship a correct, deployed core quickly.
Teams organize notes; they are **not** security boundaries, and in the MVP anyone can edit or delete
anything. The data model and API are shaped so accounts can be added without breaking existing
clients. Planned task F4 adds optional user accounts and API tokens, where anonymous requests keep
working. Planned task F5 adds private teams with membership and roles: private teams require a
token and membership, while open teams keep behaving exactly as they do now. Neither is implemented
yet.

Two mitigations make the open model tolerable in the meantime. Optimistic concurrency stops silent
overwrites, and deletes go to a trash that anyone can restore from, so a stray or malicious
`DELETE` is recoverable. The demo database also resets on every deploy.

---

*Note: this MVP README was written without the tester-review pass, and the MVP is a checkpoint, not
the final submission.*
