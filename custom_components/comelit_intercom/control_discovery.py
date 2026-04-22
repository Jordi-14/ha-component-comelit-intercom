"""Helpers for discovering door and relay controls from VIP configuration."""

from __future__ import annotations

import re
from typing import Any


def extract_controls_from_vip(vip_config: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract door and compatible actuator controls from VIP configuration."""
    user_parameters = vip_config.get("user-parameters", {})
    if not isinstance(user_parameters, dict):
        return []

    controls: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    controls.extend(
        _normalize_entries(
            user_parameters.get("opendoor-address-book", []),
            seen=seen,
            fallback_prefix="Door",
            source_key="opendoor-address-book",
        )
    )

    actuator_lists = [
        (key, value)
        for key, value in user_parameters.items()
        if key != "opendoor-address-book"
        and "actuator" in key
        and isinstance(value, list)
    ]
    if not actuator_lists:
        return controls

    controls.extend(_normalize_merged_actuator_entries(actuator_lists, seen))

    # Some firmware versions may already expose complete actuator rows in a single
    # list, while others split the name and output index across multiple lists.
    # Normalizing the original rows after the merge lets us support both layouts.
    for key, entries in actuator_lists:
        controls.extend(
            _normalize_entries(
                entries,
                seen=seen,
                fallback_prefix="Actuator",
                source_key=key,
            )
        )

    return controls


def _normalize_merged_actuator_entries(
    actuator_lists: list[tuple[str, list[Any]]],
    seen: set[tuple[str, int]],
) -> list[dict[str, Any]]:
    """Merge actuator rows by index and normalize the resulting controls."""
    controls: list[dict[str, Any]] = []
    max_len = max((len(entries) for _key, entries in actuator_lists), default=0)

    for index in range(max_len):
        merged: dict[str, Any] = {}
        source_keys: list[str] = []

        for key, entries in actuator_lists:
            if index >= len(entries) or not isinstance(entries[index], dict):
                continue

            _merge_non_empty(merged, entries[index])
            source_keys.append(key)

        if not merged:
            continue

        control = _normalize_entry(
            merged,
            fallback_name=f"Actuator {index + 1}",
            source_key=",".join(source_keys),
        )
        if control is None:
            continue

        identity = (control["apt-address"], control["output-index"])
        if identity in seen:
            continue

        seen.add(identity)
        controls.append(control)

    return controls


def _normalize_entries(
    entries: Any,
    *,
    seen: set[tuple[str, int]],
    fallback_prefix: str,
    source_key: str,
) -> list[dict[str, Any]]:
    """Normalize a list of control entries."""
    if not isinstance(entries, list):
        return []

    controls: list[dict[str, Any]] = []

    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue

        control = _normalize_entry(
            entry,
            fallback_name=f"{fallback_prefix} {index}",
            source_key=source_key,
        )
        if control is None:
            continue

        identity = (control["apt-address"], control["output-index"])
        if identity in seen:
            continue

        seen.add(identity)
        controls.append(control)

    return controls


def _normalize_entry(
    entry: dict[str, Any],
    *,
    fallback_name: str,
    source_key: str,
) -> dict[str, Any] | None:
    """Normalize a single control entry into the format used by the client."""
    apt_address = _first_string(
        entry,
        "apt-address",
        "address",
        "logical-address",
        "device-address",
    )
    if apt_address is None:
        return None

    output_index = _extract_output_index(entry)
    if output_index is None and "actuator" in source_key:
        output_index = _extract_index_from_address(apt_address)
    if output_index is None:
        return None

    return {
        "name": _first_string(entry, "name", "description", "label") or fallback_name,
        "apt-address": apt_address,
        "output-index": output_index,
    }


def _first_string(entry: dict[str, Any], *keys: str) -> str | None:
    """Return the first non-empty string value for the provided keys."""
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_output_index(entry: dict[str, Any]) -> int | None:
    """Extract an output index from a control entry."""
    for key in ("output-index", "output", "actuator-index", "relay-index", "index"):
        if key in entry:
            return _coerce_int(entry.get(key))
    return None


def _extract_index_from_address(apt_address: str) -> int | None:
    """Best-effort fallback for actuator addresses like ``SBIO0255``."""
    match = re.search(r"(\d+)$", apt_address)
    if match is None:
        return None

    return _coerce_int(match.group(1))


def _coerce_int(value: Any) -> int | None:
    """Convert values to integers when possible."""
    if isinstance(value, int):
        return value

    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None

    return None


def _merge_non_empty(target: dict[str, Any], source: dict[str, Any]) -> None:
    """Merge non-empty values from ``source`` into ``target``."""
    for key, value in source.items():
        if value in (None, "", [], {}):
            continue
        if key not in target or target[key] in (None, "", [], {}):
            target[key] = value
