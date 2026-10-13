import os
import shutil
from celery import shared_task
from django.core.management import call_command
from django.core.mail import EmailMessage
from django.conf import settings
from datetime import datetime


@shared_task
def backup_database():
    try:
        # ── 1. Create date-wise folder ──
        today = datetime.now().strftime('%Y-%m-%d')
        # backup_dir = os.path.join(settings.BASE_DIR, 'backups', today)
        backup_dir = os.path.join(r"C:\Users\deepali.w\backups", today)  #save in the c drive
        os.makedirs(backup_dir, exist_ok=True)

        # ── 2. Run dbbackup ──
        call_command('dbbackup', interactive=False, compress=False)

        # ── 3. Move backup file into date folder ──
        # base_backup_dir = os.path.join(settings.BASE_DIR, 'backups')
        base_backup_dir = r"C:\Users\deepali.w\backups"
        files = sorted(
            [f for f in os.listdir(base_backup_dir) if os.path.isfile(
                os.path.join(base_backup_dir, f))],
            key=lambda f: os.path.getmtime(os.path.join(base_backup_dir, f)),
            reverse=True
        )

        backup_filename = None
        if files:
            latest_file = files[0]
            src = os.path.join(base_backup_dir, latest_file)
            dst = os.path.join(backup_dir, latest_file)
            shutil.move(src, dst)
            backup_filename = latest_file
            backup_filepath = dst

        # ── 4. Send success email ──
        if backup_filename:
            file_size = os.path.getsize(backup_filepath)
            file_size_kb = round(file_size / 1024, 2)

            subject = f'✅ CGM DB Backup Success — {today}'
            body = f"""
Hello Team,

The daily database backup has been completed successfully.

Details:
━━━━━━━━━━━━━━━━━━━━━━━━━━━
📁 Filename     : {backup_filename}
📅 Date         : {today}
⏰ Time         : {datetime.now().strftime('%I:%M %p')} IST
📦 File Size    : {file_size_kb} KB
📂 Saved At     : backups/{today}/
━━━━━━━━━━━━━━━━━━━━━━━━━━━

Regards,
CGM Backup System
            """

            email = EmailMessage(
                subject=subject,
                body=body,
                from_email=settings.EMAIL_HOST_USER,
                to=settings.BACKUP_EMAIL_RECIPIENTS,
            )
            email.send()

        return f"Backup successful: {backup_filename}"

    except Exception as e:
        # ── 5. Send failure email ──
        subject = f'❌ CGM DB Backup FAILED — {datetime.now().strftime("%Y-%m-%d")}'
        body = f"""
Hello Team,

The daily database backup has FAILED.

Error Details:
━━━━━━━━━━━━━━━━━━━━━━━━━━━
❌ Error   : {str(e)}
📅 Date    : {datetime.now().strftime('%Y-%m-%d')}
⏰ Time    : {datetime.now().strftime('%I:%M %p')} IST
━━━━━━━━━━━━━━━━━━━━━━━━━━━

Please check the server immediately.

Regards,
CGM Backup System
        """

        email = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.EMAIL_HOST_USER,
            to=settings.BACKUP_EMAIL_RECIPIENTS,
        )
        email.send()

        return f"Backup failed: {str(e)}"