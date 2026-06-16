from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass
from typing import Any, Iterable
from .const import DEFAULT_RETRIES

import aiohttp


# Bei deiner Secvest besser großzügig sein:
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=60)

# Retries für "wackelige" Embedded APIs:
DEFAULT_RETRIES = 4
DEFAULT_BACKOFF_BASE_S = 1.2   # 1.2s, 2.4s, 4.8s, ...
DEFAULT_JITTER_S = 0.4         # +0..0.4s zufällig


@dataclass
class SecvestAuth:
    username: str
    password: str
    user_code: str


class SecvestApiError(Exception):
    """Base error for Secvest API."""


class SecvestApi:
    """
    Robust Secvest REST client:
    - Retries with backoff on timeouts / connection issues / 5xx
    - 404 fallback for endpoints that are slash-sensitive
    - Always parses JSON from text (Secvest sometimes sends wrong content-type)
    """

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
        # verify_ssl=False => ssl=False (keine Zertifikatsprüfung)
        return True if self._verify_ssl else False

    def _auth_basic(self) -> aiohttp.BasicAuth:
        return aiohttp.BasicAuth(self._auth.username, self._auth.password)

    def _common_headers(self) -> dict[str, str]:
        # Keep-Alive kann Secvest gern "zumachen"/hängen lassen
        return {"Accept": "application/json", "Connection": "close"}

    async def _read_json(self, resp: aiohttp.ClientResponse) -> Any:
        # Robust: immer Text lesen und selbst JSON parsen
        text = (await resp.text()).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise SecvestApiError(f"Response not JSON (status={resp.status}) body={text[:200]}") from e

    async def _request_json(
        self,
        method: str,
        paths: Iterable[str],
        *,
        json_payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        expect_json: bool = True,
    ) -> Any:
        """
        Try request against one or multiple alternative paths (fallback).
        Retries on transient errors.
        """
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

                        # 404: probiere nächsten Path (Slash/No-Slash Fallback)
                        if resp.status == 404 and len(paths_list) > 1:
                            continue

                        # Auth-Fehler nicht retryen
                        if resp.status in (401, 403):
                            raise SecvestApiError(f"Auth failed ({resp.status}) for {url}")

                        # 5xx retryen
                        if 500 <= resp.status <= 599:
                            raise aiohttp.ClientResponseError(
                                request_info=resp.request_info,
                                history=resp.history,
                                status=resp.status,
                                message=f"Server error {resp.status}",
                                headers=resp.headers,
                            )

                        # Sonstige 4xx (außer 404-fallback) -> hart
                        resp.raise_for_status()

                        if not expect_json:
                            return None

                        return await self._read_json(resp)

                except (asyncio.TimeoutError, aiohttp.ClientConnectorError, aiohttp.ServerDisconnectedError,
                        aiohttp.ClientOSError, aiohttp.ClientPayloadError, aiohttp.ClientResponseError) as e:
                    last_exc = e
                    # Retry nach Backoff
                    await asyncio.sleep(self._backoff(attempt))
                    break  # nächster attempt (nicht alle paths sinnlos weiterprobieren)
                except SecvestApiError as e:
                    # Auth/Non-JSON -> hart, kein Retry
                    raise
                except Exception as e:
                    # Unknown -> hart
                    raise SecvestApiError(f"Unexpected error calling {url}: {e!r}") from e

        raise SecvestApiError(f"Request failed after retries: {last_exc!r}") from last_exc

    def _backoff(self, attempt: int) -> float:
        # Exponentieller Backoff + jitter
        base = DEFAULT_BACKOFF_BASE_S * (2 ** (attempt - 1))
        jitter = random.random() * DEFAULT_JITTER_S
        return base + jitter

    # -------------------------
    # Public API
    # -------------------------

    async def get_mode(self) -> str:
        # Deine Secvest: state OHNE trailing slash (slash liefert 404)
        data = await self._request_json(
            "GET",
            paths=(
                "/system/partitions-1/state",   # korrekt bei dir
                "/system/partitions-1/state/",  # fallback falls andere Firmware
            ),
        )
        state = data.get("state") if isinstance(data, dict) else None
        if not isinstance(state, str):
            raise SecvestApiError(f"Invalid mode payload: {data!r}")
        return state

    async def get_zones(self) -> list[dict[str, Any]]:
        # Zones bei Secvest meistens mit trailing slash
        data = await self._request_json(
            "GET",
            paths=(
                "/system/partitions-1/zones/",
                "/system/partitions-1/zones",
            ),
        )
        if not isinstance(data, list):
            raise SecvestApiError(f"Invalid zones payload: {data!r}")
        return data

    async def get_faults(self) -> list[dict[str, Any]]:
        data = await self._request_json(
            "GET",
            paths=(
                "/faults/",
                "/faults",
            ),
        )
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict) and isinstance(data.get("faults"), list):
            return [item for item in data["faults"] if isinstance(item, dict)]
        raise SecvestApiError(f"Invalid faults payload: {data!r}")

    async def get_outputs(self) -> list[dict[str, Any]]:
        data = await self._request_json(
            "GET",
            paths=(
                "/output/",
                "/output",
                "/outputs/",
                "/outputs",
            ),
        )
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict) and isinstance(data.get("outputs"), list):
            return [item for item in data["outputs"] if isinstance(item, dict)]
        raise SecvestApiError(f"Invalid outputs payload: {data!r}")

    async def ack_fault(self, fault_id: str) -> None:
        await self._request_json(
            "PUT",
            paths=(
                f"/faults/{fault_id}/",
                f"/faults/{fault_id}",
            ),
            json_payload={"ack": True, "acknowledge": True},
            headers={"Content-Type": "application/json", "Connection": "close"},
            expect_json=False,
        )

    async def set_mode(self, new_state: str) -> None:
        # PUT endpoint hat bei dir Slash am Ende
        await self._request_json(
            "PUT",
            paths=(
                "/system/partitions-1/",
                "/system/partitions-1",
            ),
            json_payload={"state": new_state, "code": self._auth.user_code},
            headers={"Content-Type": "application/json", "Connection": "close"},
            expect_json=False,
        )
