"""FastAPI dependencies. Handlers get collaborators from here, never from module globals."""

from typing import Annotated

from fastapi import Depends, Request

from app.config import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


SettingsDep = Annotated[Settings, Depends(get_settings)]
