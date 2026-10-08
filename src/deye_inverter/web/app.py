"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from deye_inverter.container import Services
from deye_inverter.web.api import (
    ChargeSettingsApi,
    LogApi,
    ManualChargeApi,
    MonitoringApi,
    PlanApi,
    ProfilesApi,
    SettingsApi,
    TimeOfUseApi,
)
from deye_inverter.web.auth_gate import AuthGate
from deye_inverter.web.pages import PageController
from deye_inverter.web.static_files import RevalidatedStaticFiles

WEB_ROOT = Path(__file__).parent
SESSION_MAX_AGE = 30 * 24 * 3600


def create_app(services: Services) -> FastAPI:
    app = FastAPI(
        title="Deye Inverter", docs_url=None, redoc_url=None, lifespan=_lifespan(services)
    )
    templates = Jinja2Templates(directory=str(WEB_ROOT / "templates"))
    app.mount("/static", RevalidatedStaticFiles(directory=str(WEB_ROOT / "static")), name="static")
    for controller in (
        PageController(services, templates),
        MonitoringApi(services),
        PlanApi(services),
        TimeOfUseApi(services),
        ProfilesApi(services),
        ChargeSettingsApi(services),
        ManualChargeApi(services),
        SettingsApi(services),
        LogApi(services),
    ):
        app.include_router(controller.router)
    app.add_middleware(AuthGate, passwords=services.passwords)
    app.add_middleware(
        SessionMiddleware,
        secret_key=services.passwords.session_secret(),
        max_age=SESSION_MAX_AGE,
        same_site="strict",
    )
    return app


def _lifespan(services: Services) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if services.scheduler is not None:
            services.scheduler.start()
        yield
        if services.scheduler is not None:
            services.scheduler.shutdown()

    return lifespan
