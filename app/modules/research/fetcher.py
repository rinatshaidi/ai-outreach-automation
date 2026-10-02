"""SSRF-safe, bounded HTTP fetcher for public company research sources."""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx

ResolvedAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str], Awaitable[list[ResolvedAddress]]]


class SafeFetchError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FetchedDocument:
    requested_url: str
    final_url: str
    redirect_chain: list[str]
    status_code: int
    content_type: str
    body: bytes


async def resolve_public_addresses(hostname: str) -> list[ResolvedAddress]:
    loop = asyncio.get_running_loop()
    try:
        records = await asyncio.wait_for(
            loop.getaddrinfo(hostname, None, type=socket.SOCK_STREAM),
            timeout=10,
        )
    except (TimeoutError, OSError, socket.gaierror) as exc:
        raise SafeFetchError(
            "dns_resolution_failed", "Public hostname could not be resolved"
        ) from exc
    return list({ipaddress.ip_address(record[4][0]) for record in records})


def normalize_public_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise SafeFetchError("invalid_scheme", "Only http and https URLs are allowed")
    if parsed.username or parsed.password:
        raise SafeFetchError("userinfo_forbidden", "Credentials in research URLs are forbidden")
    if not parsed.hostname:
        raise SafeFetchError("missing_hostname", "A public hostname is required")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise SafeFetchError("private_address", "Localhost research targets are forbidden")
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise SafeFetchError("invalid_hostname", "Hostname is invalid") from exc
    try:
        port = parsed.port
    except ValueError as exc:
        raise SafeFetchError("invalid_port", "URL port is invalid") from exc
    if port not in {None, 80, 443}:
        raise SafeFetchError("port_forbidden", "Only standard HTTP ports are allowed")
    default_port = (parsed.scheme.lower() == "http" and port == 80) or (
        parsed.scheme.lower() == "https" and port == 443
    )
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))


def address_is_forbidden(address: ResolvedAddress) -> bool:
    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


class SafeFetcher:
    def __init__(
        self,
        *,
        resolver: Resolver = resolve_public_addresses,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 10,
        max_bytes: int = 1_000_000,
        max_redirects: int = 3,
        minimum_host_interval: float = 0.5,
        respect_robots: bool = True,
    ) -> None:
        self.resolver = resolver
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.minimum_host_interval = minimum_host_interval
        self.respect_robots = respect_robots
        self._last_request: dict[str, float] = {}
        self._rate_lock = asyncio.Lock()

    async def _validate_target(self, url: str) -> str:
        normalized = normalize_public_url(url)
        hostname = urlsplit(normalized).hostname
        if hostname is None:
            raise SafeFetchError("missing_hostname", "A public hostname is required")
        addresses = await self.resolver(hostname)
        if not addresses or any(address_is_forbidden(address) for address in addresses):
            raise SafeFetchError(
                "private_address", "Private or special-purpose targets are forbidden"
            )
        return normalized

    async def _rate_limit(self, hostname: str) -> None:
        async with self._rate_lock:
            elapsed = monotonic() - self._last_request.get(hostname, 0)
            delay = self.minimum_host_interval - elapsed
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request[hostname] = monotonic()

    async def _request(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        hostname = urlsplit(url).hostname or ""
        await self._rate_limit(hostname)
        try:
            request = client.build_request(
                "GET", url, headers={"User-Agent": "OutreachOpportunityResearchBot/0.1"}
            )
            return await client.send(request, stream=True)
        except httpx.TimeoutException as exc:
            raise SafeFetchError("fetch_timeout", "Research source timed out") from exc
        except httpx.HTTPError as exc:
            raise SafeFetchError("fetch_failed", "Research source could not be fetched") from exc

    async def _read_limited(self, response: httpx.Response) -> bytes:
        declared_length = response.headers.get("content-length")
        if declared_length:
            try:
                if int(declared_length) > self.max_bytes:
                    raise SafeFetchError(
                        "content_too_large", "Research source exceeds the size limit"
                    )
            except ValueError as exc:
                raise SafeFetchError("invalid_response", "Content-Length is invalid") from exc
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self.max_bytes:
                raise SafeFetchError("content_too_large", "Research source exceeds the size limit")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _robots_allowed(self, client: httpx.AsyncClient, url: str) -> bool:
        parsed = urlsplit(url)
        robots_url = urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
        response = await self._request(client, robots_url)
        try:
            if response.status_code >= 400:
                return True
            if response.is_redirect:
                return False
            body = await self._read_limited(response)
            parser = RobotFileParser()
            parser.set_url(robots_url)
            parser.parse(body.decode(response.encoding or "utf-8", errors="replace").splitlines())
            return parser.can_fetch("OutreachOpportunityResearchBot", url)
        finally:
            await response.aclose()

    async def fetch(self, raw_url: str) -> FetchedDocument:
        current = await self._validate_target(raw_url)
        requested = current
        redirect_chain: list[str] = []
        timeout = httpx.Timeout(self.timeout_seconds)
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            if self.respect_robots and not await self._robots_allowed(client, current):
                raise SafeFetchError("robots_denied", "robots.txt does not allow this research URL")
            for _ in range(self.max_redirects + 1):
                response = await self._request(client, current)
                try:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise SafeFetchError("invalid_redirect", "Redirect has no destination")
                        redirect_chain.append(current)
                        current = await self._validate_target(urljoin(current, location))
                        continue
                    if response.status_code >= 400:
                        raise SafeFetchError(
                            "http_error", f"Research source returned HTTP {response.status_code}"
                        )
                    content_type = (
                        response.headers.get("content-type", "").split(";", maxsplit=1)[0].lower()
                    )
                    if content_type not in {
                        "text/html",
                        "text/plain",
                        "application/xhtml+xml",
                    }:
                        raise SafeFetchError(
                            "unsupported_content_type", "Only HTML and plain text are accepted"
                        )
                    body = await self._read_limited(response)
                    return FetchedDocument(
                        requested_url=requested,
                        final_url=current,
                        redirect_chain=redirect_chain,
                        status_code=response.status_code,
                        content_type=content_type,
                        body=body,
                    )
                finally:
                    await response.aclose()
        raise SafeFetchError("redirect_limit", "Research source exceeded the redirect limit")
