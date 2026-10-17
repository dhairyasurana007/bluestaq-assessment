"""Data access for teams."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Team


def create_team(session: Session, name: str) -> Team:
    team = Team(name=name)
    session.add(team)
    session.commit()
    return team


def list_teams(session: Session, limit: int) -> list[Team]:
    stmt = select(Team).order_by(Team.created_at.desc(), Team.id.desc()).limit(limit)
    return list(session.scalars(stmt))


def get_team(session: Session, team_id: str) -> Team | None:
    return session.get(Team, team_id)


def rename_team(session: Session, team: Team, name: str) -> Team:
    now = utcnow()
    if now <= team.updated_at:  # guarantee a strictly later timestamp
        now = team.updated_at + timedelta(microseconds=1)
    team.name = name
    team.updated_at = now
    session.commit()
    return team


def delete_team(session: Session, team: Team) -> None:
    session.delete(team)
    session.commit()
