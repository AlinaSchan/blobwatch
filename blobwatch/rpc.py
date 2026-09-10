"""a tiny json-rpc client over urllib: fallback across public endpoints, and batches."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

DEFAULT_RPCS = (
    "https://ethereum-rpc.publicnode.com",
    "https://rpc.mevblocker.io",
    "https://eth.drpc.org",
    "https://gateway.tenderly.co/public/mainnet",
    "https://eth-mainnet.public.blastapi.io",
)
USER_AGENT = "blobwatch/0.1 (+https://github.com/alinaschanz/blobwatch)"


class RpcError(Exception):
    """the call itself failed (revert, bad params) - the same answer would come from every node."""


class RpcUnavailable(Exception):
    """no endpoint gave a usable answer."""


class Rpc:
    def __init__(self, urls: tuple[str, ...] | list[str] | None = None, timeout: float = 30.0):
        self.urls = list(urls or DEFAULT_RPCS)
        self.timeout = timeout
        self._lock = threading.Lock()

    def _post(self, url: str, payload) -> object:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())

    def _prefer(self, url: str) -> None:
        """the endpoint that answered goes first next time."""
        with self._lock:
            if url in self.urls and self.urls[0] != url:
                self.urls.remove(url)
                self.urls.insert(0, url)

    def batch(self, calls: list[tuple[str, list]]) -> list:
        """several calls in one http request. an endpoint that refuses batches, times out or fails
        one of the calls is skipped as a whole and the next one gets the same batch."""
        payload = [{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)]
        last_problem: str | None = None
        for url in list(self.urls):
            try:
                body = self._post(url, payload if len(payload) > 1 else payload[0])
            except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
                last_problem = f"{url}: {exc}"
                continue
            answers = body if isinstance(body, list) else [body]
            by_id = {a.get("id"): a for a in answers if isinstance(a, dict)}
            results: list = []
            problem = None
            for i in range(len(calls)):
                answer = by_id.get(i)
                if answer is None:
                    error = answers[0].get("error") if len(answers) == 1 and isinstance(answers[0], dict) else None
                    problem = str(error.get("message", error)) if isinstance(error, dict) else "missing answer in the batch"
                    break
                error = answer.get("error")
                if error:
                    message = str(error.get("message", error)) if isinstance(error, dict) else str(error)
                    if (isinstance(error, dict) and error.get("code") == 3) or "revert" in message.lower():
                        raise RpcError(message)
                    problem = message  # rate limit, internal error: next endpoint
                    break
                results.append(answer.get("result"))
            if problem:
                last_problem = f"{url}: {problem}"
                continue
            self._prefer(url)
            return results
        raise RpcUnavailable(f"no rpc endpoint gave a usable answer ({last_problem})")

    def call(self, method: str, params: list):
        return self.batch([(method, params)])[0]

    def eth_call(self, to: str, data: str, block: str = "latest") -> bytes:
        result = self.call("eth_call", [{"to": to, "data": data}, block])
        return bytes.fromhex((result or "0x")[2:])

    def block_number(self) -> int:
        return int(self.call("eth_blockNumber", []), 16)

    def blocks(self, numbers: list[int], full: bool = True, per_request: int = 5) -> list[dict]:
        """blocks in order; `per_request` of them per http request, single requests when a batch fails everywhere."""
        out: list[dict] = []
        for start in range(0, len(numbers), per_request):
            chunk = numbers[start:start + per_request]
            calls = [("eth_getBlockByNumber", [hex(n), full]) for n in chunk]
            try:
                got = self.batch(calls)
            except RpcUnavailable:
                got = [self.call(*c) for c in calls]
            for n, block in zip(chunk, got, strict=True):
                if not block:
                    raise RpcUnavailable(f"block {n} is not there yet on the endpoint that answered")
                out.append(block)
        return out

    def header(self, number: int | str = "latest") -> dict:
        tag = hex(number) if isinstance(number, int) else number
        return self.call("eth_getBlockByNumber", [tag, False])
