"""Seed demo data: teams `Platform` and `Research` with 12 notes (1 in Platform's trash).

Usage: python scripts/seed.py [--if-empty] [--force] [--database-url URL]

The script only seeds when env SEED_DEMO_DATA=true or --force is passed; otherwise it prints a
message and exits 0 without touching the database. With --if-empty it does nothing when any team
already exists. It does not run migrations: the schema must already be at head (Render runs
`alembic upgrade head` first).
"""

import argparse
import os
import sys
from datetime import timedelta
from pathlib import Path

# Render runs `python scripts/seed.py`, which puts scripts/ (not the repo root) on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, select  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import make_engine, make_session_factory, utcnow  # noqa: E402
from app.models import Note, Team  # noqa: E402

# (title, body, author_name, in_trash)
PLATFORM_NOTES = [
    (
        "Incident runbook: API latency spike",
        "1. Check the dashboard for p95 latency.\n2. Roll back the last deploy if it correlates.\n"
        "3. Post status updates every 30 minutes.",
        "Alice",
        False,
    ),
    (
        "On-call handoff checklist",
        "- Review open alerts\n- Note any flaky jobs\n- Hand over the pager at 09:00 UTC",
        "Bob",
        False,
    ),
    (
        "Deploy checklist",
        "Green CI, migrations reviewed, feature flags set, rollback plan written down.",
        "Carol",
        False,
    ),
    (
        "Postmortem template",
        "Summary, impact, timeline, root cause, what went well, follow-up actions.",
        "Alice",
        False,
    ),
    (
        "Onboarding: first week",
        "Get repo access, run the app locally, ship a small fix, shadow one on-call shift.",
        "Bob",
        False,
    ),
    (
        "Capacity planning notes",
        "Traffic doubles every quarter. Revisit instance sizes before the next launch.",
        "Carol",
        False,
    ),
    (
        "Old staging credentials (outdated)",
        "Superseded by the new secrets manager. Kept in the trash so it can be restored.",
        "Bob",
        True,
    ),
]

RESEARCH_NOTES = [
    (
        "Reading list: distributed systems",
        "Dynamo, Raft, Spanner, and a survey of CRDTs.",
        "Carol",
        False,
    ),
    (
        "Interview synthesis: note-taking habits",
        "Most people want fast capture first and organization second.",
        "Alice",
        False,
    ),
    (
        "Experiment log: search ranking",
        "BM25 with a title boost beat plain term frequency on the sample queries.",
        "Bob",
        False,
    ),
    (
        "Open questions",
        "How should concurrent edits be merged? Do teams want private spaces?",
        "Alice",
        False,
    ),
    (
        "Conference notes",
        "Keynote highlights, hallway ideas, and people to follow up with.",
        "Carol",
        False,
    ),
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed demo teams and notes.")
    parser.add_argument(
        "--if-empty", action="store_true", help="do nothing if any team already exists"
    )
    parser.add_argument("--force", action="store_true", help="seed even without SEED_DEMO_DATA")
    parser.add_argument(
        "--database-url", default=None, help="defaults to env DATABASE_URL (see app.config)"
    )
    return parser.parse_args(argv)


def build_team(session, name: str, notes: list[tuple], offset_minutes: int) -> int:
    """Add one team and its notes. Returns the number of notes in the trash."""
    now = utcnow()
    team_time = now - timedelta(minutes=offset_minutes + len(notes) + 1)
    team = Team(name=name, created_at=team_time, updated_at=team_time)
    session.add(team)
    session.flush()
    trashed = 0
    for i, (title, body, author, in_trash) in enumerate(notes):
        stamp = team_time + timedelta(minutes=i + 1)
        note = Note(
            team_id=team.id,
            title=title,
            body=body,
            author_name=author,
            version=1,
            created_at=stamp,
            updated_at=stamp,
            deleted_at=now if in_trash else None,
        )
        session.add(note)
        trashed += in_trash
    return trashed


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    enabled = os.environ.get("SEED_DEMO_DATA", "").strip().lower() == "true"
    if not (enabled or args.force):
        print("Skipping seed: set SEED_DEMO_DATA=true or pass --force to seed demo data.")
        return 0

    database_url = args.database_url or Settings().database_url
    engine = make_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        if not {"teams", "notes"} <= tables:
            print(
                "Error: database schema is missing; run `alembic upgrade head` first.",
                file=sys.stderr,
            )
            return 1

        factory = make_session_factory(engine)
        with factory() as session:
            if args.if_empty and session.execute(select(Team.id).limit(1)).first() is not None:
                print("Skipping seed: teams already exist (--if-empty).")
                return 0
            trashed = build_team(session, "Platform", PLATFORM_NOTES, 20)
            trashed += build_team(session, "Research", RESEARCH_NOTES, 0)
            session.commit()
        total = len(PLATFORM_NOTES) + len(RESEARCH_NOTES)
        print(f"Seeded 2 teams and {total} notes ({trashed} in trash).")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
