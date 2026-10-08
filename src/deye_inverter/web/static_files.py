"""Static files the browser must re-validate, so a redeploy is seen at once."""

from __future__ import annotations

from typing import Any

from fastapi.staticfiles import StaticFiles
from starlette.responses import Response


class RevalidatedStaticFiles(StaticFiles):  # type: ignore[misc,unused-ignore]
    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        # Cached copies are kept but checked (ETag / Last-Modified) before each use.
        response.headers["Cache-Control"] = "no-cache"
        return response
