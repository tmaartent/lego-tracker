from django.contrib import admin

from .models import Color, InventoryPart, LegoSet, Part


class InventoryPartInline(admin.TabularInline):
    model = InventoryPart
    extra = 0
    autocomplete_fields = ["part", "color"]


@admin.register(LegoSet)
class LegoSetAdmin(admin.ModelAdmin):
    list_display = ["set_num", "name", "year", "num_parts"]
    search_fields = ["set_num", "name"]
    inlines = [InventoryPartInline]


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display = ["part_num", "name", "bricklink_id"]
    search_fields = ["part_num", "name", "bricklink_id"]


@admin.register(Color)
class ColorAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "rgb", "bricklink_id"]
    search_fields = ["name"]
