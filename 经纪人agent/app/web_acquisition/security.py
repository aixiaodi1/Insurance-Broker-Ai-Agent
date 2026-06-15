from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse


ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_HOSTS = {"localhost"}
METADATA_IPS = {ipaddress.ip_address("169.254.169.254")}


class SecurityViolation(ValueError):
    def __init__(self, code: str, message: str, url: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.url = url


@dataclass(slots=True)
class SecurityCheckResult:
    normalized_url: str
    host: str
    resolved_ips: list[str]


class SecurityGate:
    def __init__(self, resolve_host=None, max_redirects: int = 5) -> None:
        self._resolve_host = resolve_host or self._default_resolve_host
        self.max_redirects = max_redirects

    def validate_url(self, url: str, allowed_domains: list[str] | None = None) -> SecurityCheckResult:
        parsed = urlparse(url.strip())
        if parsed.scheme.lower() not in ALLOWED_SCHEMES:
            raise SecurityViolation("scheme_not_allowed", f"URL scheme is not allowed: {parsed.scheme}", url)
        if not parsed.hostname:
            raise SecurityViolation("host_required", "URL host is required", url)

        host = parsed.hostname.lower().strip(".")
        if host in BLOCKED_HOSTS:
            raise SecurityViolation("host_not_allowed", f"Host is not allowed: {host}", url)
        if allowed_domains and not self._domain_allowed(host, allowed_domains):
            raise SecurityViolation("domain_not_allowed", f"Host is outside allowed domains: {host}", url)

        resolved_ips = self._resolve_or_parse_ip(host)
        for ip_text in resolved_ips:
            self._validate_ip(ip_text, url)

        normalized = urlunparse(parsed._replace(fragment=""))
        return SecurityCheckResult(normalized_url=normalized, host=host, resolved_ips=resolved_ips)

    def validate_redirect_chain(
        self,
        initial_url: str,
        redirect_chain: list[str],
        allowed_domains: list[str] | None = None,
    ) -> list[SecurityCheckResult]:
        if len(redirect_chain) > self.max_redirects:
            raise SecurityViolation("too_many_redirects", "Redirect chain exceeds maximum redirects", initial_url)
        results = [self.validate_url(initial_url, allowed_domains=allowed_domains)]
        for target in redirect_chain:
            results.append(self.validate_url(target, allowed_domains=allowed_domains))
        return results

    def _resolve_or_parse_ip(self, host: str) -> list[str]:
        try:
            ipaddress.ip_address(host)
            return [host]
        except ValueError:
            return self._resolve_host(host)

    def _validate_ip(self, ip_text: str, url: str) -> None:
        ip = ipaddress.ip_address(ip_text)
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip in METADATA_IPS
        ):
            raise SecurityViolation("ip_not_allowed", f"Resolved IP is not allowed: {ip}", url)

    def _domain_allowed(self, host: str, allowed_domains: list[str]) -> bool:
        normalized = [domain.lower().strip(".") for domain in allowed_domains]
        return any(host == domain or host.endswith(f".{domain}") for domain in normalized)

    def _default_resolve_host(self, host: str) -> list[str]:
        infos = socket.getaddrinfo(host, None)
        return sorted({info[4][0] for info in infos})
