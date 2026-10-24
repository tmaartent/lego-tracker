from django.contrib import admin

from .models import OutboxEvent


@admin.register(OutboxEvent)
class OutboxEventAdmin(admin.ModelAdmin):
    list_display = ["routing_key", "id", "created_at", "published_at"]
    list_filter = ["routing_key", ("published_at", admin.EmptyFieldListFilter)]
    readonly_fields = ["id", "routing_key", "payload", "created_at", "published_at"]

    def has_add_permission(self, request):
        return False
