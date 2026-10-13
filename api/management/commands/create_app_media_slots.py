from django.core.management.base import BaseCommand
from api.models import AppMedia

class Command(BaseCommand):
    help = 'Pre-create 3 AppMedia slots in DB'

    def handle(self, *args, **kwargs):
        for order in [1, 2, 3]:
            slot, created = AppMedia.objects.get_or_create(order=order)
            if created:
                self.stdout.write(f"✅ Slot {order} created")
            else:
                self.stdout.write(f"⚠️ Slot {order} already exists")