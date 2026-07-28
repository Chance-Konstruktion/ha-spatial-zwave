"""The Z-Wave mesh on the floor plan.

Z-Wave JS is the one integration that already knows its own topology:
which node talks to the controller, how strong the signal was, how many
messages got through. None of that is in the device registry, so the
generic adapter cannot see it -- which is exactly why this is a separate
integration and not a special case inside the hub.

Two sources, in order of preference:

1. `hass.data["zwave_js"]`, where the running driver holds the controller
   and its nodes with live statistics. This is Z-Wave JS's internals and
   it can change between Home Assistant releases, so every single read is
   defensive.
2. The device registry, which is public, stable and always there. It has
   no signal strength but it does have `via_device`, so the star still
   draws.

If (1) is not shaped the way this expects, the layer quietly falls back to
(2) and says so in its metadata rather than disappearing. A floor plan
that loses the Z-Wave layer after a Home Assistant update is worse than
one that loses the RSSI numbers.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_time_interval

from .spatial_hub_provider import edge, spatial_provider, node

_LOGGER = logging.getLogger(__name__)

ZWAVE_DOMAIN = "zwave_js"
CONTROLLER_ID = "controller"

# Z-Wave is not chatty about topology and the statistics move slowly. A
# minute is often enough to notice a node dropping out and cheap enough
# that nobody has to think about it.
REFRESH = timedelta(seconds=60)

# RSSI in dBm. Z-Wave's usable range is roughly -95 to -50; the bands are
# deliberately wide because the number jitters by several dB between two
# readings and a plan that changes colour every minute is noise.
_GOOD = -70
_FAIR = -85


def _quality(rssi: Any) -> str:
    """One of the four words every provider speaks, from a dBm reading."""
    try:
        value = float(rssi)
    except (TypeError, ValueError):
        return "unknown"
    if value >= _GOOD:
        return "good"
    if value >= _FAIR:
        return "fair"
    return "poor"


def _driver(hass: HomeAssistant) -> Any:
    """The running Z-Wave JS driver, or None if anything is not as expected.

    Deliberately paranoid: this reaches into another integration's runtime
    data, which is not a contract anybody promised us.
    """
    try:
        entries = hass.data.get(ZWAVE_DOMAIN) or {}
        for value in entries.values():
            client = getattr(value, "client", None) or (
                value.get("client") if isinstance(value, dict) else None
            )
            driver = getattr(client, "driver", None)
            if driver is not None and getattr(driver, "controller", None):
                return driver
    except Exception:  # noqa: BLE001 - never take the layer down with it
        _LOGGER.debug("Z-Wave JS internals not readable", exc_info=True)
    return None


def _area_of(hass: HomeAssistant, home_id: Any, node_id: Any) -> str | None:
    """Where the user already put this node's device.

    Z-Wave JS identifies a device as ``(DOMAIN, f"{home_id}-{node_id}")`` --
    the network's home ID, not the literal string "zwave_js". Confirmed
    against a real installation's device registry; guessing the domain name
    instead means the lookup never matches anything.
    """
    if home_id is None or node_id is None:
        return None
    try:
        registry = dr.async_get(hass)
    except (AttributeError, KeyError):  # pragma: no cover
        return None
    device = registry.async_get_device(
        identifiers={(ZWAVE_DOMAIN, f"{home_id}-{node_id}")}
    )
    return device.area_id if device else None


def _statistic(statistics: Any, *names: str) -> Any:
    for name in names:
        value = getattr(statistics, name, None)
        if value is None and isinstance(statistics, dict):
            value = statistics.get(name)
        if value is not None:
            return value
    return None


def _repeaters(statistics: Any) -> list[int]:
    """The nodes a message actually hops through, controller-side first.

    Z-Wave JS records the *last working route* per node, and that is the
    real topology -- not a guess. Confirmed against a live network: it
    lives at ``statistics.lwr.repeaters`` and is an empty list for a node
    the controller reaches directly, which is most of them in a small
    house.

    Everything here is defensive on purpose. This is another
    integration's internal shape, and a floor plan that disappears
    because a repeater list arrived as a tuple is a bad trade.
    """
    route = _statistic(statistics, "lwr", "last_working_route")
    if route is None:
        return []
    hops = _statistic(route, "repeaters")
    if not isinstance(hops, (list, tuple)):
        return []
    return [hop for hop in hops if isinstance(hop, int)]


def _from_driver(hass: HomeAssistant, driver: Any) -> dict[str, list]:
    controller = driver.controller
    own_id = getattr(getattr(controller, "own_node_id", None), "real", None) or getattr(
        controller, "own_node_id", None
    )
    home_id = getattr(controller, "home_id", None)

    nodes = [
        node(
            CONTROLLER_ID,
            label="Z-Wave Controller",
            area_id=_area_of(hass, home_id, own_id) if own_id else None,
            state="online",
            icon="mdi:z-wave",
            quelle="driver",
        )
    ]
    edges = []

    for zwave_node in getattr(controller, "nodes", {}).values():
        node_id = getattr(zwave_node, "node_id", None)
        if node_id is None or node_id == own_id:
            continue
        status = str(getattr(zwave_node, "status", "") or "").lower()
        # Z-Wave says "asleep" about battery devices, which is neither
        # online nor broken. Flattening it to offline would paint half a
        # house red every night.
        state = {
            "alive": "online",
            "awake": "online",
            "asleep": "asleep",
            "dead": "offline",
        }.get(status, "unknown")

        statistics = getattr(zwave_node, "statistics", None)
        rssi = _statistic(statistics, "rssi", "last_rssi")
        nodes.append(
            node(
                f"node-{node_id}",
                label=str(getattr(zwave_node, "name", "") or f"Node {node_id}"),
                area_id=_area_of(hass, home_id, node_id),
                state=state,
                icon="mdi:z-wave" if state == "online" else "mdi:sleep",
                node_id=node_id,
                hersteller=getattr(
                    getattr(zwave_node, "device_config", None), "manufacturer", ""
                )
                or "",
                modell=getattr(
                    getattr(zwave_node, "device_config", None), "label", ""
                )
                or "",
                firmware=getattr(zwave_node, "firmware_version", "") or "",
                rssi=rssi,
                gesendet=_statistic(statistics, "commands_tx", "commandsTX"),
                verloren=_statistic(statistics, "commands_dropped_tx"),
            )
        )
        # The route the controller last got through on. With repeaters
        # this draws the actual chain -- controller → repeater → node --
        # instead of one straight line to a device that is in fact three
        # rooms and two hops away. That chain is the thing a mesh map is
        # for: it says which node everything else depends on.
        hops = _repeaters(statistics)
        chain = [CONTROLLER_ID, *[f"node-{hop}" for hop in hops],
                 f"node-{node_id}"]
        for index in range(len(chain) - 1):
            last = index == len(chain) - 2
            edges.append(
                edge(
                    chain[index],
                    chain[index + 1],
                    # Only the final hop carries this node's own signal
                    # reading. The ones before it belong to other nodes.
                    value=rssi if last else None,
                    quality=_quality(rssi) if last else "unknown",
                    # Solid where the route is known, dashed where it is
                    # not: a straight line to the controller means
                    # "reachable", and must not read as "wired like this".
                    dashed=not hops,
                    hops=len(hops),
                )
            )

    # A repeater appears once per node that routes through it, so the same
    # hop is drawn many times. The renderer would stack identical lines.
    seen: dict[tuple, dict] = {}
    for line in edges:
        seen.setdefault((line["source"], line["target"]), line)
    return {"nodes": nodes, "edges": list(seen.values())}


def _from_registry(hass: HomeAssistant) -> dict[str, list]:
    """Everything the public registries know, which is the star and no more."""
    try:
        registry = dr.async_get(hass)
    except (AttributeError, KeyError):  # pragma: no cover
        return {"nodes": [], "edges": []}

    devices = [
        device
        for device in getattr(registry, "devices", {}).values()
        if any(domain == ZWAVE_DOMAIN for domain, _ in getattr(device, "identifiers", ()))
    ]
    if not devices:
        return {"nodes": [], "edges": []}

    nodes = [
        node(CONTROLLER_ID, label="Z-Wave Controller", state="unknown",
             icon="mdi:z-wave", quelle="registry")
    ]
    edges = []
    for device in devices:
        nodes.append(
            node(
                f"device-{device.id}",
                label=getattr(device, "name_by_user", None)
                or getattr(device, "name", "")
                or "Z-Wave Gerät",
                area_id=getattr(device, "area_id", None),
                icon="mdi:z-wave",
                hersteller=getattr(device, "manufacturer", "") or "",
                modell=getattr(device, "model", "") or "",
            )
        )
        edges.append(
            edge(CONTROLLER_ID, f"device-{device.id}", quality="unknown", dashed=True)
        )
    return {"nodes": nodes, "edges": edges}


def async_setup_spatial(hass: HomeAssistant, entry: Any) -> None:
    def data() -> dict[str, list]:
        driver = _driver(hass)
        if driver is None:
            return _from_registry(hass)
        try:
            return _from_driver(hass, driver)
        except Exception:  # noqa: BLE001
            # One bad read must not cost the layer. The registry always
            # answers, so there is a picture either way.
            _LOGGER.debug("falling back to the device registry", exc_info=True)
            return _from_registry(hass)

    provider = spatial_provider(
        hass,
        entry,
        name="Z-Wave",
        icon="mdi:z-wave",
        data=data,
        version="260728",
    )

    # Z-Wave JS fires no signal this integration could listen to, so the
    # honest option is a slow tick rather than pretending to be pushed.
    entry.async_on_unload(
        async_track_time_interval(
            hass, lambda _now: provider.async_notify(), REFRESH
        )
    )
