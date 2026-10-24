from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from catalog.importer import import_colors, import_set
from catalog.rebrickable import RebrickableClient, RebrickableError


class Command(BaseCommand):
    help = "Import one or more sets and their parts lists from Rebrickable, e.g. `import_set 6086-1`."

    def add_arguments(self, parser):
        parser.add_argument("set_nums", nargs="*", help="Rebrickable set numbers, like 6086-1")
        parser.add_argument("--colors", action="store_true", help="Also (re)import all colors with their BrickLink ids")

    def handle(self, *args, set_nums, colors, **options):
        if not set_nums and not colors:
            raise CommandError("Give at least one set number, or --colors.")
        try:
            client = RebrickableClient(settings.REBRICKABLE_API_KEY)
            if colors:
                count = import_colors(client)
                self.stdout.write(f"Imported {count} colors")
            for set_num in set_nums:
                lego_set = import_set(client, set_num)
                self.stdout.write(self.style.SUCCESS(
                    f"Imported {lego_set} ({lego_set.inventory.count()} inventory lines)"
                ))
        except RebrickableError as exc:
            raise CommandError(str(exc)) from exc
