"""Give outbox rows an auto-increment id for ordering; the event id moves to its own column.

The table is recreated: changing a primary key's type in place isn't portable.
Unpublished events are lost, which is acceptable while this only runs locally.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("outbox", "0001_initial"),
    ]

    operations = [
        migrations.DeleteModel(name="OutboxEvent"),
        migrations.CreateModel(
            name="OutboxEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_id", models.UUIDField(unique=True)),
                ("routing_key", models.CharField(max_length=100)),
                ("payload", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("published_at", models.DateTimeField(blank=True, db_index=True, null=True)),
            ],
            options={
                "ordering": ["id"],
            },
        ),
    ]
