from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import calculator, chat, events, outlets, products
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware


def create_app() -> FastAPI:
    """
    Application factory for the RAG Chatbot backend.
    Routes are attached in their respective modules and imported here.
    """

    configure_logging()
    settings = get_settings()

    app = FastAPI(
        title=settings.api_title,
        description="Backend services powering the RAG Chatbot.",
        version=settings.api_version,
    )

    cors_origins = settings.resolved_cors_origins
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_exception_handlers(app)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(calculator.router)
    app.include_router(products.router)
    app.include_router(outlets.router)
    app.include_router(chat.router)
    if settings.enable_sse:
        app.include_router(events.router)

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()


