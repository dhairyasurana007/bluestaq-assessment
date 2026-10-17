# PLAN.md: Team Notes REST Service

This file is the **single source of truth** for building this project. It is written to be executed step by step by a coding agent (Claude Sonnet, Codex or similar). Follow it literally. When something isn't specified, choose the simplest option that satisfies the spec and say so in your task report.

---

## 0. Read this first (agent instructions)

### 0.1 What you are building
A runnable REST backend (Python + FastAPI + SQLite) for a note-taking service shared across small teams, deployed to Render, with unit tests, Playwright end-to-end tests, GitHub Actions CI, a README, and a commit history of **one commit per task**.

- **MVP: no accounts.** Anyone with the URL can create team spaces and read, write and edit notes in them. Teams organize notes; they are not security boundaries.
- **Final (optional, if time allows):** opt-in user accounts and private teams, added without breaking the open MVP API.

Original assignment: deliver a runnable REST service and README in a version-controlled repository. Reviewers grade clarity, correctness and tradeoffs. The README must include 2–3 design choices and why, plus "what I'd change, add or stop doing with more time". The commit history is part of the submission.

### 0.2 Golden rules
1. **Do the tasks in order** (section 12). Never start a task before the previous one is pushed, CI is green (from M1 on) and the Render deploy is verified (from M0 on).
2. **One task = one commit.** The commit message is given in each task. The only exceptions are `fix(ci): …` / `fix(deploy): …` follow-up commits when CI or the deploy fails after a push (section 9.2, steps 9–10).
3. **Every task except M0 uses the coder/tester loop** in section 9. Don't skip the tester.
4. **Spec over intuition.** Sections 4–6 define exact field names, limits, status codes and module interfaces. Coder and tester both build from these, so they must agree without talking. Never invent a different shape.
5. **Never** commit `.venv/`, `*.db`, `.env`, logs or secrets. Never force-push. Never rewrite pushed history.
6. **Stop and ask the user** when you see `⚠️ USER ACTION REQUIRED`, when a spec ambiguity blocks you, or after 3 failed RED rounds on one task.
7. After finishing each task, tick it in the progress tracker (0.5) **as part of that task's commit**.

### 0.3 Environment facts
| Fact | Value |
|---|---|
| OS | Windows 11. Use the **Bash tool (Git Bash)** for all commands in this plan. |
| Project root | `C:\Users\dhair\bluestaq-assessment` (Git Bash: `/c/Users/dhair/bluestaq-assessment`) |
| Python | 3.13 (`py -3.13`) |
| Venv Python (local) | `.venv/Scripts/python.exe`. Always call tools through it: `.venv/Scripts/python -m pytest`, `.venv/Scripts/python -m ruff`, … Shell state does not persist between commands, so don't rely on `activate`. |
| Python in CI / Render | `python` (Linux) |
| GitHub CLI | `gh` 2.93, logged in as `dhairyasurana007` |
| GitHub repo | `dhairyasurana007/bluestaq-assessment` (public, already created and set as `origin`) |
| Render URL | `RENDER_URL` = `https://team-notes-api.onrender.com` |
| Docker | **Not installed.** Don't use it. |

**Hooks:** this workspace has a "fact-forcing" hook. Before the first Bash command or file write it may block and ask you to state facts (the user's request, what the command does, and so on). State them plainly in your reply, then retry the same call. That's expected, not an error.

**Long commands:** `scripts/wait_for_ci.py` and `scripts/wait_for_deploy.py` can run up to 15 minutes. Run them with a long timeout (for example `timeout: 900000` ms) or in the background, and wait for completion. Don't write your own `sleep` loops in the shell; the scripts already poll.

### 0.4 Deployment facts (fill in as you go)
| Item | Value |
|---|---|
| GitHub repo URL | `https://github.com/dhairyasurana007/bluestaq-assessment` |
| Render service name | `team-notes-api` |
| RENDER_URL | `https://team-notes-api.onrender.com` |

### 0.5 Progress tracker
| Phase | Task | Commit message | Done |
|---|---|---|---|
| MVP | M0 | `chore: bootstrap repository, minimal health app and Render blueprint` | [x] |
| MVP | M1 | `chore: scaffold FastAPI app with unit/e2e harnesses and CI` | [x] |
| MVP | M2 | `ci: gate Render deploys on passing CI checks` | [x] |
| MVP | M3 | `feat(teams): team spaces, database foundation and problem+json errors` | [x] |
| MVP | M4 | `feat(notes): note CRUD within team spaces` | [x] |
| MVP | M5 | `feat(notes): optimistic concurrency with ETag and If-Match` | [x] |
| MVP | M6 | `feat(notes): trash and restore for deleted notes` | [x] |
| MVP | M7 | `feat(demo): seed script and demo data on Render startup` | [x] |
| MVP | M8 | `docs: README with quick start, live demo and API tour` | [x] |
| Final | F1 | `feat(notes): tags with per-team namespace and tag filtering` | [ ] |
| Final | F2 | `feat(notes): keyset cursor pagination and sorting` | [ ] |
| Final | F3 | `feat(search): full-text note search with SQLite FTS5` | [ ] |
| Final | F4 (optional) | `feat(auth): optional user accounts and API tokens` | [ ] |
| Final | F5 (optional) | `feat(teams): private teams with membership and roles` | [ ] |
| Final | F6 | `docs: design decisions, tradeoffs and future work` | [ ] |
| Final | F7 (optional) | `chore: Dockerfile with CI build check` | [ ] |

After M8: `git tag v0.1-mvp && git push origin v0.1-mvp`. After F6: `git tag v1.0 && git push origin v1.0`.

---

## 1. Requirements → design implications

| Assignment says | Implication |
|---|---|
| "used and shared amongst several small teams" | Notes are grouped into **team spaces**. MVP: open to anyone with the URL. Final: optional private teams with accounts. |
| "capture and work with their notes" | Note CRUD, plus list, filter, search and paginate. |
| "shared" + "work with" | Concurrent edits must not silently overwrite each other (optimistic concurrency). This matters even more without accounts, since anyone can edit. |
| "You choose … what's in scope" | Auth is deliberately deferred; the README states this and shows the upgrade path (F4–F5). |
| "runnable REST service and README" | Runs locally with Python only, **and** a live demo on Render. |
| "commit history" | One commit per task, each green in CI. |

---

## 2. Stack

| Concern | Choice | Reason |
|---|---|---|
| Language | Python 3.13 | Readable, fast to build. |
| Framework | FastAPI | Validation, OpenAPI at `/docs`, dependency injection for DB sessions (and auth later). |
| ORM | SQLAlchemy 2.0 (typed `Mapped[]` models) | Standard; portable to Postgres. |
| DB | SQLite (WAL, `foreign_keys=ON`) | Zero setup; FTS5 for search. |
| Migrations | Alembic, one migration per schema-changing task | Schema history mirrors commit history. |
| Unit tests | pytest + FastAPI `TestClient` (in-process) | Fast, isolated DB per test. |
| E2E tests | Playwright for Python, `APIRequestContext` (no browser) | Black-box HTTP against a real `uvicorn` process locally, and against Render after deploy. |
| Lint/format | Ruff | One tool. |
| CI | GitHub Actions: `lint`, `unit`, `e2e` jobs | Every push verified. |
| Hosting | Render free web service, auto-deploy after CI passes | Fastest path to a public URL; no Docker needed. |
| Dependencies | `requirements.txt` + `requirements-dev.txt` (**no** `pip install -e .`) | Keeps imports resolving from the current directory, which the tester's worktree baseline depends on (section 9.1). |

`requirements.txt` (runtime):
```
fastapi>=0.115
uvicorn[standard]>=0.30
sqlalchemy>=2.0
alembic>=1.13
pydantic>=2.7
pydantic-settings>=2.3
```
`requirements-dev.txt`:
```
-r requirements.txt
pytest>=8
pytest-cov>=5
httpx>=0.27
playwright>=1.45
ruff>=0.5
pyyaml>=6
```

`pyproject.toml` holds **tool config only** (no package build):
```toml
[project]
name = "team-notes-api"
version = "0.1.0"
requires-python = ">=3.13"

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
addopts = "-q"

[tool.coverage.run]
source = ["app"]

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM"]
```

---

## 3. Scope

**MVP:** open team spaces (create, list, view, rename, delete); notes inside teams (CRUD, optional `author_name`); optimistic concurrency; trash and restore for deleted notes; problem+json errors; health endpoint; demo seed data; Render deployment; CI.

**Final:** tags; cursor pagination and sorting; full-text search; *optional* user accounts with API tokens (F4) and private teams with membership and roles (F5).

**Out of scope (list in the README):** passwords, OIDC/SSO, token expiry; real-time co-editing; version history; permanent delete or automatic purge of trashed notes; attachments, rich text; per-note ACLs; rate limiting and abuse protection for the public demo; metrics; persistent production storage (the demo DB resets on every deploy, by design).

---

## 4. Data model (exact)

| Table | Columns | Migration / task |
|---|---|---|
| `teams` | `id` UUID str PK; `name` str(100); `created_at`; `updated_at` | `0001_teams` / M3 |
| `notes` | `id` UUID PK; `team_id` FK teams ON DELETE CASCADE; `title` str(200); `body` text; `author_name` str(100) nullable; `version` int default 1; `created_at`; `updated_at`; index (`team_id`, `updated_at`, `id`) | `0002_notes` / M4 |
| `notes.deleted_at` | new nullable timestamp; `NULL` = active, set = in trash; index (`team_id`, `deleted_at`) | `0003_note_trash` / M6 |
| `tags` | `id` UUID PK; `team_id` FK CASCADE; `name` str(32); unique (`team_id`, `name`) | `0004_tags` / F1 |
| `note_tags` | `note_id` FK CASCADE; `tag_id` FK CASCADE; PK both | `0004` / F1 |
| `notes_fts` | FTS5 virtual table (`title`, `body`, content=`notes`), sync triggers on insert/update/delete, backfill | `0005_notes_fts` / F3 |
| `users` | `id` UUID PK; `username` str(32) unique, stored lowercase; `display_name` str(100); `created_at` | `0006_users_and_tokens` / F4 |
| `api_tokens` | `id` UUID PK; `user_id` FK CASCADE; `token_hash` str(64) unique (SHA-256 hex); `created_at`; `last_used_at` nullable; `revoked_at` nullable | `0006` / F4 |
| `notes.author_id` | new nullable FK → users | `0006` / F4 |
| `teams.visibility` | new column, `open` or `private`, default `open` | `0007_private_teams` / F5 |
| `team_memberships` | `team_id` FK CASCADE; `user_id` FK CASCADE; PK both; `role` `admin` or `member`; `joined_at` | `0007` / F5 |

All timestamps are UTC, ISO-8601. UUIDs are serialized as strings.

---

## 5. HTTP API spec (exact)

- Base path: `/api/v1` for everything except `GET /health`.
- **MVP: no authentication.** Every endpoint is open. (F4 adds *optional* bearer tokens; F5 makes them required only for private teams.)
- Request bodies forbid unknown fields (Pydantic `extra="forbid"` → 422).
- Path IDs are UUIDs; a non-UUID path ID → 422.

### 5.1 Shared shapes
```
TeamOut  = {id, name, created_at, updated_at}             # F5 adds "visibility" and "role"
NoteOut  = {id, team_id, title, body, tags: [str], author_name: str | null,
            version, created_at, updated_at, deleted_at}   # tags is [] until F1; deleted_at from M6
                                                           # (null unless in trash); F4 adds "author_id"
List<X>  = {items: [X], next_cursor: str | null}           # GET /notes: null until F2 adds cursors.
                                                           # Teams and trash lists: always null (limit only).
```

### 5.2 Validation rules
| Field | Rule |
|---|---|
| team `name` | 1–100 chars after trimming |
| note `title` | 1–200 chars after trimming |
| note `body` | 0–100,000 chars, default `""` |
| `author_name` | optional; 1–100 chars after trimming; set on create only (not editable) |
| `tags` (F1) | list of ≤10; each 1–32 chars, regex `^[a-z0-9-]+$` after lowercasing and trimming; duplicates removed; returned sorted ascending |
| `limit` | 1–100, default 20 |
| PATCH team | `name` required |
| PATCH note | at least one of `title`, `body`, `tags`, else 422 |

### 5.3 MVP endpoints
| # | Method & path | Request | Success | Errors | Task |
|---|---|---|---|---|---|
| 1 | `GET /health` | — | 200 `{"status":"ok","commit":"<RENDER_GIT_COMMIT or 'local'>"}` | — | M0 |
| 2 | `POST /teams` | `{name}` | 201 TeamOut + `Location: /api/v1/teams/{id}` | 422 | M3 |
| 3 | `GET /teams` | `?limit=` | 200 List<TeamOut>, newest `created_at` first | 422 | M3 |
| 4 | `GET /teams/{team_id}` | — | 200 TeamOut | 404 | M3 |
| 5 | `PATCH /teams/{team_id}` | `{name}` | 200 TeamOut | 404, 422 | M3 |
| 6 | `DELETE /teams/{team_id}` | — | 204 (deletes its notes too) | 404 | M3 |
| 7 | `POST /teams/{team_id}/notes` | `{title, body?, author_name?, tags?}` | 201 NoteOut + `Location: /api/v1/notes/{id}` + `ETag: "1"` | 404 team, 422 | M4 |
| 8 | `GET /notes` | query (5.4) | 200 List<NoteOut> | 422 | M4, F1–F3 |
| 9 | `GET /notes/{note_id}` | — | 200 NoteOut + `ETag` | 404 | M4 |
| 10 | `PATCH /notes/{note_id}` | `{title?, body?, tags?}` + `If-Match` (from M5) | 200 NoteOut + new `ETag` | 404, 422, 412, 428 | M4, M5 |
| 11 | `DELETE /notes/{note_id}` | — | 204. M4: hard delete. From M6: moves the note to the trash. | 404 (also if already in trash) | M4, M6 |
| 12 | `GET /teams/{team_id}/trash` | `?limit=` | 200 List<NoteOut> of trashed notes, most recently deleted first | 404 team, 422 | M6 |
| 13 | `POST /notes/{note_id}/restore` | — | 200 NoteOut (`deleted_at: null`, version bumped) + new `ETag` | 404 unknown, 409 not in trash | M6 |

**Trash rules (M6):** a trashed note is invisible everywhere except the trash list and restore: `GET`/`PATCH`/`DELETE /notes/{id}` return 404, and it's excluded from `GET /notes` (and later from tag filters and search). There's no permanent delete of single notes; deleting a team still permanently deletes all its notes, trashed ones included.

### 5.4 `GET /notes` query parameters
| Param | Task | Meaning |
|---|---|---|
| `team_id` (repeatable) | M4 | Restrict to these teams; unknown IDs simply match nothing |
| `limit` | M4 | 1–100, default 20 |
| `tag` (repeatable) | F1 | Note must have **all** given tags |
| `sort` | F2 | `-updated_at` (default), `updated_at`, `-created_at`, `title` |
| `cursor` | F2 | Opaque cursor from the previous page |
| `q` | F3 | Full-text search on title and body; when present, results are ranked by relevance and `sort` is ignored |

Until F2, results are sorted `-updated_at, -id`, truncated to `limit`, with `next_cursor: null`.

### 5.5 Status code rules (MVP)
| Situation | Code |
|---|---|
| Resource doesn't exist | 404 |
| Validation error | 422 |
| `PATCH /notes/{id}` without `If-Match` (from M5) | 428 |
| `If-Match` doesn't match the current version, or is malformed | 412 |
| Restoring a note that isn't in the trash (from M6) | 409 |

F4 adds 401 and more 409 cases; F5 adds 403 (section 12).

### 5.6 Error body (RFC 9457), every 4xx and 5xx
`Content-Type: application/problem+json`
```json
{"type": "about:blank", "title": "Not Found", "status": 404,
 "detail": "Note not found.", "instance": "/api/v1/notes/3f…"}
```
422 responses add `"errors": [{"loc": ["body","title"], "msg": "…"}]`. `title` is the standard HTTP reason phrase for the status.

### 5.7 ETag / If-Match (M5)
- `ETag` value is the note's version in double quotes: `"3"`.
- `If-Match` parsing: trim, strip an optional `W/` prefix, strip the quotes. `*` matches any version. A non-integer value → 412.
- The update must be atomic: `UPDATE notes SET …, version = version + 1 WHERE id = :id AND version = :expected`. Zero rows → 412 with `detail` "Note was modified by someone else (current version N)."

---

## 6. Testable module interface (exact)

Hidden unit tests may import **only** these names. The coder must provide them with these exact signatures.

| Module | Name | Contract |
|---|---|---|
| `app.main` | `create_app(database_url: str \| None = None) -> FastAPI` | Builds the app. If `database_url` is None, use `Settings().database_url`. Stores the resolved URL in `app.state.database_url` (M1+). |
| `app.main` | `app` | `app = create_app()` at module level (used by uvicorn) |
| `app.config` | `Settings` | pydantic-settings; `database_url: str = "sqlite:///./notes.db"` read from env `DATABASE_URL` |
| `app.pagination` (F2) | `encode_cursor(values: dict) -> str`, `decode_cursor(cursor: str) -> dict` | URL-safe base64 JSON; `decode_cursor` raises `ValueError` on garbage |
| `app.security` (F4) | `hash_token(raw: str) -> str`, `generate_token() -> str` | SHA-256 hex digest; `secrets.token_urlsafe(32)` |
| `migrations/env.py` | — | Uses `config.get_main_option("sqlalchemy.url")` if set, else `Settings().database_url`. Tests run migrations with `alembic.command.upgrade(cfg, "head")` after `cfg.set_main_option("sqlalchemy.url", url)`. |
| `GET /health` | — | Reads `os.environ.get("RENDER_GIT_COMMIT", "local")` **at request time** |

---

## 7. Design choices (these go in the README)

### A. Open-by-default team spaces, with an opt-in path to accounts
MVP has no login: anyone with the URL can use any team space. This was a deliberate scope cut to ship a correct, deployed core quickly. Teams are organizational, not security boundaries. The schema and API are shaped so accounts can be added **without breaking existing clients**: F4 makes tokens optional (anonymous requests still work), and F5 adds `private` teams that require membership while `open` teams keep working as before. Tradeoff: in the MVP, anyone can edit or delete anything. Two mitigations: optimistic concurrency (B) stops silent overwrites, and **deletes go to a trash** that anyone can restore from, so a stray or malicious `DELETE` is recoverable. The demo resets on deploy, and the README says so plainly.

### B. Optimistic concurrency
`version` column, `ETag`/`If-Match`, atomic conditional update, 412 on conflict and 428 when the header is missing. With no accounts, many anonymous people may edit the same note; this prevents silent lost updates without locks or CRDTs. Tradeoff: clients must handle 412 (re-fetch, merge, retry).

### C. Keyset pagination + FTS5 search
An opaque cursor over (sort key, id) stays stable under concurrent edits, unlike offset pagination. FTS5 gives ranked, tokenized search without another service, isolated in `repositories/notes.py::search_notes()` so it can be swapped for Postgres `tsvector`.

Minor choices: UUIDs; problem+json; SQLite plus a Render demo that resets on deploy; layering is router → repository with no service layer (YAGNI).

---

## 8. Project layout (target)

```
bluestaq-assessment/
├── PLAN.md  README.md  pyproject.toml  requirements.txt  requirements-dev.txt
├── render.yaml  .python-version  .gitignore  alembic.ini
├── .github/workflows/ci.yml
├── .claude/agents/notes-coder.md  .claude/agents/notes-tester.md
├── migrations/env.py  migrations/versions/0001_teams.py …
├── app/
│   ├── __init__.py  main.py  config.py  db.py  models.py  schemas.py  errors.py  pagination.py
│   ├── security.py  permissions.py          ← F4 / F5 only
│   ├── repositories/__init__.py  teams.py  notes.py
│   └── routers/__init__.py  health.py  teams.py  notes.py
├── scripts/wait_for_ci.py  scripts/wait_for_deploy.py  scripts/seed.py
├── examples/walkthrough.sh
└── tests/
    ├── unit/   conftest.py  test_<task>.py      ← OWNED BY TESTER
    └── e2e/    conftest.py  test_<task>.py      ← OWNED BY CODER
```

### 8.1 E2E harness (`tests/e2e/conftest.py`, built in M1)
- A session fixture `base_url`:
  - If env `E2E_BASE_URL` is set → use it as-is (remote target; don't start a server).
  - Else → create a temp dir; set `DATABASE_URL=sqlite:///<tmp>/e2e.db`; if `alembic.ini` exists, run `[sys.executable, "-m", "alembic", "upgrade", "head"]` with that env; start `[sys.executable, "-m", "uvicorn", "app.main:app", "--port", <free port>]` with stdout and stderr to `tests/e2e/.server.log`; poll `GET /health` for up to 20 s; yield `http://127.0.0.1:<port>`; terminate the process on teardown.
- A session fixture `api`: `with sync_playwright() as p: ctx = p.request.new_context(base_url=base_url); yield ctx; ctx.dispose()`.
- Helper `make_team(api) -> dict` creating a team named `e2e-<uuid4 hex[:12]>`.
- **E2E rules:** tests must pass against a non-empty, shared DB (Render, which anyone can write to). Always create your own teams and notes with unique names; filter lists by your own `team_id`; never assume global counts; never delete data you didn't create.
- No `playwright install` is needed (no browser). If Playwright errors about a missing browser, run `.venv/Scripts/python -m playwright install chromium` once and note it in the report.

### 8.2 Unit harness (`tests/unit/conftest.py`, tester-owned)
- Per test: a temp SQLite file, migrations to head (once Alembic exists, M3+), `TestClient(create_app(database_url=url))`.
- Factories: `make_team(client, name=None)`, `make_note(client, team_id, **fields)`.

---

## 9. Per-task workflow: coder + tester sub-agents

### 9.1 Roles
| Role | Where it works | Owns (may edit) | Must not |
|---|---|---|---|
| **Main agent** | main checkout | PLAN.md progress tick, commits, pushes, verification | write feature code or tests |
| **Coder** | main checkout | `app/`, `migrations/`, `tests/e2e/`, `scripts/`, config and docs named in the task | read, run, create or edit **anything** in `tests/unit/` (committed or not); read the tester's worktree |
| **Tester** | its **own git worktree** at the pre-task commit (phase 1), then the main checkout (phase 2) | `tests/unit/` | edit anything outside `tests/unit/`; paste hidden test source in reports |

Why the worktree: hidden tests stay out of the coder's checkout, and the baseline runs against the **pre-task code**, not the coder's half-written code. That only works because nothing is pip-installed in editable mode: pytest's `pythonpath = ["."]` makes `import app` resolve to the directory pytest runs in.

The tester uses the main checkout's venv by absolute path: `/c/Users/dhair/bluestaq-assessment/.venv/Scripts/python.exe -m pytest tests/unit`, run **from inside its worktree directory**.

**When a task changes earlier behavior** (for example M5 makes `If-Match` mandatory, which breaks the PATCH calls in M4's tests): in phase 1 the tester updates the affected earlier unit tests in its worktree (those updated tests count as regression tests and may pass or fail on the baseline), and the coder updates the affected earlier e2e tests.

**The coder never touches unit tests, for the whole task, including RED rounds.** `tests/unit/` belongs to the tester alone: only the tester writes, runs and reports on unit tests (the main agent also runs them in step 7 and CI runs them). The coder verifies its work with ruff and the Playwright e2e tests only, and learns about unit-test failures solely through the behavior descriptions the main agent relays (test names + expected vs. actual behavior, never test source or tracebacks).

### 9.2 Runbook (main agent): follow every step for every task M1–F7

**Step 1: Preflight.**
```bash
git status --porcelain        # must print nothing
git branch --show-current     # must print: main
git log --oneline -3
```
If the working tree isn't clean, stop and report to the user.

**Step 2: Spawn both sub-agents in one message, both in the background.**
- Coder: `Agent(subagent_type="notes-coder", prompt=<CODER PROMPT>)`
- Tester: `Agent(subagent_type="notes-tester", isolation="worktree", prompt=<TESTER PHASE 1 PROMPT>)`

Prompts are in 9.3. Replace `<TASK>` with the task ID, for example `M4`.

**Step 3: Collect the tester's baseline report.** (Docs tasks M8 and F6: the tester returns a README checklist instead of tests; see 9.6.) It must say: number of hidden tests N, and all N failed for an expected reason (assertion failure, 404/405 for a missing route, or ImportError for a module this task creates). Tests for the task's "Regression criteria" may pass and are reported separately. If any other hidden test **passed** or failed because of a bug in the test itself, send it back to the tester with `SendMessage` to fix, and repeat until the baseline is valid.

**Step 4: Collect the coder's report.** It must say that `ruff` and `tests/e2e` passed locally, and list the files changed. (The coder doesn't run `tests/unit`; regressions there are caught by the tester in phase 2.)

**Step 5: Start tester phase 2.** `SendMessage` to the tester with the TESTER PHASE 2 prompt (9.3) and the coder's report pasted in.

**Step 6: Read the verdict.**
- **GREEN** → go to step 7.
- **RED** → `SendMessage` to the coder: the failing test names with expected vs. actual behavior, and the must-fix gaps, exactly as the tester described them. **Do not** send hidden test source. When the coder reports back, repeat step 5. Count rounds; after **3** RED rounds, stop and ask the user.
- **Disagreement:** if the coder says a hidden test contradicts PLAN.md, re-read sections 4–6. If the plan is clear, the side that contradicts it fixes its work. If the plan is ambiguous, **stop and ask the user**, then record the decision in PLAN.md (it goes into this task's commit).

**Step 7: Main-agent verification (run these yourself).**
```bash
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m ruff format --check .
.venv/Scripts/python -m pytest tests/unit tests/e2e
git status --porcelain
git diff --stat
```
All must pass. Check that no `.db`, `.log`, `.venv` or `.env` files appear in `git status`. Skim `git diff` for debug prints, commented-out code and anything outside the task's scope.

**Step 8: Tick and commit.** In PLAN.md 0.5, change the task's `[ ]` to `[x]` (and fill section 0.4 values if the task produced them). Then:
```bash
git add -A
git commit -m "<exact commit message from the task>" -m "<one-line summary of what was built and tested>"
```
If your environment specifies co-author or attribution trailer lines for commits, add them as an extra `-m` paragraph.

**Step 9: Push and wait for CI.**
```bash
git push origin main
.venv/Scripts/python scripts/wait_for_ci.py
```
`wait_for_ci.py` exits 0 when every workflow run for HEAD succeeded, 1 if any failed (it prints the run ID), and 2 on timeout. If it fails:
```bash
gh run list --commit "$(git rev-parse HEAD)"     # see runs for this commit
gh run view <run-id>                             # summary of jobs
gh run view <run-id> --log-failed                # logs of failed steps only
```
Treat a CI failure as a RED round: send the failing log excerpt to the coder, re-verify (step 7), then commit with `fix(ci): <what was fixed>` and repeat step 9. Never amend or force-push.

Useful extra CI commands:
```bash
gh run list --limit 5                            # recent runs, all commits
gh run watch <run-id> --exit-status              # stream a run until done (blocks)
gh run rerun <run-id> --failed                   # rerun only failed jobs (flaky infra only)
gh workflow view CI                              # workflow overview
```

**Step 10: Verify the deploy (every task).**
```bash
.venv/Scripts/python scripts/wait_for_deploy.py "$RENDER_URL"
E2E_BASE_URL="$RENDER_URL" .venv/Scripts/python -m pytest tests/e2e
```
Substitute the real URL from 0.4 (shell variables don't persist between commands). `wait_for_deploy.py` exits 0 once `GET /health` reports `commit == HEAD`. If e2e fails remotely but passed locally, treat it as RED for the same task (likely an environment issue such as paths, env vars or start command), fix it with a `fix(deploy): …` commit, and repeat steps 9–10.

**Step 11: Clean up the tester worktree.**
```bash
git worktree list
git worktree remove --force <tester worktree path>   # only if it still exists
git worktree prune
```
Delete leftover local worktree branches with `git branch -D <name>` if they clutter `git branch` (local only, never pushed).

**Step 12:** Next task.

### 9.3 Prompt templates

**CODER PROMPT**
```
You are the coder for task <TASK> in C:\Users\dhair\bluestaq-assessment.
Read PLAN.md sections 0.3, 2, 4, 5, 6, 7, 8 and the task <TASK> in section 12. They are the spec.
Implement ONLY task <TASK>. Do not implement later tasks.
You may edit app/, migrations/, tests/e2e/, scripts/, and config/doc files the task names.
NEVER read, run, create or modify anything in tests/unit/ (committed or not), and never look in any other
git worktree. Unit tests belong to the tester. If told about unit-test failures, fix the described behavior.
Write Playwright e2e tests (tests/e2e/test_<task lowercase>.py) for every acceptance criterion
that is visible over HTTP: status codes, headers, bodies, error paths. Follow the E2E rules in 8.1.
Before reporting, run and make pass:
  .venv/Scripts/python -m ruff check .
  .venv/Scripts/python -m ruff format --check .
  .venv/Scripts/python -m pytest tests/e2e
Do not commit or push.
Report: (1) summary, (2) files changed, (3) endpoints added or changed, (4) exact commands you ran
and their results, (5) any deviation from PLAN.md and why.
```

**TESTER PHASE 1 PROMPT**
```
You are the tester for task <TASK>. You are in your own git worktree at the pre-task commit.
Main checkout (where the coder works): C:\Users\dhair\bluestaq-assessment. Do not read the coder's changes.
Read PLAN.md sections 4, 5, 6, 8.2 and task <TASK> in section 12.
Write hidden pytest unit tests in tests/unit/test_<task lowercase>.py (and update tests/unit/conftest.py if needed)
covering EVERY acceptance criterion of <TASK> plus edge cases: validation bounds, error codes and
problem+json bodies. Import only names listed in PLAN.md section 6.
Run from your worktree directory:
  /c/Users/dhair/bluestaq-assessment/.venv/Scripts/python.exe -m pytest tests/unit/test_<task lowercase>.py
Every test must FAIL, and for the expected reason (assertion, 404/405 missing route, or ImportError
for a module this task creates). Fix any test that passes or errors because of its own bug.
Exception: criteria the task lists under "Regression criteria" may pass on the baseline. Put those
tests in tests/unit/test_<task lowercase>_regression.py and report them separately.
Do not edit anything outside tests/unit/. Do not commit.
Report: number of tests, baseline result summary (counts by failure reason), list of test names
with the acceptance criterion each covers. Do NOT include test source.
```

**TESTER PHASE 2 PROMPT**
```
Phase 2 for task <TASK>. The coder reports the implementation is ready:
<paste coder report>
1. Copy your tests/unit files from your worktree into C:\Users\dhair\bluestaq-assessment\tests\unit\ (overwrite conftest.py).
2. In the main checkout run:
   .venv/Scripts/python -m ruff check .   and   .venv/Scripts/python -m ruff format --check .
   .venv/Scripts/python -m pytest tests/unit --cov=app --cov-report=term-missing
   .venv/Scripts/python -m pytest tests/e2e
3. Verify the coder did not modify tests/unit: `git diff -- tests/unit` and `git status -- tests/unit`
   must show only your files, identical to your worktree copies.
4. Review tests/e2e/test_<task lowercase>.py against task <TASK>'s acceptance criteria. List gaps as
   MUST-FIX (an acceptance criterion with no e2e coverage) or NICE-TO-HAVE.
5. You may add more unit tests for gaps you find; they must fail on pre-task code (check in your worktree).
Verdict: GREEN only if all tests pass, ruff is clean, coverage >= 85%, no MUST-FIX gaps, and step 3 is OK.
Otherwise RED with: failing test names + expected vs actual behavior, MUST-FIX gaps. No test source.
```

### 9.4 Agent definition files (created in M0)

`.claude/agents/notes-coder.md`
```markdown
---
name: notes-coder
description: Implements exactly one PLAN.md task in the main checkout and writes Playwright e2e tests for it. Never reads, runs or edits anything in tests/unit.
tools: Read, Write, Edit, Bash, Glob, Grep
---
You are the coder sub-agent for the Team Notes API. PLAN.md is the spec and your prompt names one task.
Follow the CODER PROMPT rules in PLAN.md section 9.3 exactly. Never commit or push.
```

`.claude/agents/notes-tester.md`
```markdown
---
name: notes-tester
description: Writes hidden unit tests for one PLAN.md task in an isolated worktree, proves they fail first, then verifies the coder's implementation and e2e coverage.
tools: Read, Write, Edit, Bash, Glob, Grep
---
You are the tester sub-agent for the Team Notes API. PLAN.md is the spec and your prompt names one task and phase.
Follow the TESTER PHASE 1 / PHASE 2 rules in PLAN.md section 9.3 exactly. Only edit tests/unit/. Never commit or push.
Never reveal hidden test source in your reports.
```

### 9.5 Fallback when sub-agents are unavailable (for example Codex without sub-agents)
Run the same roles **sequentially** yourself:
1. `git worktree add ../notes-tester-wt HEAD` → write hidden tests there → run the baseline (must fail) → don't look at them again.
2. Implement in the main checkout as the coder, with e2e tests, all green.
3. Copy the hidden tests into `tests/unit/` → run everything → review e2e gaps → fix until green.
4. Continue at runbook step 7. Remove the worktree with `git worktree remove --force ../notes-tester-wt`.

Note in the README that the fallback was used for any such task.

### 9.6 Docs tasks (M8, F6)
The coder writes the docs. The tester's phase 1 writes no unit tests; it writes a **checklist** of what the README must contain (from the task). In phase 2 it follows the README literally in a fresh venv in a temp dir, runs every documented command, and executes `examples/walkthrough.sh` against `RENDER_URL`. Any failing or unclear step → RED.

---

## 10. CI: `.github/workflows/ci.yml` (created in M1)

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13", cache: pip, cache-dependency-path: requirements-dev.txt }
      - run: pip install -r requirements-dev.txt
      - run: ruff check .
      - run: ruff format --check .
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13", cache: pip, cache-dependency-path: requirements-dev.txt }
      - run: pip install -r requirements-dev.txt
      - run: pytest tests/unit --cov=app --cov-report=term-missing --cov-fail-under=85
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13", cache: pip, cache-dependency-path: requirements-dev.txt }
      - run: pip install -r requirements-dev.txt
      - run: pytest tests/e2e
      - if: failure()
        uses: actions/upload-artifact@v4
        with: { name: e2e-server-log, path: tests/e2e/.server.log, if-no-files-found: ignore }
```
Workflow name **must** stay `CI` (Render waits for checks, and the commands in 9.2 reference it).

---

## 11. Render deployment

### 11.1 `render.yaml` (created in M0; updated in M2, M3 and M7)
M0 version (copy exactly):
```yaml
services:
  - type: web
    name: team-notes-api
    runtime: python
    plan: free
    branch: main
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /health
    envVars:
      - key: PYTHON_VERSION
        value: "3.13.2"
      - key: DATABASE_URL
        value: sqlite:///./notes.db
```
- M0 deploys on every push (Render's default), because CI doesn't exist yet.
- M2 adds `autoDeployTrigger: checksPass` under `branch: main`.
- M3 changes `startCommand` to: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- M7 changes it to: `alembic upgrade head && python scripts/seed.py --if-empty && uvicorn app.main:app --host 0.0.0.0 --port $PORT`, and adds env var `SEED_DEMO_DATA=true`.
- If the build log says Python `3.13.2` isn't available, change `PYTHON_VERSION` to the 3.13.x version the log or Render docs list.
- Facts to state in the README: the free instance sleeps after about 15 minutes idle (the first request can take up to a minute), and the disk is ephemeral, so **the demo database resets on every deploy or restart**. Demo data is reseeded at startup.

### 11.2 `scripts/wait_for_ci.py` (created in M1, copy exactly)
```python
"""Wait for all GitHub Actions runs for HEAD to finish. Exit 0 = all succeeded, 1 = failure, 2 = timeout."""

import json
import subprocess
import sys
import time


def sh(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout.strip()


def main() -> int:
    sha = sh("git", "rev-parse", "HEAD")
    deadline = time.time() + 15 * 60
    while time.time() < deadline:
        out = sh("gh", "run", "list", "--commit", sha, "--json", "databaseId,status,conclusion,workflowName")
        runs = json.loads(out or "[]")
        if runs and all(r["status"] == "completed" for r in runs):
            for r in runs:
                print(f"{r['workflowName']}: {r['conclusion']} (run {r['databaseId']})")
            failed = [r for r in runs if r["conclusion"] != "success"]
            if failed:
                print(f"Inspect: gh run view {failed[0]['databaseId']} --log-failed")
                return 1
            return 0
        print("CI running..." if runs else "No run registered for HEAD yet...", flush=True)
        time.sleep(15)
    print("Timed out waiting for CI")
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

### 11.3 `scripts/wait_for_deploy.py` (created in M0, copy exactly)
```python
"""Poll <url>/health until it reports the expected commit. Usage: wait_for_deploy.py URL [SHA]."""

import json
import subprocess
import sys
import time
import urllib.request


def main() -> int:
    url = sys.argv[1].rstrip("/") + "/health"
    if len(sys.argv) > 2:
        sha = sys.argv[2]
    else:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    deadline = time.time() + 15 * 60
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                live = json.load(resp).get("commit")
            if live == sha:
                print(f"Deploy verified: {sha} is live at {url}")
                return 0
            print(f"Live commit is {live}; waiting for {sha}...", flush=True)
        except Exception as exc:  # cold start, deploy in progress, DNS
            print(f"Not reachable yet: {exc}", flush=True)
        time.sleep(20)
    print("Timed out waiting for deploy. Check the Render dashboard → Events / Logs.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

---

## 12. Tasks

Each task lists **Build** (what the coder creates), **Acceptance criteria** (the tester turns each bullet into hidden unit tests and the coder covers them with e2e tests), optional **Regression criteria** (already true; may pass on the tester's baseline), and the **commit message**. Run the section 9.2 runbook for every task except M0.

### Phase 1: MVP (M0–M8), no accounts
Goal: a deployed, open notes API organized by team spaces, with safe concurrent edits, a recoverable trash, demo data, CI and a short README. **The MVP is an internal checkpoint, not the submission:** the user tries the live API to confirm the direction before the Final phase. Only the final version (after F6) is submitted, so the assignment's required README sections are written in F6.

#### M0: Bootstrap repository, minimal app, Render connection *(main agent only; no sub-agents)*
Goal: a live Render URL **before** any feature work, so every later task is deployed and verified.

**Already done before this plan started:** the GitHub repo `dhairyasurana007/bluestaq-assessment` exists (public), the local folder is a git repo on `main` tracking `origin/main`, and the only commit so far is `docs: add implementation plan` (this file). Verify with:
```bash
git remote -v                              # origin → github.com/dhairyasurana007/bluestaq-assessment.git
gh repo view dhairyasurana007/bluestaq-assessment --json url,visibility
```
Then run from the project root:
```bash
py -3.13 -m venv .venv
```
Create these files with exactly the content in this plan: `.gitignore` (below), `requirements.txt`, `requirements-dev.txt`, `pyproject.toml` (section 2), `.claude/agents/notes-coder.md`, `.claude/agents/notes-tester.md` (section 9.4), `render.yaml` (section 11.1, the M0 version), `scripts/wait_for_deploy.py` (section 11.3), `app/__init__.py` (empty), and `app/main.py` (below). `.python-version` contains `3.13`.

`app/main.py` (minimal app; M1 restructures it):
```python
import os

from fastapi import FastAPI


def create_app(database_url: str | None = None) -> FastAPI:
    app = FastAPI(title="Team Notes API")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "commit": os.environ.get("RENDER_GIT_COMMIT", "local")}

    return app


app = create_app()
```

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
*.db
*.db-wal
*.db-shm
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/
tests/e2e/.server.log
.env
```
Then:
```bash
.venv/Scripts/python -m pip install --upgrade pip
.venv/Scripts/python -m pip install -r requirements-dev.txt
git add -A
git commit -m "chore: bootstrap repository, minimal health app and Render blueprint"
git push -u origin main
```
Tick M0 in 0.5 **before** the commit above. If the push is rejected, stop and ask the user (don't force-push).

Quick local smoke test before asking the user (optional but recommended): start the app with `.venv/Scripts/python -m uvicorn app.main:app --port 8000` **in the background**, run `curl -s http://127.0.0.1:8000/health` (expect `{"status":"ok","commit":"local"}`), then stop the server.

**⚠️ USER ACTION REQUIRED: connect Render (right after M0 is pushed, before M1).** Stop and ask the user to:
1. Sign in or sign up at https://render.com (free tier; "Sign in with GitHub" is simplest).
2. Click **New → Blueprint**, pick the `dhairyasurana007/bluestaq-assessment` repo, and click **Apply**. This creates the `team-notes-api` web service from `render.yaml`.
3. Wait until the first deploy shows **Live**, then paste the service URL (`https://….onrender.com`) back into the chat.

If the Render build fails, ask the user to paste the end of the build log. Common fixes are in 11.1 (Python version). Fix, commit as `fix(deploy): …`, and push.

After the user gives the URL:
```bash
.venv/Scripts/python scripts/wait_for_deploy.py https://<service>.onrender.com
```
It must print `Deploy verified`. Write the URL into sections 0.3 and 0.4. That PLAN.md change goes into the **M1** commit. Don't start M1 until the deploy is verified.

#### M1: Scaffold, test harnesses, CI
**Build:** `app/config.py` (`Settings`); restructure `app/main.py` so `create_app` reads `Settings`, stores the resolved URL in `app.state.database_url`, and registers `app/routers/health.py` (move `/health` there; behavior unchanged); `tests/e2e/conftest.py` (section 8.1) + `tests/e2e/test_m1.py`; `.github/workflows/ci.yml` (section 10); `scripts/wait_for_ci.py` (section 11.2).
**Acceptance criteria (new behavior; the hidden tests must fail on the M0 code):**
- `from app.config import Settings`; `Settings().database_url == "sqlite:///./notes.db"` when `DATABASE_URL` is unset; with env `DATABASE_URL=sqlite:///x.db` → `"sqlite:///x.db"`.
- `create_app("sqlite:///<tmp>/x.db").state.database_url == "sqlite:///<tmp>/x.db"`, and `create_app()` uses `Settings().database_url`. Creating the app must not create `./notes.db`.

**Regression criteria:**
- `GET /health` → 200 `{"status": "ok", "commit": "local"}` when `RENDER_GIT_COMMIT` is unset; `"commit": "abc123"` when that env var is set (read at request time).
- `GET /docs` → 200; `GET /openapi.json` → 200 with `info.title == "Team Notes API"`; unknown path → 404.
- The e2e fixture starts and stops uvicorn cleanly; e2e also passes with `E2E_BASE_URL` set to `RENDER_URL`.
- After push, `scripts/wait_for_ci.py` exits 0 (all three jobs green), and `scripts/wait_for_deploy.py` verifies the M1 commit on Render.

**Commit:** `chore: scaffold FastAPI app with unit/e2e harnesses and CI`

#### M2: Gate Render deploys on CI
**Build:** add `autoDeployTrigger: checksPass` to `render.yaml` (see 11.1), so Render deploys only commits whose GitHub checks passed.
**Acceptance criteria (hidden unit tests read `render.yaml` with PyYAML):**
- `render.yaml` has exactly one service, and `autoDeployTrigger == "checksPass"`.

**Regression criteria:**
- `type: web`, `runtime: python`, `plan: free`, `healthCheckPath: /health`, `buildCommand` installs `requirements.txt`, and `startCommand` contains `uvicorn app.main:app`, `--host 0.0.0.0` and `--port $PORT`.
- After push: CI green, then `wait_for_deploy.py` verifies the M2 commit, and remote e2e passes.

If the Blueprint sync rejects `autoDeployTrigger` (visible in the Render dashboard under Blueprints, or the deploy never picks up the commit), remove the line and ask the user to set **Settings → Build & Deploy → Auto-Deploy → "After CI Checks Pass"** in the Render dashboard. Note this in the commit body.
**Commit:** `ci: gate Render deploys on passing CI checks`

#### M3: Team spaces, DB foundation, error contract
**Build:** `app/db.py` (engine with `check_same_thread=False`, `PRAGMA foreign_keys=ON` and `journal_mode=WAL` on connect, session dependency); `alembic.ini`, `migrations/env.py` (per section 6), migration `0001_teams`; `app/models.py`; `app/schemas.py`; `app/errors.py` (problem+json handlers for `HTTPException`, `RequestValidationError` and domain errors, including routing 404/405); `app/repositories/teams.py`; `app/routers/teams.py` (endpoints 2–6); `render.yaml` start command with `alembic upgrade head` (11.1).
**Acceptance criteria:**
- `POST /teams {"name": "Platform"}` → 201, TeamOut, header `Location: /api/v1/teams/{id}`; leading and trailing whitespace in `name` is trimmed.
- Empty or whitespace-only name, a 101-char name, a missing name or an unknown field → 422 problem+json with `errors` (for example `loc == ["body","name"]`).
- `GET /teams` → List<TeamOut>, newest first; `limit` respected; `limit=0` or `101` → 422.
- `GET /teams/{id}` → 200; a random UUID → 404 problem+json; a non-UUID → 422.
- `PATCH /teams/{id} {"name": "New"}` → 200 with the new name and a later `updated_at`; unknown ID → 404.
- `DELETE /teams/{id}` → 204; then `GET` → 404; deleting again → 404.
- Every 4xx response, including routing 404 and 405, has `Content-Type: application/problem+json` with `type`, `title`, `status`, `detail`.

**Regression criteria:** `/health` unchanged; remote e2e against Render passes after deploy (migrations run on startup).
**Commit:** `feat(teams): team spaces, database foundation and problem+json errors`

#### M4: Notes CRUD within team spaces
**Build:** migration `0002_notes`; `app/repositories/notes.py`; `app/routers/notes.py` (endpoints 7–11; `GET /notes` with `team_id` + `limit` only; PATCH unconditional in this task).
**Acceptance criteria:**
- Create → 201, NoteOut with `version: 1`, `tags: []`, `author_name` as given (or `null`); headers `Location: /api/v1/notes/{id}` and `ETag: "1"`.
- Creating in a nonexistent team → 404.
- Validation: empty or whitespace title, a 201-char title, a body over 100,000 chars, a 101-char `author_name`, an unknown field → 422. PATCH with `{}` → 422. PATCH containing `author_name` → 422 (not editable).
- `GET /notes/{id}` → 200 with `ETag`; unknown → 404.
- `GET /notes?team_id=<id>` returns only that team's notes, newest `updated_at` first, `next_cursor: null`; two `team_id` params return notes from both teams; `limit` bounds as in 5.2.
- PATCH updates only the provided fields, bumps `version`, updates `updated_at`, and leaves `created_at` unchanged.
- DELETE → 204; then GET → 404.
- Deleting a team deletes its notes (`GET /notes/{id}` → 404 afterwards).

**Commit:** `feat(notes): note CRUD within team spaces`

#### M5: Optimistic concurrency
**Build:** the section 5.7 behavior; `ETag` on endpoints 7, 9, 10 (already present from M4; keep it). This task intentionally changes M4 behavior (PATCH without `If-Match` now fails), so follow "When a task changes earlier behavior" in 9.1: the tester updates `tests/unit/test_m4.py` and the coder updates `tests/e2e/test_m4.py`.
**Acceptance criteria:**
- PATCH without `If-Match` → 428 problem+json.
- PATCH with `If-Match: "1"` on a v1 note → 200, `version: 2`, `ETag: "2"`.
- Stale: A and B both read v1; A patches with `"1"` → 200; B patches with `"1"` → 412, `detail` mentions current version 2, and B's change is **not** applied (GET shows A's values).
- `If-Match: W/"2"` is accepted as version 2; `If-Match: *` always matches; `If-Match: "abc"` → 412.

**Commit:** `feat(notes): optimistic concurrency with ETag and If-Match`

#### M6: Trash and restore
**Build:** migration `0003_note_trash` (`notes.deleted_at` + index); change `DELETE /notes/{id}` to a soft delete; add endpoints 12 and 13 (section 5.3); every active-note query in `repositories/notes.py` filters `deleted_at IS NULL`. Put that filter in **one** helper (for example `active_notes()`) so later tasks (tags, pagination, search) can't forget it.
**Acceptance criteria:**
- `DELETE /notes/{id}` → 204; afterwards `GET`, `PATCH` and `DELETE` on that ID → 404, and it's absent from `GET /notes`.
- `GET /teams/{team_id}/trash` lists it with a non-null `deleted_at`, most recently deleted first; `limit` bounds as in 5.2; unknown team → 404; active notes never appear in the trash.
- `POST /notes/{id}/restore` → 200, `deleted_at: null`, `version` incremented, new `ETag`; the note reappears in `GET /notes` and `GET /notes/{id}`, with title and body unchanged.
- Restoring an active note → 409 problem+json; restoring an unknown ID → 404.
- An `If-Match` captured before the delete no longer matches after a restore (PATCH with the old ETag → 412).
- Deleting the team permanently removes its trashed notes too (restore → 404 afterwards).
- The migration leaves existing notes active (`deleted_at` NULL).

**Regression criteria:** create, read, update and concurrency behavior from M4–M5 unchanged.
**Commit:** `feat(notes): trash and restore for deleted notes`

#### M7: Demo seed data on Render
**Build:** `scripts/seed.py` with `--if-empty` (do nothing and exit 0 if any team exists), `--force` and `--database-url` (default from `Settings`). It creates team `Platform` with 7 notes (1 of them in the trash) and team `Research` with 5 notes, with `author_name` values `Alice`, `Bob` and `Carol`. It runs **only** if env `SEED_DEMO_DATA=true` or `--force` is passed; otherwise it prints a message and exits 0. Update `render.yaml` per 11.1 (seed in `startCommand`, env `SEED_DEMO_DATA=true`).
**Acceptance criteria:**
- `--force` on an empty DB creates exactly 2 teams and 12 notes with the names above, exactly 1 of them in Platform's trash.
- Running again with `--if-empty` changes nothing (counts unchanged, exit 0).
- Without `SEED_DEMO_DATA=true` and without `--force` → no data is created.
- Remote, checked by the **main agent** with curl right after `wait_for_deploy.py` and **before** running remote e2e (e2e runs add newer teams that could push the seeded ones off the first page): `curl -s "$RENDER_URL/api/v1/teams?limit=100"` includes `Platform` and `Research`. This can't be an e2e test, because the local e2e server isn't seeded.

**Commit:** `feat(demo): seed script and demo data on Render startup`

#### M8: README v1 *(docs task, section 9.6)*
**Build:** `README.md` with:
- title + CI badge (`https://github.com/dhairyasurana007/bluestaq-assessment/actions/workflows/ci.yml/badge.svg`)
- **Live demo**: RENDER_URL, a link to `/docs`, and the caveats: no accounts (anyone can edit), cold start, data resets on deploy
- **Quick start**: Windows and macOS/Linux venv commands, `pip install -r requirements-dev.txt`, `alembic upgrade head`, `uvicorn app.main:app --reload`, open `/docs`, optional `python scripts/seed.py --force`
- **Running tests**: unit, e2e, e2e against Render via `E2E_BASE_URL`, ruff
- **API overview**: endpoint table
- **Domain model**
- **Out of scope**, including "no accounts in the MVP: why, and how F4–F5 add them"
Also `examples/walkthrough.sh`: bash + curl that takes a base URL as `$1`, creates a team, creates a note, reads it with its ETag, makes one successful edit, shows a stale edit getting 412, deletes the note, lists the team's trash, and restores it, printing each response.
**Acceptance criteria (tester checklist):** every section above is present; every command runs as written in a fresh venv; `bash examples/walkthrough.sh "$RENDER_URL"` completes and shows a 412 and a successful restore; links resolve.
**Commit:** `docs: README with quick start, live demo and API tour`
After CI and deploy verification: `git tag v0.1-mvp && git push origin v0.1-mvp`.

### Phase 2: Final (F1–F7)
Do F1–F3 first. F4–F5 (accounts) are **optional**; do them only if time allows, and always do F6.

#### F1: Tags
**Build:** migration `0004_tags`; `tags` accepted on create and PATCH (PATCH replaces the full set); normalization per 5.2; `tag` filter on `GET /notes`; seed script adds tags to the demo notes.
**Acceptance criteria:**
- `tags: ["Design", " q4 ", "design"]` → stored and returned as `["design", "q4"]`.
- Invalid tag (`"has space"`, 33 chars, 11 tags) → 422.
- `GET /notes?tag=design&tag=q4` returns only notes having both.
- Tags are per team: the same tag name in two teams creates two `tags` rows, and filtering by `team_id` + `tag` only returns that team's notes.
- Changing tags requires `If-Match` and bumps `version`.
- Trashed notes keep their tags but never appear in tag-filtered results; restoring brings them back with tags intact.

**Commit:** `feat(notes): tags with per-team namespace and tag filtering`

#### F2: Cursor pagination and sorting
**Build:** `app/pagination.py` (`encode_cursor`, `decode_cursor`); keyset queries for each `sort` value on `GET /notes`; the cursor encodes `{"s": sort, "k": <last sort key>, "id": <last id>}`.
**Acceptance criteria:**
- `encode_cursor`/`decode_cursor` round-trip; `decode_cursor("!!!")` raises `ValueError`.
- With 25 notes in one team and `limit=10`, three pages return all 25 exactly once, in order; the last page has `next_cursor: null`.
- Stability: fetch page 1, update a note from page 1 (moving it to the top), fetch page 2 → no duplicates and no skipped notes among those that existed before.
- Each sort value orders correctly; a cursor created with one sort, used with another → 422; a garbage cursor → 422 (never 500).

**Commit:** `feat(notes): keyset cursor pagination and sorting`

#### F3: Full-text search
**Build:** migration `0005_notes_fts` (FTS5 external-content table + insert/update/delete triggers + backfill of existing rows); `search_notes()`; `q` param. When `q` is set, results are ordered by relevance, so the F2 cursor encodes `{"s": "rank", "k": <bm25 score>, "id": <last id>}`. Quote user input to avoid FTS syntax errors: wrap each whitespace-separated term in double quotes, escaping embedded `"` as `""`.
**Acceptance criteria:**
- `q=kubernetes` finds notes with the word in the title or body; a non-matching term returns empty `items`.
- Updated text is searchable immediately; trashed notes are never returned, and become searchable again after restore.
- `q` combines with `team_id`, `tag` and pagination.
- `q` containing `"`, `*`, `NEAR(`, `-` or `:` → 200 (never 500).
- The migration backfills notes that existed before it ran.

**Commit:** `feat(search): full-text note search with SQLite FTS5`

#### F4 (optional): User accounts and API tokens
Accounts are **opt-in**: every MVP endpoint keeps working without a token.
**Build:** migration `0006_users_and_tokens` (+ nullable `notes.author_id`); `app/security.py` (`generate_token`, `hash_token`, an `optional_user` dependency); endpoints:

| Method & path | Request | Success | Errors |
|---|---|---|---|
| `POST /users` | `{username, display_name}` (username 3–32, `^[A-Za-z0-9_]+$`, stored lowercase; display_name 1–100) | 201 `{"user": {id, username, display_name, created_at}, "token": "<raw>"}` | 409 duplicate (case-insensitive), 422 |
| `GET /me` | bearer token **required** | 200 `{"user": …}` | 401 |
| `GET /me/tokens` | required | 200 List of `{id, created_at, last_used_at, revoked_at}` | 401 |
| `POST /me/tokens` | required | 201 `{"token_id", "token"}` | 401 |
| `DELETE /me/tokens/{id}` | required | 204 | 401, 404 not mine, 409 last active token |

**Acceptance criteria:**
- The DB stores only `hash_token(token)`, never the raw token.
- No `Authorization` header → all MVP endpoints behave exactly as before (regression).
- A header that is present but invalid (unknown, revoked, malformed, wrong scheme) → 401 with `WWW-Authenticate: Bearer`, even on open endpoints.
- With a valid token, a created note gets `author_id = user.id` and `author_name = user.display_name` (any `author_name` in the body is ignored); NoteOut gains `author_id` (null for anonymous notes).
- Revoked token → 401; other tokens still work; `last_used_at` is set after use.

**Commit:** `feat(auth): optional user accounts and API tokens`

#### F5 (optional, requires F4): Private teams with membership and roles
**Build:** migration `0007_private_teams` (`teams.visibility`, `team_memberships`); `app/permissions.py` as the single place for access checks; TeamOut gains `visibility` and `role` (the caller's role, or `null`). `POST /teams` accepts `visibility` (`open` default, or `private`; `private` requires a token → else 401); the creator of a private team becomes `admin`. Member endpoints, **for private teams only** (on an open team → 409):

| Method & path | Who | Success | Errors |
|---|---|---|---|
| `GET /teams/{id}/members` | member | 200 List of `{user: {id, username, display_name}, role, joined_at}` | 404 |
| `POST /teams/{id}/members` | admin; `{username, role="member"}` | 201 | 403, 404, 409 already a member |
| `PATCH /teams/{id}/members/{user_id}` | admin; `{role}` | 200 | 403, 404, 409 last admin |
| `DELETE /teams/{id}/members/{user_id}` | admin, or self | 204 | 403, 404, 409 last admin |

**Acceptance criteria:**
- Open teams behave exactly as in the MVP for everyone, including anonymous users (regression).
- Private team: non-members (and anonymous users) get **404** on the team, its notes, and note IDs inside it (indistinguishable from nonexistent); `GET /teams` and `GET /notes` never include it for them.
- Members can create, read, list and update notes, view the trash and restore; deleting (trashing) a note requires being its author or an admin (else 403); renaming or deleting the team requires admin (else 403).
- A team can't lose its last admin (demote, remove or leave → 409).
- A removed member immediately loses access (404).

**Commit:** `feat(teams): private teams with membership and roles`

#### F6: Final README *(docs task, section 9.6)*
**Build:** extend the README into the submission version, adding the sections the assignment requires:
- **Design choices I spent the most time on**: section 7 A–C, each as decision / why / tradeoff / rejected alternatives
- **Other decisions**: the minor choices
- **What I'd change, add or stop doing with more time**:
  - *change:* Postgres + `tsvector`, a persistent hosted DB
  - *add:* accounts and private teams if F4–F5 were skipped, rate limiting for the public API, version history, automatic purge of old trash, observability
  - *stop:* leaving the public demo fully writable; possibly the mandatory `If-Match` for clients that accept last-write-wins
- **How this was built**: coder/tester sub-agents, hidden red-baseline tests, CI and deploy verification per commit
- Updated API table and examples for every completed Final task

Extend `examples/walkthrough.sh` with tags, pagination and search.
**Acceptance criteria:** the tester checklist covers every heading above; every implemented endpoint is documented; the walkthrough runs green against `RENDER_URL`; no stale statements (for example "next_cursor is always null").
**Commit:** `docs: design decisions, tradeoffs and future work`
After CI and deploy verification: `git tag v1.0 && git push origin v1.0`.

#### F7 (optional): Dockerfile
Only if the user asks. Docker isn't installed locally, so verification is a CI job running `docker build` and then `curl /health` in the container.
**Commit:** `chore: Dockerfile with CI build check`

---

## 13. If time runs short
Cut in this order: F7 → F5 → F4 → F1 → F3 (document `LIKE` as the fallback) → F2. **Never cut** M0–M8 or F6.

---

## 14. Submission checklist (main agent verifies, then tells the user)
```bash
git log --oneline                         # one commit per task, in order
gh run list --limit 20                    # all green
git tag --list                            # v0.1-mvp, v1.0
gh repo view dhairyasurana007/bluestaq-assessment --json visibility,url
```
- [ ] Every task commit has green CI; tags pushed
- [ ] `RENDER_URL/docs` loads; `scripts/wait_for_deploy.py` verifies HEAD; remote e2e passes
- [ ] Fresh-clone quick start works
- [ ] No secrets, `.db`, `.venv` or logs in the repo (`git ls-files | grep -E "\.db$|\.venv|\.log$"` prints nothing)
- [ ] README has run instructions, live demo, 2–3 design choices, and "what I'd change/add/stop"
- [ ] Tell the user the repo URL and Render URL to submit

---

## 15. Review prep (for the human, not the agent)
- Why no accounts in the MVP? What's the risk, and how do F4–F5 add them without breaking clients?
- How would teams keep their notes apart today? (They can't; teams are organizational. Private teams are the upgrade path.)
- Concurrent edits: why optimistic concurrency, and why not last-write-wins or CRDTs?
- Why soft delete (trash) instead of hard delete? Why no permanent delete or purge yet?
- Why SQLite, and why does the demo reset? What would production storage look like?
- Cursor vs offset pagination; is the cursor tamper-safe?
- Unit vs Playwright e2e: what does each catch?
- How did hidden red-baseline tests change the AI-written code? Examples?
