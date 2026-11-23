from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.core.config import Settings, get_settings
from app.core.db import dispose_engine
from app.core.errors import register_exception_handlers
from app.core.logging import RequestContextMiddleware, configure_logging
from app.core.middleware import install_http_middleware
from app.modules.ac_entry.router import dispatch_slips_router
from app.modules.ac_entry.router import router as ac_entry_router
from app.modules.attachments.router import router as attachments_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.closure.router import router as closure_router
from app.modules.config.field_profiles.router import router as field_profiles_router
from app.modules.config.forms.router import router as forms_router
from app.modules.config.history.router import router as history_router
from app.modules.config.numbering.router import router as numbering_router
from app.modules.config.options.router import router as options_router
from app.modules.config.settings.router import router as settings_router
from app.modules.config.templates.router import router as templates_router
from app.modules.config.workflow.router import router as workflow_router
from app.modules.container_audit.router import router as container_audit_router
from app.modules.credit_notes.router import router as credit_notes_router
from app.modules.custody.router import router as custody_router
from app.modules.dashboards.router import router as dashboards_router
from app.modules.department_routing.router import router as department_routing_router
from app.modules.dismantling.router import router as dismantling_router
from app.modules.dismantling.router import scrap_router
from app.modules.dispatch.router import router as dispatch_router
from app.modules.final_actions.router import router as final_actions_router
from app.modules.final_actions.router import store_analysis_router
from app.modules.goods_slips.router import router as goods_slips_router
from app.modules.health.router import router as health_router
from app.modules.inspection.router import router as inspection_router
from app.modules.intermediate_stores.router import admin_router as intermediate_stores_admin_router
from app.modules.intermediate_stores.router import router as intermediate_stores_router
from app.modules.inventory.battery_router import router as battery_router
from app.modules.inventory.router import router as inventory_router
from app.modules.itemization.router import router as itemization_router
from app.modules.journeys.router import router as journeys_router
from app.modules.masters.router import router as masters_router
from app.modules.notifications.router import admin_router as notifications_admin_router
from app.modules.notifications.router import router as notifications_router
from app.modules.party_notifications.router import router as party_notifications_router
from app.modules.pendency.router import router as pendency_router
from app.modules.reports.router import router as reports_router
from app.modules.rm_actions.router import router as rm_actions_router
from app.modules.rm_review.router import router as rm_review_router
from app.modules.roles.router import router as roles_router
from app.modules.search.router import router as search_router
from app.modules.servicing.router import router as servicing_router
from app.modules.store_issue.router import router as store_issue_router
from app.modules.tasks.router import router as tasks_router
from app.modules.transfer_slips.router import gs_router as transfer_slips_gs_router
from app.modules.transfer_slips.router import router as transfer_slips_router
from app.modules.unboxing.router import router as unboxing_router
from app.modules.users.router import me_router as users_me_router
from app.modules.users.router import router as users_router
from app.modules.views.router import router as views_router

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    # Fails fast here (at import / startup) if a required setting is missing.
    settings = settings or get_settings()
    configure_logging(settings)

    # Production audit 2026-11-14: the interactive docs and the OpenAPI schema disclose the whole
    # API surface, so they are served only outside prod (`pnpm gen:api` runs against local).
    expose_docs = settings.app_env != "prod"
    app = FastAPI(
        title="RMS API",
        version=__version__,
        description="Replacement Management System API",
        lifespan=lifespan,
        docs_url="/docs" if expose_docs else None,
        redoc_url="/redoc" if expose_docs else None,
        openapi_url="/openapi.json" if expose_docs else None,
    )
    register_exception_handlers(app, app_env=settings.app_env)
    install_http_middleware(app, settings)
    # Added last = outermost: every response (including CORS preflights and 500s) gets a request id.
    app.add_middleware(RequestContextMiddleware, app_env=settings.app_env)

    # Probes at the root too (/health, /health/ready) for the hosting platform's health check.
    app.include_router(health_router, include_in_schema=False)
    app.include_router(health_router, prefix=API_PREFIX)
    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(options_router, prefix=API_PREFIX)
    app.include_router(forms_router, prefix=API_PREFIX)
    app.include_router(workflow_router, prefix=API_PREFIX)
    app.include_router(numbering_router, prefix=API_PREFIX)
    app.include_router(settings_router, prefix=API_PREFIX)
    app.include_router(templates_router, prefix=API_PREFIX)
    app.include_router(history_router, prefix=API_PREFIX)
    app.include_router(field_profiles_router, prefix=API_PREFIX)
    app.include_router(goods_slips_router, prefix=API_PREFIX)
    app.include_router(tasks_router, prefix=API_PREFIX)
    app.include_router(unboxing_router, prefix=API_PREFIX)
    app.include_router(itemization_router, prefix=API_PREFIX)
    app.include_router(inspection_router, prefix=API_PREFIX)
    app.include_router(rm_review_router, prefix=API_PREFIX)
    app.include_router(department_routing_router, prefix=API_PREFIX)
    app.include_router(final_actions_router, prefix=API_PREFIX)
    app.include_router(store_analysis_router, prefix=API_PREFIX)
    app.include_router(ac_entry_router, prefix=API_PREFIX)
    app.include_router(dispatch_slips_router, prefix=API_PREFIX)
    app.include_router(rm_actions_router, prefix=API_PREFIX)
    app.include_router(pendency_router, prefix=API_PREFIX)
    app.include_router(container_audit_router, prefix=API_PREFIX)
    app.include_router(custody_router, prefix=API_PREFIX)
    app.include_router(attachments_router, prefix=API_PREFIX)
    app.include_router(notifications_router, prefix=API_PREFIX)
    app.include_router(notifications_admin_router, prefix=API_PREFIX)
    app.include_router(battery_router, prefix=API_PREFIX)
    app.include_router(inventory_router, prefix=API_PREFIX)
    app.include_router(servicing_router, prefix=API_PREFIX)
    app.include_router(dismantling_router, prefix=API_PREFIX)
    app.include_router(scrap_router, prefix=API_PREFIX)
    app.include_router(store_issue_router, prefix=API_PREFIX)
    app.include_router(dispatch_router, prefix=API_PREFIX)
    app.include_router(credit_notes_router, prefix=API_PREFIX)
    app.include_router(party_notifications_router, prefix=API_PREFIX)
    app.include_router(closure_router, prefix=API_PREFIX)
    app.include_router(dashboards_router, prefix=API_PREFIX)
    app.include_router(reports_router, prefix=API_PREFIX)
    app.include_router(audit_router, prefix=API_PREFIX)
    app.include_router(search_router, prefix=API_PREFIX)
    app.include_router(views_router, prefix=API_PREFIX)
    app.include_router(masters_router, prefix=API_PREFIX)
    app.include_router(journeys_router, prefix=API_PREFIX)  # change plan Phase 10 (AMD-22)
    app.include_router(users_router, prefix=API_PREFIX)  # P1-05 user administration
    app.include_router(users_me_router, prefix=API_PREFIX)
    app.include_router(roles_router, prefix=API_PREFIX)
    # Phase P1 20-11-2026 (DEC-61): Intermediate Stores.
    app.include_router(intermediate_stores_admin_router, prefix=API_PREFIX)
    app.include_router(intermediate_stores_router, prefix=API_PREFIX)
    # Phase P5 20-11-2026 (DEC-65): transfer slips + edit requests.
    app.include_router(transfer_slips_router, prefix=API_PREFIX)
    app.include_router(transfer_slips_gs_router, prefix=API_PREFIX)

    if settings.app_env in ("test", "local"):
        from app.modules.test_support.router import router as test_router

        app.include_router(test_router, prefix=API_PREFIX)

    return app


app = create_app()
