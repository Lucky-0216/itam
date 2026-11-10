from fastapi import APIRouter

from app.api.v1 import (
    approval_flow,
    asset_catalog,
    asset_flow,
    asset_ledger,
    asset_ops,
    audit,
    auth,
    branding,
    contracts,
    dashboard,
    dingtalk,
    imports,
    inbound,
    ldap,
    maintenance,
    notifications,
    org,
    reports,
    reminders,
    roles,
    search,
    todos,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(branding.router)
api_router.include_router(org.router)
api_router.include_router(roles.router)
api_router.include_router(asset_catalog.router)
api_router.include_router(asset_ledger.router)
api_router.include_router(asset_flow.router)
api_router.include_router(approval_flow.router)
api_router.include_router(asset_ops.router)
api_router.include_router(inbound.router)
api_router.include_router(maintenance.router)
api_router.include_router(contracts.router)
api_router.include_router(reports.router)
api_router.include_router(reminders.router)
api_router.include_router(audit.router)
api_router.include_router(dashboard.router)
api_router.include_router(ldap.router)
api_router.include_router(dingtalk.router)
api_router.include_router(notifications.router)
api_router.include_router(todos.router)
api_router.include_router(imports.router)
api_router.include_router(search.router)
