from decimal import Decimal

from notifier.messages import render

from .conftest import matched, price_dropped


def test_new_match():
    text = render(matched())

    assert text.splitlines() == [
        "🧱 <b>New match: 6086-1 Black Knight&#x27;s Castle</b>",
        "LEGO 6086 kasteel compleet",
        "€110.00 + €10.00 shipping = <b>€120.00</b>",
        "📍 3500 BE, ~14 km away",
        '<a href="https://example.test/a1">Open on 2dehands</a>',
    ]


def test_price_drop():
    text = render(price_dropped())

    assert text.startswith("📉 <b>Price drop: 6086-1")
    assert "€120.00 → <b>€100.00</b> incl. shipping" in text


def test_seller_text_is_escaped():
    text = render(matched(title='<b>LEGO</b> 6086 & "more"'))

    assert "&lt;b&gt;LEGO&lt;/b&gt; 6086 &amp; &quot;more&quot;" in text


def test_unknowns_are_said_out_loud():
    text = render(matched(shipping=None, distance_km=None, postcode="52062", country="DE"))

    assert "<b>€110.00</b> + shipping unknown" in text
    assert "📍 52062 DE, distance unknown" in text


def test_free_shipping_and_incomplete_warning():
    text = render(matched(shipping=Decimal("0"), looks_incomplete=True))

    assert "free shipping or pickup" in text
    assert "⚠️ The title suggests parts are missing" in text


def test_older_event_without_set_name():
    event = matched().model_copy(update={"set_name": None})

    assert render(event).startswith("🧱 <b>New match: 6086-1</b>")
