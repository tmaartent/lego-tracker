from django.contrib import admin, messages
from django.http import HttpResponse

from .models import MissingPart, OwnedSet
from .wanted_list import build_wanted_list, to_bricklink_xml


class MissingPartInline(admin.TabularInline):
    model = MissingPart
    extra = 1
    raw_id_fields = ["inventory_part"]


@admin.register(OwnedSet)
class OwnedSetAdmin(admin.ModelAdmin):
    list_display = ["lego_set", "acquired_on", "price_paid", "source", "condition"]
    list_filter = ["condition", "source"]
    search_fields = ["lego_set__set_num", "lego_set__name"]
    autocomplete_fields = ["lego_set"]
    inlines = [MissingPartInline]
    actions = ["download_wanted_list"]

    @admin.action(description="Download BrickLink wanted list for missing parts")
    def download_wanted_list(self, request, queryset):
        wanted = build_wanted_list(list(queryset))
        if wanted.unmapped:
            self.message_user(
                request,
                f"Skipped parts without a BrickLink id: {', '.join(wanted.unmapped)}",
                messages.WARNING,
            )
        response = HttpResponse(to_bricklink_xml(wanted), content_type="application/xml")
        response["Content-Disposition"] = 'attachment; filename="bricklink-wanted-list.xml"'
        return response
