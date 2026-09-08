import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    database_url: str
    allowed_domains: frozenset[str]
    batch_size: int
    sensitive_read_window_minutes: int
    log_level: str

    @staticmethod
    def from_env(env: dict[str, str] | None = None) -> "Config":
        source = env if env is not None else dict(os.environ)

        database_url = source.get("DATABASE_URL", "").strip()
        if not database_url:
            raise SystemExit("DATABASE_URL is not set, so the analyzer has nothing to read")

        domains = {
            domain.strip().lower()
            for domain in source.get("ALLOWED_DOMAINS", "").split(",")
            if domain.strip()
        }

        return Config(
            database_url=database_url,
            allowed_domains=frozenset(domains),
            batch_size=int(source.get("BATCH_SIZE", "200")),
            sensitive_read_window_minutes=int(source.get("SENSITIVE_READ_WINDOW_MINUTES", "10")),
            log_level=source.get("LOG_LEVEL", "info").upper(),
        )
