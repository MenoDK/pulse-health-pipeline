"""Who may call what.

Outside the lab every `/api` route needs the API key, compared in constant time. The lab has no login, which is why it
exists only on request and is reachable only as the machine's own name: a request whose Host header is anything else is
refused (a page on another site cannot reach a server on your laptop through DNS rebinding), and a request that changes
something must come from this origin (a page on another site cannot make your browser press the lab's buttons).
"""

from __future__ import annotations

import hmac
import re
from urllib.parse import urlsplit

from fastapi import Header, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from pulse.config import Settings

_LOCAL_HOST = re.compile(r"^(localhost|127\.0\.0\.1|\[::1\])(:\d{1,5})?$", re.IGNORECASE)
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


def host_allowed(host: str) -> bool:
    return bool(_LOCAL_HOST.match(host.strip()))


def same_origin(request: Request) -> bool:
    """True when a state-changing request plainly comes from this site, or from a client with no browser headers."""
    site = request.headers.get("sec-fetch-site")
    if site is not None and site not in {"same-origin", "none"}:
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return True
    return urlsplit(origin).netloc.lower() == request.headers.get("host", "").lower()


class LabGate(BaseHTTPMiddleware):
    """Applied only when the lab is on."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not host_allowed(request.headers.get("host", "")):
            return JSONResponse({"error": "this server answers only to its own name"}, status_code=421)
        if request.method not in _SAFE_METHODS and not same_origin(request):
            return JSONResponse({"error": "cross-site request refused"}, status_code=403)
        return await call_next(request)


class Headers(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["content-security-policy"] = CSP
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["referrer-policy"] = "no-referrer"
        response.headers["cache-control"] = (
            "no-store" if request.url.path.startswith(("/api", "/health")) else "no-cache"
        )
        return response


def api_key_dependency(settings: Settings):  # type: ignore[no-untyped-def]
    expected = settings.api_key.encode()

    def check(x_api_key: str = Header(default="")) -> None:
        if settings.lab_mode:
            return  # the gates above are the protection in the lab
        if not hmac.compare_digest(x_api_key.encode(), expected):
            raise HTTPException(status_code=401, detail="missing or wrong X-API-Key")

    return check
