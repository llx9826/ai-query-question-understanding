"""Process entry point for the management and conversation service."""

import uvicorn

from app.bootstrap import create_app
from app.settings import Settings


def main() -> None:
    settings = Settings()
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.http_host,
        port=settings.http_port,
        workers=settings.http_workers,
    )


if __name__ == "__main__":
    main()
