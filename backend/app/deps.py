"""FastAPI dependencies. Handlers get collaborators from here, never from module globals."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request

from app.config import Settings
from app.providers.base import ChatModel, Embedder, Reranker
from app.providers.factory import Providers
from app.services.answering import AnsweringService
from app.services.retrieval import RetrievalConfig, RetrievalService
from app.services.submission import SubmissionService
from app.services.verification import VerificationService
from app.store.repository import Repository
from app.store.session import repository_session
from app.worker import IngestionWorker


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


def get_repository(request: Request) -> Iterator[Repository]:
    """One connection per request, closed after the response is sent."""
    settings = get_settings(request)
    with repository_session(settings.db_path, settings.embedding_dim) as repo:
        yield repo


def get_worker(request: Request) -> IngestionWorker:
    return request.app.state.worker


def get_submission(
    request: Request, repo: Annotated[Repository, Depends(get_repository)]
) -> SubmissionService:
    return SubmissionService(repo, note_max_chars=get_settings(request).note_max_chars)


def get_answering(
    request: Request, repo: Annotated[Repository, Depends(get_repository)]
) -> AnsweringService:
    settings = get_settings(request)
    providers = get_providers(request)
    config = RetrievalConfig(
        candidates=settings.retrieval_candidates,
        rrf_k=settings.rrf_k,
        max_chunks_per_item=settings.max_chunks_per_item,
        min_full=settings.relevance_min_full,
        min_partial=settings.relevance_min_partial,
    )
    retrieval = RetrievalService(repo, providers.embedder, providers.reranker, config)
    verification = None
    if providers.verifier is not None:
        verification = VerificationService(
            providers.verifier,
            providers.escalation,
            escalate_below=settings.verify_escalate_below,
        )
    return AnsweringService(
        retrieval,
        providers.chat,
        question_max_chars=settings.question_max_chars,
        verification=verification,
    )


SettingsDep = Annotated[Settings, Depends(get_settings)]
RepositoryDep = Annotated[Repository, Depends(get_repository)]
WorkerDep = Annotated[IngestionWorker, Depends(get_worker)]
SubmissionDep = Annotated[SubmissionService, Depends(get_submission)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder)]
ChatModelDep = Annotated[ChatModel, Depends(get_chat_model)]
RerankerDep = Annotated[Reranker | None, Depends(get_reranker)]
AnsweringDep = Annotated[AnsweringService, Depends(get_answering)]
