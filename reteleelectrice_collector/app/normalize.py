from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


ACTIVE_READING_FIELDS = {
    "WI": "import_kwh",
    "WE": "export_kwh",
}
REACTIVE_READING_FIELDS = {
    "QI": "reactive_inductive_kvarh",
    "QE": "reactive_capacitive_kvarh",
}


class NormalizationError(ValueError):
    pass


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    raw = str(value).strip()
    if raw in {"", "-", "null", "None"}:
        return None
    try:
        return float(raw.replace(" ", "").replace(",", "."))
    except ValueError as exc:
        raise NormalizationError(f"Invalid numeric meter value: {raw!r}") from exc


def normalize_curve_payload(
    payload: dict[str, Any],
    *,
    timezone_name: str = "Europe/Bucharest",
    interval_timestamp: str = "start",
    include_reactive: bool = False,
) -> list[dict[str, Any]]:
    if payload.get("result") != "OK":
        raise NormalizationError("Portal payload result is not OK")
    if interval_timestamp not in {"start", "end"}:
        raise NormalizationError("interval_timestamp must be 'start' or 'end'")

    pod = str(payload.get("POD") or "").strip()
    records = payload.get("ListData")
    if not isinstance(records, list):
        raise NormalizationError("Portal payload does not contain ListData")

    field_map = dict(ACTIVE_READING_FIELDS)
    if include_reactive:
        field_map.update(REACTIVE_READING_FIELDS)

    local_tz = ZoneInfo(timezone_name)
    points: dict[int, dict[str, Any]] = {}

    for record in records:
        if not isinstance(record, dict):
            continue
        reading_type = str(record.get("ReadingType") or "").upper()
        field = field_map.get(reading_type)
        if not field:
            continue

        try:
            frequency = int(record.get("Frequency") or 0)
        except (TypeError, ValueError) as exc:
            raise NormalizationError("Invalid curve frequency") from exc
        if frequency <= 0 or 1440 % frequency != 0:
            raise NormalizationError(f"Unsupported curve frequency: {frequency}")

        try:
            record_date = date.fromisoformat(str(record.get("DateT")))
        except ValueError as exc:
            raise NormalizationError(f"Invalid curve date: {record.get('DateT')!r}") from exc

        values = record.get("Value") or []
        if not isinstance(values, list):
            raise NormalizationError("Curve Value is not a list")

        # Work from the UTC instant of local midnight. This keeps intervals monotonic
        # across DST transition days and naturally supports 92/100-slot days.
        local_midnight = datetime.combine(record_date, time.min, tzinfo=local_tz)
        utc_midnight = local_midnight.astimezone(timezone.utc)
        offset_slots = 1 if interval_timestamp == "end" else 0

        for index, raw_value in enumerate(values):
            number = parse_number(raw_value)
            if number is None:
                continue
            instant = utc_midnight + timedelta(minutes=frequency * (index + offset_slots))
            epoch = int(instant.timestamp())
            point = points.setdefault(
                epoch,
                {
                    "timestamp": epoch,
                    "pod": pod,
                    "slot": index + 1,
                    "frequency_min": frequency,
                },
            )
            point[field] = number
            if reading_type == "WI":
                point["import_avg_kw"] = number * 60.0 / frequency
            elif reading_type == "WE":
                point["export_avg_kw"] = number * 60.0 / frequency

    return [points[key] for key in sorted(points)]
