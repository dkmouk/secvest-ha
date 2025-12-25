from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass
from typing import Any, Iterable

import aiohttp


DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=60)

DEFAULT_RETRIES = 4
DEFAULT_BACKOFF_BASE_S = 1.2
DEFAULT_JITTER_S = 0.4


@dataclass
class SecvestAuth:
    username: str
    password: str
    user_code: str


class SecvestApiError(Exception):
    """Base error for Secvest API."""


class SecvestApi:
    """Robust Secvest REST client."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        auth: SecvestAuth,
        verify_ssl: bool,
        timeout: aiohttp.ClientTimeout = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
    ) -> None:
        self._session = session
        self._host = host.rstrip("/")
        self._auth = auth
        self._verify_ssl = verify_ssl
        self._timeout = timeout
        self._retries = retries

    def _url(self, path: str) -> str:
        return f"{self._host}{path}"

    def _ssl(self) -> bool:
        return True if self._verify_ssl else False

    def _auth_basic(self) -> aiohttp.BasicAuth:
        return aiohttp.BasicAuth(self._auth.username, self._auth.password)

    def _common_headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Connection": "close"}

    async def _read_json(self, resp: aiohttp.ClientResponse) -> Any:
        text = (await resp.text()).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise SecvestApiError(
                f"Response not JSON (status={resp.status}) body={text[:200]}"
            ) from e

    def _backoff(self, attempt: int) -> float:
        base = DEFAULT_BACKOFF_BASE_S * (2 ** (attempt - 1))
        jitter = random.random() * DEFAULT_JITTER_S
        return base + jitter

    async def _request_json(
        self,
        method: str,
        paths: Iterable[str],
        *,
        json_payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        expect_json: bool = True,
    ) -> Any:
        last_exc: Exception | None = None
        paths_list = list(paths)

        for attempt in range(1, self._retries + 1):
            for path in paths_list:
                url = self._url(path)
                try:
                    async with self._session.request(
                        method,
                        url,
                        json=json_payload,
                        auth=self._auth_basic(),
                        ssl=self._ssl(),
                        timeout=self._timeout,
                        headers=headers or self._common_headers(),
                    ) as resp:
                        if resp.status == 404 and len(paths_list) > 1:
                            continue

                        if resp.status in (401, 403):
                            raise SecvestApiError(f"Auth failed ({resp.status}) for {url}")

                        if resp.status == 409:
                            body = (await resp.text()).strip()
                            raise SecvestApiError(f"409 Conflict from Secvest: {body[:300]}")

                        if 400 <= resp.status <= 499:
                            body = (await resp.text()).strip()
                            raise SecvestApiError(f"HTTP {resp.status} from Secvest: {body[:300]}")

                        if 500 <= resp.status <= 599:
                            raise aiohttp.ClientResponseError(
                                request_info=resp.request_info,
                                history=resp.history,
                                status=resp.status,
                                message=f"Server error {resp.status}",
                                headers=resp.headers,
                            )

                        resp.raise_for_status()

                        if not expect_json:
                            return None

                        return await self._read_json(resp)

                except (
                    asyncio.TimeoutError,
                    aiohttp.ClientConnectorError,
                    aiohttp.ServerDisconnectedError,
                    aiohttp.ClientOSError,
                    aiohttp.ClientPayloadError,
                    aiohttp.ClientResponseError,
                ) as e:
                    last_exc = e
                    await asyncio.sleep(self._backoff(attempt))
                    break
                except SecvestApiError:
                    raise
                except Exception as e:
                    raise SecvestApiError(f"Unexpected error calling {url}: {e!r}") from e

        raise SecvestApiError(f"Request failed after retries: {last_exc!r}") from last_exc

    async def get_mode(self) -> str:
        data = await self._request_json(
            "GET",
            paths=("/system/partitions-1/state", "/system/partitions-1/state/"),
        )
        state = data.get("state") if isinstance(data, dict) else None
        if not isinstance(state, str):
            raise SecvestApiError(f"Invalid mode payload: {data!r}")
        return state

    async def get_zones(self) -> list[dict[str, Any]]:
        data = await self._request_json(
            "GET",
            paths=("/system/partitions-1/zones/", "/system/partitions-1/zones"),
        )
        if not isinstance(data, list):
            raise SecvestApiError(f"Invalid zones payload: {data!r}")
        return data

    async def set_mode(self, new_state: str) -> None:
        await self._request_json(
            "PUT",
            paths=("/system/partitions-1/", "/system/partitions-1"),
            json_payload={"state": new_state, "code": str(self._auth.user_code)},
            headers={"Content-Type": "application/json", "Connection": "close"},
            expect_json=False,
        )
