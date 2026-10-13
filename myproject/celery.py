import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE','myproject.settings')

app=Celery('myproject')
app.config_from_object('django.conf:settings',namespace='CELERY')
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'daily-db-backup-10am': {
        'task': 'api.tasks.backup_database',
        'schedule': crontab(hour=4, minute=30),
        # 10:00 AM IST = 04:30 UTC
    },
}
