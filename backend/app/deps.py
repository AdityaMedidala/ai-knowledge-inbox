"""FastAPI dependencies. Handlers get collaborators from here, never from module globals."""

from typing import Annotated

from fastapi import Depends, Request

from app.config import Settings
from app.providers.base import ChatModel, Embedder, Reranker
from app.providers.factory import Providers


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_providers(request: Request) -> Providers:
    return request.app.state.providers


def get_embedder(request: Request) -> Embedder:
    return get_providers(request).embedder


def get_chat_model(request: Request) -> ChatModel:
    return get_providers(request).chat


def get_reranker(request: Request) -> Reranker | None:
    return get_providers(request).reranker


SettingsDep = Annotated[Settings, Depends(get_settings)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder)]
ChatModelDep = Annotated[ChatModel, Depends(get_chat_model)]
RerankerDep = Annotated[Reranker | None, Depends(get_reranker)]
