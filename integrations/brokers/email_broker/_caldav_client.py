"""CalDAV client for the email broker.

Thin async wrapper around the synchronous :mod:`caldav` library. Mirrors
the IMAP client's contract:

- Every blocking ``caldav`` call runs through ``asyncio.to_thread`` so
  the event loop stays responsive while a HTTP-PROPFIND or REPORT is in
  flight.
- An ``asyncio.Lock`` serializes access to the underlying ``DAVClient``.
  caldav's library is documented as not fully thread-safe, and serial
  access matches what we already do for IMAP.

The credential is held in memory for the broker's lifetime — same pattern
as the IMAP client. The broker's ``__main__`` wipes it from
``os.environ`` after handing it here.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import caldav
import recurring_ical_events
import requests.exceptions
import urllib3.exceptions
from caldav.lib import error as caldav_error
from icalendar import Calendar as ICalendar
from icalendar import Event as ICalendarEvent
from icalendar import Timezone, vCalAddress

from integrations.brokers.email_broker.types import Calendar, Event
from integrations.calendar_recurrence import normalize_recurrence_rule, normalize_time_zone

logger = logging.getLogger(__name__)

# Errors that indicate the underlying HTTP connection has gone away —
# server-side idle close, RST, half-closed TLS. caldav uses requests under
# the hood, so the visible shapes are requests/urllib3 errors. Auth failures
# stay in their own ``AuthorizationError`` branch — retrying those would
# loop on a real credential rejection.
_STALE_CONN_ERRORS: tuple[type[BaseException], ...] = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    urllib3.exceptions.ProtocolError,
)


class CalDavAuthError(Exception):
    """Server rejected the credential. The broker's entry code maps this to exit(77)."""


class CalDavClient:
    """Single CalDAV session shared by all concurrent verb calls in this broker."""

    def __init__(self, *, url: str, username: str, password: str) -> None:
        self._url = url
        self._username = username
        # Held on the instance so the broker can refresh credentials on
        # transient errors without keeping the secret in env.
        self._password = password

        self._lock = asyncio.Lock()
        self._client: caldav.DAVClient | None = None
        self._principal: Any | None = None
        # iCloud rejects the UID-only calendar-query REPORT used by
        # ``get_event_by_uid`` with HTTP 412. Remember hrefs returned by
        # create/list calls so mutations can reload the resource with GET,
        # which also refreshes its ETag before PUT.
        self._event_urls: dict[str, str] = {}

    async def connect(self) -> None:
        """Open the CalDAV session and resolve the user's principal.

        Auth failures (HTTP 401) raise :class:`CalDavAuthError` so the
        broker's entry code can exit 77 — same shape as IMAP's auth flow.
        """
        try:
            self._client, self._principal = await asyncio.to_thread(self._blocking_connect)
        except caldav_error.AuthorizationError as exc:
            msg = f"CalDAV auth rejected: {exc}"
            raise CalDavAuthError(msg) from exc
        except Exception as exc:
            # The library wraps most errors in caldav.lib.error.* — any one
            # whose status is 401 we treat as auth rejection so the broker
            # exits 77 and the supervisor flips state to ``auth_failed``.
            if _is_auth_failure(exc):
                msg = f"CalDAV auth rejected: {exc}"
                raise CalDavAuthError(msg) from exc
            raise
        logger.info("CalDAV principal resolved (%s @ %s)", self._username, self._url)

    def _blocking_connect(self) -> tuple[caldav.DAVClient, Any]:
        """Synchronous connect — runs inside a worker thread.

        Used by ``connect()`` and as the reconnect path inside
        ``_with_reconnect``.
        """
        client = caldav.DAVClient(
            url=self._url,
            username=self._username,
            password=self._password,
        )
        # Resolving the principal exercises the auth path; if creds are
        # rejected this is where it surfaces.
        principal = client.principal()
        return client, principal

    def _with_reconnect(self, op):
        """Run ``op(client, principal)``; reconnect+retry once on stale-conn errors.

        Caller must hold ``self._lock`` and must have awaited ``connect()``
        first. iCloud closes idle DAV sessions after ~10-30 minutes; the
        next request fails with a requests/urllib3 connection error. We
        rebuild the DAVClient + principal and retry once. A second failure
        propagates.

        Auth errors are *not* caught here — they're bubbled up so the
        broker's entry code can map them to exit 77.
        """
        if self._client is None or self._principal is None:
            msg = "CalDavClient used before connect()"
            raise RuntimeError(msg)
        try:
            return op(self._client, self._principal)
        except _STALE_CONN_ERRORS as exc:
            logger.info("CalDAV connection stale (%s); reconnecting and retrying once", exc)
            client, principal = self._blocking_connect()
            self._client = client
            self._principal = principal
            return op(client, principal)

    async def list_calendars(self) -> list[Calendar]:
        """Return the user's calendars (collections under their principal)."""
        async with self._lock:

            def _op(_client: caldav.DAVClient, principal: Any) -> list[Any]:
                return list(principal.calendars())

            cals = await asyncio.to_thread(self._with_reconnect, _op)

        return [
            Calendar(
                name=_calendar_name(c),
                url=str(c.url),
            )
            for c in cals
        ]

    async def list_events(
        self,
        calendar_url: str,
        days_forward: int,
        days_back: int,
        limit: int,
    ) -> tuple[str, list[Event]]:
        """List events on ``calendar_url`` over a centered date range.

        Returns ``(calendar_name, events)``. The name is fetched alongside
        the search so the caller can present human-readable output without
        a second round-trip; recurring events are server-expanded into
        per-occurrence records.
        """
        limit = max(1, min(limit, 200))
        async with self._lock:

            def _op(client: caldav.DAVClient, _principal: Any) -> tuple[str, list[Any]]:
                cal = client.calendar(url=calendar_url)
                name = _calendar_name(cal)
                now = datetime.now(UTC)
                start = now - timedelta(days=days_back)
                end = now + timedelta(days=days_forward)
                # ``event=True`` filters out tasks/journals; ``expand=True``
                # asks the server to materialize each recurrence into its
                # own VEVENT so the parser doesn't need to walk RRULEs.
                hits = list(cal.search(
                    start=start, end=end, event=True, expand=True,
                ))
                return name, hits

            name, raw = await asyncio.to_thread(self._with_reconnect, _op)

        logger.info(
            "list_events(%s, +%d/-%d days): %d raw hits",
            calendar_url, days_forward, days_back, len(raw),
        )
        events: list[Event] = []
        skipped = 0
        for hit in raw:
            ev = _parse_event(hit)
            if ev is None:
                skipped += 1
                continue
            self._remember_event_url(ev.uid, hit)
            events.append(ev)
            if len(events) >= limit:
                break
        if skipped:
            logger.info("list_events: skipped %d unparseable hit(s)", skipped)
        return name, events

    async def create_event(
        self,
        calendar_url: str,
        summary: str,
        start: str,
        end: str,
        description: str = "",
        location: str = "",
        attendees: list[str] | None = None,
        recurrence_rule: str | None = None,
        time_zone: str | None = None,
    ) -> Event:
        """Create and return a VEVENT in ``calendar_url``."""
        recurrence = normalize_recurrence_rule(recurrence_rule)
        zone_name = normalize_time_zone(time_zone)
        if recurrence and "T" in start and zone_name is None:
            raise ValueError("time_zone is required for a recurring timed event")
        dtstart = _parse_event_time(start, "start", time_zone=zone_name)
        dtend = _parse_event_time(end, "end", time_zone=zone_name)
        if isinstance(dtstart, datetime) != isinstance(dtend, datetime):
            msg = "start and end must both be datetimes or both be dates"
            raise ValueError(msg)
        if dtend <= dtstart:
            raise ValueError("end must be after start")

        async with self._lock:

            def _op(client: caldav.DAVClient, principal: Any) -> Any:
                cal = client.calendar(url=calendar_url)
                properties: dict[str, Any] = {
                    "summary": summary,
                    "dtstart": dtstart,
                    "dtend": dtend,
                }
                if description:
                    properties["description"] = description
                if location:
                    properties["location"] = location
                if attendees:
                    organizer = _organizer_address(principal, self._username)
                    if organizer is not None:
                        properties["organizer"] = organizer
                    properties["attendee"] = _attendee_addresses(attendees)
                if recurrence:
                    properties["rrule"] = recurrence
                if zone_name or attendees or recurrence:
                    return cal.add_event(ical=_build_icalendar(properties, zone_name))
                return cal.add_event(**properties)

            raw = await asyncio.to_thread(self._with_reconnect, _op)

        event = _parse_event(raw)
        if event is None:
            msg = "CalDAV server returned an event without a usable UID"
            raise RuntimeError(msg)
        self._remember_event_url(event.uid, raw)
        logger.info("create_event(%s): created %s", calendar_url, event.uid)
        return event

    async def update_event(
        self,
        calendar_url: str,
        event_id: str,
        *,
        recurrence_id: str | None = None,
        href: str | None = None,
        summary: str | None = None,
        start: str | None = None,
        end: str | None = None,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        recurrence_rule: str | None = None,
        time_zone: str | None = None,
    ) -> Event:
        """Update an exact occurrence, or a non-recurring VEVENT."""
        recurrence = normalize_recurrence_rule(recurrence_rule)
        zone_name = normalize_time_zone(time_zone)
        if recurrence and start is not None and "T" in start and zone_name is None:
            raise ValueError("time_zone is required when changing a timed recurrence")
        parsed_start = (
            _parse_event_time(start, "start", time_zone=zone_name) if start is not None else None
        )
        parsed_end = (
            _parse_event_time(end, "end", time_zone=zone_name) if end is not None else None
        )

        async with self._lock:

            def _op(client: caldav.DAVClient, _principal: Any) -> Any:
                cal = client.calendar(url=calendar_url)
                resource = self._get_event_resource(cal, event_id, href)
                if recurrence_id is None:
                    component = _master_component(resource)
                else:
                    component = _occurrence_component(resource, recurrence_id)
                _update_component(
                    component,
                    summary=summary,
                    start=parsed_start,
                    end=parsed_end,
                    description=description,
                    location=location,
                    attendees=attendees,
                    organizer=(
                        self._username
                        if attendees is not None and "@" in self._username
                        else None
                    ),
                    recurrence_rule=recurrence,
                )
                if zone_name:
                    _ensure_timezone(resource, zone_name, parsed_start or parsed_end)
                if recurrence_id is not None:
                    _merge_occurrence(resource, component, recurrence_id)
                resource.save()
                return resource, component

            try:
                raw, component = await asyncio.to_thread(self._with_reconnect, _op)
            except caldav_error.NotFoundError as exc:
                raise LookupError(f"event not found: {event_id}") from exc

        event = _event_from_component(component, href=str(getattr(raw, "url", "")))
        if event is None:
            msg = "CalDAV server returned an event without a usable UID"
            raise RuntimeError(msg)
        self._remember_event_url(event.uid, raw)
        logger.info("update_event(%s): updated %s", calendar_url, event.uid)
        return event

    async def delete_event(
        self,
        calendar_url: str,
        event_id: str,
        *,
        recurrence_id: str | None = None,
        href: str | None = None,
    ) -> None:
        """Delete an exact occurrence, or a non-recurring VEVENT."""
        async with self._lock:

            def _op(client: caldav.DAVClient, _principal: Any) -> None:
                cal = client.calendar(url=calendar_url)
                resource = self._get_event_resource(cal, event_id, href)
                if recurrence_id is None:
                    resource.delete()
                    return
                _exclude_occurrence(resource, recurrence_id)
                resource.save()

            try:
                await asyncio.to_thread(self._with_reconnect, _op)
            except caldav_error.NotFoundError as exc:
                raise LookupError(f"event not found: {event_id}") from exc
        if recurrence_id is None:
            self._event_urls.pop(event_id, None)
        logger.info("delete_event(%s): deleted %s", calendar_url, event_id)

    async def update_event_series(
        self,
        calendar_url: str,
        event_id: str,
        *,
        href: str | None = None,
        **changes: Any,
    ) -> Event:
        """Update the master VEVENT for an entire recurring series."""
        return await self.update_event(calendar_url, event_id, href=href, **changes)

    async def delete_event_series(
        self,
        calendar_url: str,
        event_id: str,
        *,
        href: str | None = None,
    ) -> None:
        """Delete an entire recurring series."""
        await self.delete_event(calendar_url, event_id, href=href)

    def _get_event_resource(
        self, calendar: Any, event_id: str, href: str | None = None,
    ) -> Any:
        """Load an event by cached href, falling back to a UID REPORT."""
        event_url = href or self._event_urls.get(event_id)
        if event_url is not None:
            return calendar.event_by_url(event_url)
        return calendar.get_event_by_uid(event_id)

    def _remember_event_url(self, event_id: str, resource: Any) -> None:
        event_url = getattr(resource, "url", None)
        if event_url is not None:
            self._event_urls[event_id] = str(event_url)


# ── helpers ──────────────────────────────────────────────────────────────────


def _is_auth_failure(exc: Exception) -> bool:
    """True if ``exc`` is the caldav lib's flavor of HTTP 401."""
    # caldav wraps HTTP errors in error.DAVError subclasses with a
    # ``.reason`` attribute; the 401 case maps to AuthorizationError but
    # other paths can come through as bare HTTP errors. Sniff for the
    # 401 status text rather than coupling to one library version's
    # exception hierarchy.
    text = str(exc).lower()
    return "401" in text or "unauthorized" in text


def _parse_event_time(
    value: str, field: str, *, time_zone: str | None = None,
) -> date | datetime:
    """Parse an RFC 3339 datetime or an ISO date used by calendar tools."""
    try:
        if "T" not in value:
            return date.fromisoformat(value)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an RFC 3339 datetime or ISO date") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} datetime must include a UTC offset")
    if time_zone:
        return parsed.astimezone(ZoneInfo(time_zone))
    return parsed.astimezone(UTC)


def _parse_recurrence_id(value: str) -> date | datetime:
    """Parse a provider recurrence key, including valid floating datetimes."""
    try:
        if "T" not in value:
            return date.fromisoformat(value)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid CalDAV recurrence identity") from exc


def _ical_value(component: Any, field: str) -> Any:
    value = component.get(field)
    return getattr(value, "dt", value)


def _validate_event_range(start: Any, end: Any) -> None:
    if start is None or end is None:
        raise ValueError("event must contain both start and end")
    if isinstance(start, datetime) != isinstance(end, datetime):
        raise ValueError("start and end must both be datetimes or both be dates")
    if end <= start:
        raise ValueError("end must be after start")


def _replace_ical_property(component: Any, field: str, value: Any) -> None:
    component.pop(field, None)
    if isinstance(value, list):
        for item in value:
            component.add(field, item)
    else:
        component.add(field, value)


def _calendar_address(address: str) -> vCalAddress:
    value = address if address.lower().startswith("mailto:") else f"mailto:{address}"
    return vCalAddress(value)


def _organizer_address(principal: Any, username: str) -> vCalAddress | None:
    """Resolve the principal's scheduling address, with an email fallback."""
    with contextlib.suppress(Exception):
        address = principal.get_vcal_address()
        if isinstance(address, vCalAddress):
            return address
    if "@" in username:
        return _calendar_address(username)
    return None


def _attendee_addresses(attendees: list[str]) -> list[vCalAddress]:
    addresses: list[vCalAddress] = []
    for attendee in attendees:
        address = _calendar_address(attendee)
        address.params.update({
            "CUTYPE": "INDIVIDUAL",
            "PARTSTAT": "NEEDS-ACTION",
            "ROLE": "REQ-PARTICIPANT",
            "RSVP": "TRUE",
        })
        addresses.append(address)
    return addresses


def _build_icalendar(properties: dict[str, Any], time_zone: str | None) -> str:
    """Build a VEVENT with VTIMEZONE for portable recurring local times."""
    calendar = ICalendar()
    calendar.add("prodid", "-//omnideck//calendar integration//EN")
    calendar.add("version", "2.0")
    if time_zone:
        zone = ZoneInfo(time_zone)
        start = properties["dtstart"]
        start_date = start.date() if isinstance(start, datetime) else start
        calendar.add_component(Timezone.from_tzinfo(
            zone,
            tzid=time_zone,
            first_date=date(max(1, start_date.year - 1), 1, 1),
            last_date=date(min(9998, start_date.year + 100), 12, 31),
        ))
    component = ICalendarEvent()
    component.add("uid", str(uuid.uuid4()))
    component.add("dtstamp", datetime.now(UTC))
    for field, value in properties.items():
        if isinstance(value, list):
            for item in value:
                component.add(field, item)
        else:
            component.add(field, value)
    calendar.add_component(component)
    return calendar.to_ical().decode("utf-8")


def _ensure_timezone(
    resource: Any, time_zone: str, event_time: date | datetime | None,
) -> None:
    """Add an IANA VTIMEZONE when a series update introduces that TZID."""
    for component in resource.icalendar_instance.walk("VTIMEZONE"):
        if str(component.get("tzid", "")) == time_zone:
            return
    year = event_time.year if event_time is not None else datetime.now(UTC).year
    resource.icalendar_instance.add_component(Timezone.from_tzinfo(
        ZoneInfo(time_zone),
        tzid=time_zone,
        first_date=date(max(1, year - 1), 1, 1),
        last_date=date(min(9998, year + 100), 12, 31),
    ))


def _master_component(resource: Any) -> Any:
    """Return the recurrence master (or the sole non-recurring VEVENT)."""
    components = list(resource.icalendar_instance.walk("VEVENT"))
    component = next((item for item in components if item.get("recurrence-id") is None), None)
    if component is None:
        raise ValueError("CalDAV event does not contain a recurrence master")
    return component


def _occurrence_component(resource: Any, recurrence_id: str) -> Any:
    """Return a stored exception or locally expand the requested occurrence."""
    for component in resource.icalendar_instance.walk("VEVENT"):
        if _ical_dt(component, "recurrence-id") == recurrence_id:
            return component.copy()

    target = _parse_recurrence_id(recurrence_id)
    occurrences = recurring_ical_events.of(resource.icalendar_instance).at(target)
    for component in occurrences:
        if _ical_dt(component, "recurrence-id") == recurrence_id:
            return component.copy()
    raise LookupError(f"event occurrence not found: {recurrence_id}")


def _update_component(
    component: Any,
    *,
    summary: str | None,
    start: date | datetime | None,
    end: date | datetime | None,
    description: str | None,
    location: str | None,
    attendees: list[str] | None,
    organizer: str | None,
    recurrence_rule: str | None,
) -> None:
    updates: dict[str, Any] = {
        "summary": summary,
        "dtstart": start,
        "dtend": end,
        "description": description,
        "location": location,
        "rrule": recurrence_rule,
    }
    for field, value in updates.items():
        if value is not None:
            _replace_ical_property(component, field, value)
    if attendees is not None:
        _replace_ical_property(component, "attendee", _attendee_addresses(attendees))
        if attendees and organizer and component.get("organizer") is None:
            _replace_ical_property(component, "organizer", _calendar_address(organizer))

    if start is not None or end is not None:
        actual_start = _ical_value(component, "dtstart")
        actual_end = _ical_value(component, "dtend")
        if actual_start is not None and actual_end is not None:
            _validate_event_range(actual_start, actual_end)


def _merge_occurrence(resource: Any, occurrence: Any, recurrence_id: str) -> None:
    """Add or replace a RECURRENCE-ID exception in the master resource."""
    components = resource.icalendar_instance.subcomponents
    matches = [
        index
        for index, component in enumerate(components)
        if getattr(component, "name", "") == "VEVENT"
        and _ical_dt(component, "recurrence-id") == recurrence_id
    ]
    if len(matches) > 1:
        raise ValueError("CalDAV event contains duplicate recurrence exceptions")
    if matches:
        components[matches[0]] = occurrence
    else:
        resource.icalendar_instance.add_component(occurrence)


def _exclude_occurrence(resource: Any, recurrence_id: str) -> None:
    """Delete one occurrence by removing its override and adding EXDATE."""
    # Validate that the recurrence key actually materializes before mutating
    # the master; an opaque but stale reference should fail visibly.
    _occurrence_component(resource, recurrence_id)
    master = _master_component(resource)
    target = _parse_recurrence_id(recurrence_id)
    components = resource.icalendar_instance.subcomponents
    components[:] = [
        component
        for component in components
        if not (
            getattr(component, "name", "") == "VEVENT"
            and _ical_dt(component, "recurrence-id") == recurrence_id
        )
    ]
    if target not in _exdate_values(master):
        master.add("exdate", target)


def _exdate_values(component: Any) -> list[Any]:
    properties = component.get("exdate", [])
    if not isinstance(properties, list):
        properties = [properties]
    values: list[Any] = []
    for prop in properties:
        dts = getattr(prop, "dts", None)
        if dts is not None:
            values.extend(getattr(value, "dt", value) for value in dts)
        else:
            values.append(getattr(prop, "dt", prop))
    return values


def _calendar_name(cal: Any) -> str:
    """Extract the human-readable display name from a CalDAV calendar object.

    caldav exposes ``Calendar.name`` as a lazy property that fetches the
    displayname from the server; the fetch can raise from any layer of
    the HTTP/DAV/network stack. Treat any failure as "no name available"
    and fall back to the URL's last segment — always-safe identifier.
    """
    name: Any | None = None
    with contextlib.suppress(Exception):
        name = cal.name
    if name:
        return str(name)
    url = str(cal.url).rstrip("/")
    return url.rsplit("/", 1)[-1] or url


def _parse_event(hit: Any) -> Event | None:
    """Convert a caldav search hit into our :class:`Event` shape.

    Returns ``None`` if the hit doesn't carry a usable VEVENT (e.g. the
    server returned a freebusy block). Robust to missing fields — every
    field but ``uid`` is optional in our type, and the iCalendar payload
    routinely omits ``DESCRIPTION`` / ``LOCATION`` / ``DTEND``.

    caldav 3.x exposes the parsed iCalendar tree at
    ``hit.icalendar_instance`` — an :class:`icalendar.Calendar` whose
    ``walk("VEVENT")`` yields the event component(s).
    """
    ical = getattr(hit, "icalendar_instance", None)
    if ical is None:
        return None
    vevent = next(iter(ical.walk("VEVENT")), None)
    if vevent is None:
        return None

    return _event_from_component(vevent, href=str(getattr(hit, "url", "")))


def _event_from_component(vevent: Any, *, href: str = "") -> Event | None:
    """Convert one VEVENT component to the broker's internal event shape."""
    uid = _ical_str(vevent, "uid")
    if not uid:
        return None
    recurrence_id = _ical_dt(vevent, "recurrence-id")
    return Event(
        uid=uid,
        summary=_ical_str(vevent, "summary"),
        start=_ical_dt(vevent, "dtstart"),
        end=_ical_dt(vevent, "dtend"),
        location=_ical_str(vevent, "location"),
        description=_ical_str(vevent, "description"),
        recurrence_id=recurrence_id,
        recurring=bool(recurrence_id or vevent.get("rrule") or vevent.get("rdate")),
        href=href,
    )


def _ical_str(vevent: Any, field: str) -> str:
    """Read a VEVENT property as a plain unicode string."""
    value = vevent.get(field)
    if value is None:
        return ""
    return str(value)


def _ical_dt(vevent: Any, field: str) -> str:
    """Read a VEVENT date/datetime property as ISO 8601.

    All-day events use ``VALUE=DATE`` (a python ``date``); regular events
    use a tz-aware ``datetime``. Both have ``isoformat()``.
    """
    value = vevent.get(field)
    if value is None:
        return ""
    dt = getattr(value, "dt", None)
    if dt is None:
        return str(value)
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)
