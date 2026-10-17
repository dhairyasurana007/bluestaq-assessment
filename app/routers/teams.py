"""Team space endpoints (PLAN.md section 5.3, endpoints 2-6)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import NotFoundError
from app.models import Team
from app.repositories import teams as repo
from app.schemas import TeamCreate, TeamList, TeamOut, TeamUpdate

router = APIRouter(prefix="/api/v1/teams", tags=["teams"])

SessionDep = Annotated[Session, Depends(get_session)]


def _require_team(session: Session, team_id: UUID) -> Team:
    team = repo.get_team(session, str(team_id))
    if team is None:
        raise NotFoundError("Team not found.")
    return team


@router.post("", status_code=201, response_model=TeamOut)
def create_team(body: TeamCreate, response: Response, session: SessionDep) -> Team:
    team = repo.create_team(session, body.name)
    response.headers["Location"] = f"/api/v1/teams/{team.id}"
    return team


@router.get("", response_model=TeamList)
def list_teams(session: SessionDep, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> TeamList:
    items = repo.list_teams(session, limit)
    return TeamList(items=[TeamOut.model_validate(t) for t in items])


@router.get("/{team_id}", response_model=TeamOut)
def get_team(team_id: UUID, session: SessionDep) -> Team:
    return _require_team(session, team_id)


@router.patch("/{team_id}", response_model=TeamOut)
def update_team(team_id: UUID, body: TeamUpdate, session: SessionDep) -> Team:
    team = _require_team(session, team_id)
    return repo.rename_team(session, team, body.name)


@router.delete("/{team_id}", status_code=204)
def delete_team(team_id: UUID, session: SessionDep) -> Response:
    team = _require_team(session, team_id)
    repo.delete_team(session, team)
    return Response(status_code=204)
