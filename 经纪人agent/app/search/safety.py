from __future__ import annotations

import re
import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse


@dataclass(slots=True)
class PromptInjectionReport:
    suspected: bool
    flags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EgressDecision:
    allowed: bool
    reason: str = ""


class PromptInjectionGuard:
    def scan(self, text: str) -> PromptInjectionReport:
        lowered = text.lower()
        flags: list[str] = []
        if re.search(r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above)\b.{0,30}\binstructions?\b", lowered):
            flags.append("instruction_override")
        if "system prompt" in lowered or "developer message" in lowered:
            flags.append("system_prompt_exfiltration")
        if "api key" in lowered or "secret key" in lowered:
            flags.append("secret_exfiltration")
        if "tool call" in lowered or "call the tool" in lowered:
            flags.append("tool_use_instruction")
        if re.search(r"https?://[^\s]+/(collect|exfil|callback|send)", lowered):
            flags.append("external_exfiltration_url")
        return PromptInjectionReport(suspected=bool(flags), flags=flags)


class EgressGuard:
    SENSITIVE_QUERY_KEYS = {
        "api_key",
        "apikey",
        "key",
        "token",
        "secret",
        "system_prompt",
        "developer_message",
        "conversation",
        "chat_history",
        "memory",
    }

    def validate_url(self, url: str) -> EgressDecision:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if any(key.lower() in self.SENSITIVE_QUERY_KEYS for key in query):
            return EgressDecision(allowed=False, reason="sensitive_query_parameter")
        return EgressDecision(allowed=True)


def unsafe_public_url_reason(url: str, resolve_host=None) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        return "scheme_not_allowed"
    host = parsed.hostname or ""
    if not host or host.lower() == "localhost":
        return "host_not_allowed"
    resolver = resolve_host or _resolve_host
    try:
        addresses = [host] if _is_ip(host) else resolver(host)
    except Exception:
        return "dns_resolution_failed"
    for value in addresses:
        try:
            ip = ipaddress.ip_address(value)
        except ValueError:
            return "ip_not_allowed"
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return "ip_not_allowed"
    return ""


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _resolve_host(host: str) -> list[str]:
    return sorted({item[4][0] for item in socket.getaddrinfo(host, None)})
