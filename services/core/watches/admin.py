from django.contrib import admin

from .models import Watch


@admin.register(Watch)
class WatchAdmin(admin.ModelAdmin):
    list_display = ["lego_set", "max_total_price", "max_distance_km", "accept_incomplete", "active"]
    list_filter = ["active", "accept_incomplete"]
    list_editable = ["active"]
    search_fields = ["lego_set__set_num", "lego_set__name"]
    autocomplete_fields = ["lego_set"]
    readonly_fields = ["revision", "created_at", "updated_at"]

    def delete_queryset(self, request, queryset):
        # The bulk delete action would skip Watch.delete() and its event.
        for watch in queryset:
            watch.delete()
