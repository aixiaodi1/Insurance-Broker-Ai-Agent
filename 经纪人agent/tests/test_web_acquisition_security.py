import pytest

from app.web_acquisition.security import SecurityGate, SecurityViolation


def resolver_for(ip: str):
    return lambda host: [ip]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "data:text/plain,hello",
        "ftp://example.com/file",
        "chrome://version",
    ],
)
def test_security_gate_rejects_forbidden_schemes(url):
    gate = SecurityGate(resolve_host=resolver_for("93.184.216.34"))

    with pytest.raises(SecurityViolation) as exc:
        gate.validate_url(url)

    assert exc.value.code == "scheme_not_allowed"


@pytest.mark.parametrize(
    "url,ip",
    [
        ("http://localhost", "127.0.0.1"),
        ("http://127.0.0.1", "127.0.0.1"),
        ("http://0.0.0.0", "0.0.0.0"),
        ("http://10.1.2.3", "10.1.2.3"),
        ("http://172.16.0.1", "172.16.0.1"),
        ("http://192.168.1.20", "192.168.1.20"),
        ("http://169.254.169.254", "169.254.169.254"),
        ("http://example.com", "224.0.0.1"),
    ],
)
def test_security_gate_rejects_unsafe_hosts_and_resolved_ips(url, ip):
    gate = SecurityGate(resolve_host=resolver_for(ip))

    with pytest.raises(SecurityViolation) as exc:
        gate.validate_url(url)

    assert exc.value.code in {"host_not_allowed", "ip_not_allowed"}


def test_security_gate_allows_allowed_domain_and_subdomain():
    gate = SecurityGate(resolve_host=resolver_for("93.184.216.34"))

    assert gate.validate_url("https://www.example.com/a", allowed_domains=["example.com"]).normalized_url == "https://www.example.com/a"


def test_security_gate_rejects_domain_suffix_spoofing():
    gate = SecurityGate(resolve_host=resolver_for("93.184.216.34"))

    with pytest.raises(SecurityViolation) as exc:
        gate.validate_url("https://example.com.evil.com", allowed_domains=["example.com"])

    assert exc.value.code == "domain_not_allowed"


def test_security_gate_revalidates_redirect_chain():
    gate = SecurityGate(resolve_host=lambda host: ["93.184.216.34"] if host == "example.com" else ["10.0.0.2"])

    with pytest.raises(SecurityViolation) as exc:
        gate.validate_redirect_chain(
            "https://example.com/start",
            ["https://example.com/step", "https://internal.example.test/private"],
            allowed_domains=["example.com"],
        )

    assert exc.value.code in {"domain_not_allowed", "ip_not_allowed"}


def test_security_gate_rejects_too_many_redirects():
    gate = SecurityGate(resolve_host=resolver_for("93.184.216.34"), max_redirects=2)

    with pytest.raises(SecurityViolation) as exc:
        gate.validate_redirect_chain(
            "https://example.com/start",
            ["https://example.com/a", "https://example.com/b", "https://example.com/c"],
            allowed_domains=["example.com"],
        )

    assert exc.value.code == "too_many_redirects"
