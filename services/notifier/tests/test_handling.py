from lego_events import WatchDeleted
from sqlalchemy import select

from notifier.channels import PermanentFailure
from notifier.handling import Outcome, handle
from notifier.models import Notification

from .conftest import FakeChannel, matched, price_dropped

DELAYS = [10, 60, 300]


async def test_sends_and_records_the_notification(sessions):
    channel = FakeChannel()
    event = matched()

    decision = await handle(event, 0, sessions, channel, DELAYS)

    assert decision.outcome is Outcome.SENT
    assert len(channel.sent) == 1
    async with sessions() as session:
        [row] = (await session.scalars(select(Notification))).all()
    assert (row.event_id, row.event_type, row.watch_id, row.attempts) == (event.event_id, "listing.matched", 1, 1)


async def test_price_drops_are_sent_too(sessions):
    decision = await handle(price_dropped(), 0, sessions, FakeChannel(), DELAYS)

    assert decision.outcome is Outcome.SENT


async def test_redelivered_event_is_not_sent_twice(sessions):
    channel = FakeChannel()
    event = matched()
    await handle(event, 0, sessions, channel, DELAYS)

    decision = await handle(event, 0, sessions, channel, DELAYS)

    assert decision.outcome is Outcome.DUPLICATE
    assert len(channel.sent) == 1


async def test_temporary_failures_back_off_then_give_up(sessions):
    channel = FakeChannel(fail_times=99)
    event = matched()

    decisions = [await handle(event, attempt, sessions, channel, DELAYS) for attempt in range(4)]

    assert [d.outcome for d in decisions] == [Outcome.RETRY] * 3 + [Outcome.DEAD]
    assert [d.retry_in_seconds for d in decisions[:3]] == DELAYS
    assert "gave up after 4 attempts" in decisions[3].reason


async def test_success_on_a_retry_records_the_attempts(sessions):
    channel = FakeChannel(fail_times=1)
    event = matched()
    await handle(event, 0, sessions, channel, DELAYS)

    decision = await handle(event, 1, sessions, channel, DELAYS)

    assert decision.outcome is Outcome.SENT
    async with sessions() as session:
        assert (await session.get(Notification, event.event_id)).attempts == 2


async def test_permanent_failure_goes_straight_to_dead_letters(sessions):
    channel = FakeChannel(fail_times=1, failure=PermanentFailure("chat not found"))

    decision = await handle(matched(), 0, sessions, channel, DELAYS)

    assert decision.outcome is Outcome.DEAD
    assert decision.reason == "chat not found"


async def test_other_events_are_ignored(sessions):
    channel = FakeChannel()

    decision = await handle(WatchDeleted(watch_id=1, revision=2), 0, sessions, channel, DELAYS)

    assert decision.outcome is Outcome.IGNORED
    assert channel.calls == 0
