"""Apply PostgreSQL migrations before the FastAPI process accepts requests."""

from __future__ import annotations

import uvicorn

from mandate.config import ApiSettings
from mandate.persistence.migrations import apply_migrations


def run(settings: ApiSettings | None = None) -> None:
    """Prepare persistent state, then start the private FastAPI process."""
    active_settings = settings or ApiSettings()
    if active_settings.database_url is None:
        raise RuntimeError("The API requires DATABASE_URL before startup.")
    apply_migrations(active_settings.database_url)
    start_server(active_settings)


def start_server(settings: ApiSettings) -> None:
    """Start the HTTP listener after persistent state is ready."""
    uvicorn.run(
        "mandate.api.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - the container port must accept web traffic
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
    )


if __name__ == "__main__":
    run()
