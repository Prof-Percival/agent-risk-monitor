import re
from collections.abc import Callable
from urllib.parse import urlparse

from .models import Analysis, Finding

SECRET_PATH_PATTERNS = (
    re.compile(r"(^|/)\.env(\.|$)"),
    re.compile(r"(^|/)id_(rsa|dsa|ecdsa|ed25519)$"),
    re.compile(r"\.aws/credentials$"),
    re.compile(r"(^|/)\.ssh/"),
    re.compile(r"\.(pem|p12|pfx)$"),
    re.compile(r"(^|/)(credentials|secrets)\.(json|ya?ml)$"),
    re.compile(r"(^|/)\.npmrc$|(^|/)\.pypirc$"),
    re.compile(r"/var/run/secrets/"),
)

# A download whose output is handed straight to an interpreter. The shape matters, not the command.
EXECUTION_PATTERNS = (
    (
        re.compile(r"\b(curl|wget)\b[^|;]*\|\s*(sudo\s+)?(ba|z|k|da)?sh\b"),
        "download piped to a shell",
    ),
    (
        re.compile(r"\bbase64\b[^|;]*(-d|--decode)[^|;]*\|\s*(ba|z|k|da)?sh\b"),
        "base64 decoded into a shell",
    ),
    (
        re.compile(r"\b(curl|wget)\b[^|;]*\|\s*(python3?|perl|ruby|node)\b"),
        "download piped to an interpreter",
    ),
    (re.compile(r"\b(curl|wget)\b.*&&.*chmod\s+\+x.*&&"), "download made executable and run"),
    (re.compile(r"\beval\b[^|;]*\$\(\s*(curl|wget)\b"), "remote content evaluated"),
)

PRIVILEGE_PATTERNS = (
    re.compile(r"\bsudo\b"),
    re.compile(r"--privileged\b"),
    re.compile(r"\brunas\b|\bsetuid\b"),
)

BROAD_PATHS = {"/", "/etc", "/root", "/home", "~", "/var", "C:\\", "C:/"}


def is_secret_path(path: str) -> bool:
    return any(pattern.search(path) for pattern in SECRET_PATH_PATTERNS)


def secret_file_access(analysis: Analysis) -> Finding | None:
    if analysis.event.event_type != "file_read":
        return None

    path = str(analysis.event.payload.get("path", ""))
    if not path or not is_secret_path(path):
        return None

    return Finding(
        rule="secret_file_access",
        severity="high",
        summary=f"Read a likely credential file: {path}",
        details={"path": path},
    )


def unapproved_domain(analysis: Analysis) -> Finding | None:
    if analysis.event.event_type != "http_request":
        return None

    url = str(analysis.event.payload.get("url", ""))
    host = (urlparse(url).hostname or "").lower()

    if not host:
        return None

    # A subdomain of an allowed domain counts as allowed, so the list stays short.
    if any(host == allowed or host.endswith(f".{allowed}") for allowed in analysis.allowed_domains):
        return None

    return Finding(
        rule="unapproved_domain",
        severity="medium",
        summary=f"Request to {host}, which is not on the allowlist",
        details={"host": host, "url": url, "method": analysis.event.payload.get("method")},
    )


def remote_code_execution(analysis: Analysis) -> Finding | None:
    if analysis.event.event_type != "shell_command":
        return None

    command = str(analysis.event.payload.get("command", ""))
    if not command:
        return None

    for pattern, shape in EXECUTION_PATTERNS:
        if pattern.search(command):
            return Finding(
                rule="remote_code_execution",
                severity="critical",
                summary=f"Shell command is a {shape}",
                details={"command": command[:500], "shape": shape},
            )

    return None


def rapid_secret_reads(analysis: Analysis) -> Finding | None:
    """Reading one credential file can be legitimate. Sweeping several in minutes is collection."""
    if analysis.event.event_type != "file_read":
        return None

    path = str(analysis.event.payload.get("path", ""))
    if not path or not is_secret_path(path):
        return None

    if analysis.prior_sensitive_reads < 3:
        return None

    total = analysis.prior_sensitive_reads + 1

    return Finding(
        rule="rapid_secret_reads",
        severity="high",
        summary=f"{total} reads of credential files by this agent in a short window",
        details={"reads_in_window": total, "path": path},
    )


def privileged_tool_call(analysis: Analysis) -> Finding | None:
    if analysis.event.event_type != "tool_call":
        return None

    args = analysis.event.payload.get("args") or {}
    if not isinstance(args, dict):
        return None

    values = " ".join(str(value) for value in args.values())

    name = str(analysis.event.payload.get("name", "unknown"))

    if any(pattern.search(values) for pattern in PRIVILEGE_PATTERNS):
        return Finding(
            rule="privileged_tool_call",
            severity="high",
            summary=f"Tool call {name} asks for elevated privileges",
            details={"name": name, "args": args},
        )

    requested = str(args.get("path", ""))
    if requested in BROAD_PATHS or requested.rstrip("/") in BROAD_PATHS:
        return Finding(
            rule="privileged_tool_call",
            severity="high",
            summary=f"Tool call {name} asks for broad filesystem access",
            details={"name": name, "path": requested},
        )

    return None


ALL_RULES: tuple[Callable[[Analysis], Finding | None], ...] = (
    secret_file_access,
    rapid_secret_reads,
    remote_code_execution,
    unapproved_domain,
    privileged_tool_call,
)


def evaluate(analysis: Analysis) -> list[Finding]:
    return [finding for rule in ALL_RULES if (finding := rule(analysis)) is not None]
