"""FastAPI endpoints for preview-first Gmail cleanup."""

from __future__ import annotations

import hmac
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from .command_parser import build_parser
from .config import Settings
from .database import Database
from .models import SenderCreate
from .service import GmailCleanerService


class CommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=2000)


class ConfirmRequest(BaseModel):
    preview_id: str
    confirm: bool


def create_app(
    *, settings: Settings | None = None, database: Database | None = None
) -> FastAPI:
    settings = settings or Settings.from_env()
    database = database or Database(settings.database_path)
    database.initialize()

    app = FastAPI(
        title="Gmail Cleaner Agent API",
        description=(
            "Natural-language, sender-based Gmail cleanup. Searches are preview-only; "
            "moving messages to Trash requires a separate confirmation request."
        ),
        version="0.1.0",
    )
    app.state.settings = settings
    app.state.database = database

    def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = settings.api_bearer_token
        if not expected:
            return
        supplied = authorization or ""
        if supplied.lower().startswith("bearer "):
            supplied = supplied[7:].strip()
        if not hmac.compare_digest(supplied, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid API bearer token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def service() -> GmailCleanerService:
        return GmailCleanerService(
            settings=settings,
            database=database,
            parser=build_parser(settings.openai_api_key, settings.openai_model),
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/v1/senders", dependencies=[Depends(authorize)])
    def list_senders() -> dict[str, Any]:
        return {"senders": database.list_senders()}

    @app.post("/api/v1/senders", dependencies=[Depends(authorize)])
    def add_sender(request: SenderCreate) -> dict[str, Any]:
        try:
            return {"sender": service().add_sender(request)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/v1/senders/{name_or_email}", dependencies=[Depends(authorize)])
    def remove_sender(name_or_email: str) -> dict[str, Any]:
        removed = database.remove_sender(name_or_email)
        if not removed:
            raise HTTPException(status_code=404, detail="Saved sender not found.")
        return {"removed": name_or_email}

    @app.post("/api/v1/commands", dependencies=[Depends(authorize)])
    def execute_command(request: CommandRequest) -> dict[str, Any]:
        try:
            return service().execute_command(request.command)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Gmail or AI service request failed ({type(exc).__name__}). Check server logs.",
            ) from exc

    @app.post("/api/v1/actions/confirm", dependencies=[Depends(authorize)])
    def confirm_action(request: ConfirmRequest) -> dict[str, Any]:
        try:
            return service().confirm_preview(request.preview_id, request.confirm)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Gmail action failed ({type(exc).__name__}). Check server logs.",
            ) from exc

    @app.get("/api/v1/history", dependencies=[Depends(authorize)])
    def history(limit: int = 50) -> dict[str, Any]:
        return {"history": database.list_history(limit)}

    return app


app = create_app()
