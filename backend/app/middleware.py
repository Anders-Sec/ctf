"""Cross-cutting request middleware."""

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.logging import get_logger, request_id_var

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a request id to the log context and echo it back to the caller.

    An inbound id is trusted only as far as correlation goes — it is never used
    for authorization — so accepting one from an ingress or a load test is safe
    and makes traces line up end to end.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        # Cap it: an inbound header is attacker-controlled and ends up in logs.
        request_id = request_id[:64]

        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()

        try:
            try:
                response = await call_next(request)
            except Exception:
                # The exception handler produces the response; log the timing here
                # so failed requests are as measurable as successful ones.
                logger.exception(
                    "request_failed",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    },
                )
                raise

            response.headers[REQUEST_ID_HEADER] = request_id
            logger.info(
                "request_completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            return response
        finally:
            # Reset last, so the completion log above still carries the id.
            request_id_var.reset(token)
