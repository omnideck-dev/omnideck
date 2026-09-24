"""Small synchronous HTTP client for API-level E2E tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from http.client import HTTPResponse
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class ApiResponse:
    """Buffered response returned by ``ApiClient``."""

    status: int
    body: bytes

    @property
    def text(self) -> str:
        """Decode the response body as UTF-8 text."""
        return self.body.decode("utf-8")

    def json(self) -> Any:
        """Decode the response body as JSON."""
        return json.loads(self.body)


class ApiClient:
    """Call the public API of an already-running E2E application."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def get(self, path: str, *, timeout: float = 10) -> ApiResponse:
        """Issue a GET request."""
        return self.request("GET", path, timeout=timeout)

    def post(
        self,
        path: str,
        *,
        data: object | None = None,
        timeout: float = 10,
    ) -> ApiResponse:
        """Issue a POST request with an optional JSON body."""
        return self.request("POST", path, data=data, timeout=timeout)

    def delete(self, path: str, *, timeout: float = 10) -> ApiResponse:
        """Issue a DELETE request."""
        return self.request("DELETE", path, timeout=timeout)

    def open_stream(
        self,
        method: str,
        path: str,
        *,
        data: object | None = None,
        timeout: float = 10,
    ) -> HTTPResponse:
        """Open a response without buffering it so a test can disconnect."""
        body = json.dumps(data).encode("utf-8") if data is not None else None
        headers = {"X-Requested-With": "XMLHttpRequest"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self._base_url}/{path.lstrip('/')}",
            data=body,
            headers=headers,
            method=method,
        )
        return urlopen(request, timeout=timeout)

    def request(
        self,
        method: str,
        path: str,
        *,
        data: object | None = None,
        timeout: float = 10,
    ) -> ApiResponse:
        """Issue one request and buffer success or HTTP-error responses."""
        body = json.dumps(data).encode("utf-8") if data is not None else None
        headers = {"X-Requested-With": "XMLHttpRequest"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self._base_url}/{path.lstrip('/')}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return ApiResponse(status=response.status, body=response.read())
        except HTTPError as exc:
            return ApiResponse(status=exc.code, body=exc.read())
