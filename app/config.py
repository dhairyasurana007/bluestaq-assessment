from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings, read from the environment (e.g. DATABASE_URL)."""

    database_url: str = "sqlite:///./notes.db"
