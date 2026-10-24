import json
from decimal import Decimal

import pytest
from django.db import transaction
from lego_events import WatchDeleted, WatchUpserted, parse

from catalog.models import LegoSet
from outbox.models import OutboxEvent, enqueue
from watches.models import Watch

pytestmark = pytest.mark.django_db


@pytest.fixture
def castle():
    return LegoSet.objects.create(set_num="6086-1", name="Black Knight's Castle", year=1992)


def outbox_events():
    return [parse(row.routing_key, json.dumps(row.payload)) for row in OutboxEvent.objects.all()]


def test_creating_a_watch_announces_its_full_state(castle):
    watch = Watch.objects.create(lego_set=castle, max_total_price=Decimal("150"), max_distance_km=50)

    [event] = outbox_events()
    assert isinstance(event, WatchUpserted)
    assert event.watch.watch_id == watch.pk
    assert event.watch.set_num == "6086-1"
    assert event.watch.max_total_price == Decimal("150")
    assert event.watch.revision == 1


def test_every_change_gets_a_higher_revision(castle):
    watch = Watch.objects.create(lego_set=castle)
    watch.max_total_price = Decimal("120")
    watch.save()

    revisions = [event.watch.revision for event in outbox_events()]
    assert revisions == [1, 2]


def test_revision_comes_from_the_database_not_a_stale_copy(castle):
    watch = Watch.objects.create(lego_set=castle)
    stale = Watch.objects.get(pk=watch.pk)
    watch.save()  # revision 2

    stale.active = False
    stale.save()

    assert stale.revision == 3


def test_deleting_a_watch_announces_it(castle):
    watch = Watch.objects.create(lego_set=castle)
    watch_id = watch.pk
    watch.delete()

    deleted = outbox_events()[-1]
    assert isinstance(deleted, WatchDeleted)
    assert deleted.watch_id == watch_id
    assert deleted.revision == 2


def test_no_event_when_the_change_rolls_back(castle):
    with pytest.raises(RuntimeError), transaction.atomic():
        Watch.objects.create(lego_set=castle)
        raise RuntimeError("something later in the same transaction failed")

    assert not Watch.objects.exists()
    assert not OutboxEvent.objects.exists()


def test_enqueue_refuses_to_run_outside_a_transaction():
    # pytest-django wraps each test in a transaction, so step out of it explicitly.
    connection = transaction.get_connection()
    in_block = connection.in_atomic_block
    connection.in_atomic_block = False
    try:
        with pytest.raises(RuntimeError, match="transaction.atomic"):
            enqueue(WatchDeleted(watch_id=1, revision=1))
    finally:
        connection.in_atomic_block = in_block


def test_api_lists_watches_for_the_watcher(client, castle):
    Watch.objects.create(lego_set=castle, max_distance_km=50, accept_incomplete=False)

    response = client.get("/api/watches/")

    assert response.status_code == 200
    [watch] = response.json()
    assert watch["set_num"] == "6086-1"
    assert watch["max_distance_km"] == 50
    assert watch["accept_incomplete"] is False
    assert watch["revision"] == 1
