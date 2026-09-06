"""Tests for the API-wide error envelope (spec 001).

Every later spec relies on this shape: the frontend switches on `error.code` and
never parses `error.message`.
"""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.errors import AppError, ConflictError, NotFoundError


async def test_unknown_route_uses_the_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Not Found"},
    }


async def test_app_error_subclasses_carry_their_code(app: FastAPI) -> None:
    @app.get("/api/test/conflict")
    async def _conflict() -> None:
        raise ConflictError("That party name is taken.")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/test/conflict")

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "conflict",
        "message": "That party name is taken.",
    }


async def test_app_error_details_are_included_when_present(app: FastAPI) -> None:
    @app.get("/api/test/details")
    async def _details() -> None:
        raise AppError(
            "Too many attempts.",
            code="rate_limited",
            status_code=429,
            details={"retry_after_seconds": 30},
        )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/test/details")

    assert response.status_code == 429
    assert response.json()["error"]["details"] == {"retry_after_seconds": 30}


async def test_not_found_error_maps_to_404(app: FastAPI) -> None:
    @app.get("/api/test/missing")
    async def _missing() -> None:
        raise NotFoundError()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/test/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_validation_errors_report_the_offending_fields(app: FastAPI) -> None:
    from pydantic import BaseModel

    class _Body(BaseModel):
        name: str
        size: int

    @app.post("/api/test/validate")
    async def _validate(body: _Body) -> dict[str, str]:
        return {"name": body.name}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/test/validate", json={"name": "goblins"})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]["fields"] == [{"field": "size", "reason": "Field required"}]


async def test_unhandled_exceptions_never_leak_internals(app: FastAPI) -> None:
    """A traceback reaching a player could contain a flag or a connection string."""
    secret = "FLAG{do-not-leak-me}"

    @app.get("/api/test/boom")
    async def _boom() -> None:
        raise RuntimeError(f"failed while checking {secret}")

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/test/boom")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert secret not in response.text
    assert "RuntimeError" not in response.text
