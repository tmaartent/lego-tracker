"""The text of a notification, in Telegram's HTML subset."""
from decimal import Decimal
from html import escape

from lego_events import ListingMatched, ListingPriceDropped, ListingSnapshot


def render(event: ListingMatched | ListingPriceDropped) -> str:
    listing = event.listing
    set_label = escape(f"{event.set_num} {event.set_name}" if event.set_name else event.set_num)

    if isinstance(event, ListingPriceDropped):
        heading = f"📉 <b>Price drop: {set_label}</b>"
        price = f"{_eur(event.previous_total_price)} → <b>{_eur(listing.total_price)}</b> {_shipping_note(listing)}"
    else:
        heading = f"🧱 <b>New match: {set_label}</b>"
        price = _price_line(listing)

    lines = [heading, escape(listing.title), price.strip(), _where(listing)]
    if listing.looks_incomplete:
        lines.append("⚠️ The title suggests parts are missing")
    lines.append(f'<a href="{escape(listing.url, quote=True)}">Open on {escape(listing.source)}</a>')
    return "\n".join(line for line in lines if line)


def _price_line(listing: ListingSnapshot) -> str:
    if listing.shipping is None:
        return f"<b>{_eur(listing.price)}</b> + shipping unknown"
    if listing.shipping == 0:
        return f"<b>{_eur(listing.price)}</b>, free shipping or pickup"
    return f"{_eur(listing.price)} + {_eur(listing.shipping)} shipping = <b>{_eur(listing.total_price)}</b>"


def _shipping_note(listing: ListingSnapshot) -> str:
    return "(shipping unknown)" if listing.shipping is None else "incl. shipping"


def _where(listing: ListingSnapshot) -> str:
    place = " ".join(part for part in (listing.postcode, listing.country) if part)
    if listing.distance_km is not None:
        return f"📍 {escape(place)}, ~{listing.distance_km:.0f} km away"
    return f"📍 {escape(place)}, distance unknown" if place else "📍 Location unknown"


def _eur(amount: Decimal) -> str:
    return f"€{amount:.2f}"
