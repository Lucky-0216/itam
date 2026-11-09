from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery = Celery(
    "itam",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.maintenance",
        "app.tasks.ldap_sync",
        "app.tasks.dingtalk_sync",
        "app.tasks.dingtalk_approval",
        "app.tasks.asset_flow",
        "app.tasks.contract",
        "app.tasks.reminders",
    ],
)

celery.conf.update(
    timezone="Asia/Shanghai",
    enable_utc=False,
    task_track_started=True,
    task_time_limit=600,
    task_soft_time_limit=540,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "itam-heartbeat": {
            "task": "app.tasks.maintenance.heartbeat",
            "schedule": crontab(minute="*/10"),
        },
        "itam-ldap-sync": {
            "task": "app.tasks.ldap_sync.sync_due_ldap",
            "schedule": crontab(minute="*/5"),
        },
        "itam-dingtalk-sync": {
            "task": "app.tasks.dingtalk_sync.sync_due_dingtalk",
            "schedule": crontab(minute="*/5"),
        },
        "itam-dingtalk-approval-reconcile": {
            "task": "app.tasks.dingtalk_approval.reconcile_dingtalk_approvals",
            "schedule": crontab(minute="*/5"),
        },
        "itam-borrow-due-reminder": {
            "task": "app.tasks.asset_flow.scan_due_borrows",
            "schedule": crontab(hour=9, minute=0),
        },
        "itam-contract-due-reminder": {
            "task": "app.tasks.contract.scan_due_contracts",
            "schedule": crontab(hour=9, minute=5),
        },
        "itam-consolidated-reminder": {
            "task": "app.tasks.reminders.scan_due_reminders",
            "schedule": crontab(hour=9, minute=10),
        },
    },
)
