from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.domain.errors import AppError, ErrorCode, ProviderError, ProviderErrorKind
from tests.conftest import ALLOWED_ORIGIN

SECRET_DETAIL = "db password is hunter2"


class EchoBody(BaseModel):
    name: str = Field(min_length=1, max_length=5)
    count: int


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    """Base app plus test-only routes that exercise each error path."""

    @app.post("/_test/echo")
    def echo(body: EchoBody) -> EchoBody:
        return body

    @app.get("/_test/app-error")
    def app_error() -> None:
        raise AppError(ErrorCode.DUPLICATE_ITEM, "Already saved.", {"existing_id": "abc"})

    @app.get("/_test/provider-down")
    def provider_down() -> None:
        raise ProviderError(ProviderErrorKind.TIMEOUT, "openai", "sdk text that may echo input")

    @app.get("/_test/boom")
    def boom() -> None:
        raise RuntimeError(SECRET_DETAIL)

    return app


def assert_envelope(body: dict, code: str) -> None:
    assert set(body) == {"error", "request_id"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["message"]


def test_unknown_route_returns_404_envelope(client: TestClient) -> None:
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert_envelope(response.json(), "NOT_FOUND")
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_wrong_method_returns_405_envelope(client: TestClient) -> None:
    response = client.delete("/health")

    assert response.status_code == 405
    assert_envelope(response.json(), "METHOD_NOT_ALLOWED")


def test_validation_error_returns_422_with_field_details(client: TestClient) -> None:
    response = client.post("/_test/echo", json={"name": "far too long", "count": "x"})

    assert response.status_code == 422
    body = response.json()
    assert_envelope(body, "VALIDATION_ERROR")
    fields = {f["loc"]: f for f in body["error"]["details"]["fields"]}
    assert set(fields) == {"body.name", "body.count"}
    assert fields["body.name"]["type"] == "string_too_long"
    assert fields["body.count"]["type"] == "int_parsing"
    assert all(set(f) == {"loc", "message", "type"} for f in fields.values())


def test_malformed_json_returns_422_envelope(client: TestClient) -> None:
    response = client.post(
        "/_test/echo", content=b"{not json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert_envelope(response.json(), "VALIDATION_ERROR")


def test_app_error_maps_code_to_status_and_keeps_details(client: TestClient) -> None:
    response = client.get("/_test/app-error")

    assert response.status_code == 409
    body = response.json()
    assert_envelope(body, "DUPLICATE_ITEM")
    assert body["error"]["details"] == {"existing_id": "abc"}


def test_unhandled_exception_returns_generic_500_with_request_id_and_cors(
    client: TestClient, log_lines: Callable[[], list[dict]]
) -> None:
    response = client.get("/_test/boom", headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 500
    body = response.json()
    assert_envelope(body, "INTERNAL_ERROR")
    assert body["error"]["details"] is None
    assert SECRET_DETAIL not in response.text
    assert "RuntimeError" not in response.text

    request_id = response.headers["X-Request-ID"]
    assert body["request_id"] == request_id
    assert response.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN

    errors = [line for line in log_lines() if line["event"] == "unhandled_exception"]
    assert len(errors) == 1
    assert errors[0]["request_id"] == request_id
    assert errors[0]["level"] == "error"
    assert "Traceback" in errors[0]["exception"]
    assert SECRET_DETAIL in errors[0]["exception"]


def test_provider_error_returns_503_envelope_without_sdk_text(client: TestClient) -> None:
    response = client.get("/_test/provider-down")

    assert response.status_code == 503
    body = response.json()
    assert_envelope(body, "UPSTREAM_UNAVAILABLE")
    assert body["error"]["details"] == {"provider": "openai", "kind": "timeout", "retryable": True}
    assert "sdk text" not in response.text
