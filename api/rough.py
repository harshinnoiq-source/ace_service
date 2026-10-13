import os
from rest_framework import status, viewsets
from rest_framework.response import Response

from .models import AppMedia
from .serializers import AppMediaSerializer


class AppMediaViewSet(viewsets.ViewSet):

    def list(self, request):
        slots = AppMedia.objects.all().order_by('order')
        serializer = AppMediaSerializer(slots, many=True, context={'request': request})
        return Response({
            "status": "success",
            "data": serializer.data
        })
def list(self, request):
    slots = AppMedia.objects.all().order_by('order')
    serializer = AppMediaSerializer(slots, many=True, context={'request': request})
    return Response({
        "status": "success",
        "data": serializer.data
    })
    def create(self, request):
        file = request.FILES.get('file')
        file_type = request.data.get('type')
        order = request.data.get('order')

        # 1. Validate order
        try:
            order = int(order)
        except (TypeError, ValueError):
            return Response({
                "status": "error",
                "message": "order must be a valid integer"
            }, status=status.HTTP_400_BAD_REQUEST)

        # 2. Validate required fields
        if not file or not file_type:
            return Response({
                "status": "error",
                "message": "file and type are required"
            }, status=status.HTTP_400_BAD_REQUEST)

        # 3. Get or create slot (IMPORTANT FIX)
        slot, created = AppMedia.objects.get_or_create(order=order)

        # 4. Delete old file safely
        if slot.file:
            try:
                if os.path.isfile(slot.file.path):
                    os.remove(slot.file.path)
            except Exception:
                pass  # avoid crash if file missing

        # 5. Update slot
        slot.file = file
        slot.type = file_type
        slot.save()

        serializer = AppMediaSerializer(slot, context={'request': request})

        return Response({
            "status": "success",
            "message": "Slot created" if created else f"Slot {order} updated",
            "data": serializer.data
        }, status=status.HTTP_200_OK)
    def create(self, request):
        file = request.FILES.get('file')
        file_type = request.data.get('type')

        try:
            order = int(request.data.get('order'))
        except (TypeError, ValueError):
            return Response({
                "status": "error",
                "message": "order must be a valid number"
            }, status=status.HTTP_400_BAD_REQUEST)

        if not order or not file or not file_type:
            return Response({
                "status": "error",
                "message": "order, file and type are required"
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            slot = AppMedia.objects.get(order=order)
            if slot.file:
                if os.path.isfile(slot.file.path):
                    os.remove(slot.file.path)
            slot.file = file
            slot.type = file_type
            slot.save()
        except AppMedia.DoesNotExist:
            return Response({
                "status": "error",
                "message": "Invalid slot order"
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = AppMediaSerializer(slot, context={'request': request})
        return Response({
            "status": "success",
            "message": f"Slot {order} updated successfully",
            "data": serializer.data
        })
