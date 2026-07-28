"""What this integration hands the hub, from both of its two sources.

The adapter reads Z-Wave JS's running driver when it can and the device
registry when it cannot. The second path is the interesting one: it exists
so that a Home Assistant release that reshapes Z-Wave JS's internals costs
the RSSI numbers rather than the whole layer, and a fallback nobody tests
is a fallback that does not work.
"""

from __future__ import annotations

import pytest

from conftest import FakeDevice, FakeEntry, FakeHass, set_devices

from custom_components.spatial_zwave.spatial import (
    CONTROLLER_ID,
    ZWAVE_DOMAIN,
    _quality,
    async_setup_spatial,
)


# ── Z-Wave JS stand-ins ───────────────────────────────────────────────


class FakeStatistics:
    def __init__(self, rssi=None, commands_tx=None, commands_dropped_tx=None):
        self.rssi = rssi
        self.commands_tx = commands_tx
        self.commands_dropped_tx = commands_dropped_tx


class FakeDeviceConfig:
    def __init__(self, manufacturer="Aeotec", label="Multisensor 7"):
        self.manufacturer = manufacturer
        self.label = label


class FakeNode:
    def __init__(self, node_id, *, name="", status="alive", rssi=-62,
                 firmware_version="1.2"):
        self.node_id = node_id
        self.name = name
        self.status = status
        self.statistics = FakeStatistics(rssi, commands_tx=140,
                                         commands_dropped_tx=2)
        self.device_config = FakeDeviceConfig()
        self.firmware_version = firmware_version


class FakeController:
    def __init__(self, nodes=None, own_node_id=1):
        self.own_node_id = own_node_id
        self.nodes = {node.node_id: node for node in (nodes or [])}


class FakeDriver:
    def __init__(self, nodes=None):
        if nodes is None:
            nodes = [
                FakeNode(2, name="Flurlicht", rssi=-58),
                FakeNode(3, name="Fensterkontakt", status="asleep", rssi=-88),
            ]
        self.controller = FakeController(nodes)


class _Client:
    def __init__(self, driver):
        self.driver = driver


class _RuntimeData:
    """What newer Home Assistant releases park under the entry."""

    def __init__(self, client):
        self.client = client


def install_driver(hass, driver, *, as_dict=False) -> None:
    """Put a driver where the adapter goes looking for the real one.

    Z-Wave JS has held its client both as an attribute and in a dict over
    the years, and the adapter reads either. Both shapes are exercised.
    """
    client = _Client(driver)
    hass.data[ZWAVE_DOMAIN] = {
        "entry": {"client": client} if as_dict else _RuntimeData(client)
    }


def payload(hass) -> dict:
    entry = FakeEntry()
    async_setup_spatial(hass, entry)
    return hass.registrations["spatial_zwave"]["data"]()


@pytest.fixture(autouse=True)
def _clean_registry():
    set_devices([])
    yield
    set_devices([])


# ── Registration ──────────────────────────────────────────────────────


def test_it_registers_under_its_own_domain():
    hass = FakeHass()
    async_setup_spatial(hass, FakeEntry())

    registration = hass.registrations["spatial_zwave"]
    assert registration["api_version"] == 1
    assert callable(registration["data"])


def test_no_zwave_at_all_is_an_empty_plan_not_a_crash():
    """Installed without Z-Wave, or before it has started: still fine."""
    assert payload(FakeHass()) == {"nodes": [], "edges": []}


def test_unloading_the_entry_stops_the_refresh():
    hass, entry = FakeHass(), FakeEntry()
    async_setup_spatial(hass, entry)

    assert entry.unload_hooks, "the tick must be hung on the entry's unload"
    entry.unload()  # must not raise


# ── The driver path ───────────────────────────────────────────────────


def test_the_driver_gives_a_controller_and_its_nodes():
    hass = FakeHass()
    install_driver(hass, FakeDriver())
    data = payload(hass)

    ids = {node["id"] for node in data["nodes"]}
    assert ids == {CONTROLLER_ID, "node-2", "node-3"}
    assert all(edge["source"] == CONTROLLER_ID for edge in data["edges"])


def test_the_controller_is_not_also_one_of_its_own_nodes():
    hass = FakeHass()
    install_driver(hass, FakeDriver([FakeNode(1, name="Stick"),
                                     FakeNode(2, name="Lampe")]))
    data = payload(hass)

    assert {node["id"] for node in data["nodes"]} == {CONTROLLER_ID, "node-2"}


def test_a_sleeping_battery_device_is_not_reported_as_broken():
    """Half the house would go red every night otherwise."""
    hass = FakeHass()
    install_driver(hass, FakeDriver())
    nodes = {node["id"]: node for node in payload(hass)["nodes"]}

    assert nodes["node-2"]["state"] == "online"
    assert nodes["node-3"]["state"] == "asleep", "asleep is neither on nor off"


def test_the_metadata_carries_what_only_zwave_knows():
    hass = FakeHass()
    install_driver(hass, FakeDriver())
    node = next(n for n in payload(hass)["nodes"] if n["id"] == "node-2")

    assert node["metadata"]["rssi"] == -58
    assert node["metadata"]["hersteller"] == "Aeotec"
    assert node["metadata"]["node_id"] == 2


def test_edges_are_dashed_because_the_route_is_unknown():
    """Z-Wave repeats; the line means "reachable", not "wired like this"."""
    hass = FakeHass()
    install_driver(hass, FakeDriver())

    assert all(edge["dashed"] for edge in payload(hass)["edges"])


def test_a_driver_that_explodes_falls_back_instead_of_vanishing():
    """Losing the RSSI numbers beats losing the layer."""
    class Exploding:
        @property
        def controller(self):
            raise RuntimeError("Z-Wave JS changed shape")

    hass = FakeHass()
    # The lookup itself must survive a driver whose controller raises.
    install_driver(hass, Exploding())
    set_devices([FakeDevice({(ZWAVE_DOMAIN, "abc-4")}, name="Dimmer")])

    data = payload(hass)
    assert data["nodes"], "the registry always answers, so there is a picture"


# ── The registry fallback ─────────────────────────────────────────────


def test_the_registry_alone_still_draws_the_star():
    hass = FakeHass()
    set_devices([
        FakeDevice({(ZWAVE_DOMAIN, "abc-2")}, name="Flurlicht",
                   area_id="flur", manufacturer="Aeotec", device_id="d2"),
        FakeDevice({(ZWAVE_DOMAIN, "abc-3")}, name="Kontakt", device_id="d3"),
    ])
    data = payload(hass)

    assert len(data["nodes"]) == 3, "controller plus two devices"
    assert len(data["edges"]) == 2
    assert any(node.get("area_id") == "flur" for node in data["nodes"])


def test_a_users_rename_wins_in_the_fallback_too():
    hass = FakeHass()
    set_devices([
        FakeDevice({(ZWAVE_DOMAIN, "abc-2")}, name="Node 2",
                   name_by_user="Küche", device_id="d2"),
    ])
    labels = {node["label"] for node in payload(hass)["nodes"]}

    assert "Küche" in labels and "Node 2" not in labels


def test_devices_of_other_integrations_are_not_drawn_as_zwave():
    hass = FakeHass()
    set_devices([FakeDevice({("hue", "1")}, name="Hue Lampe", device_id="h1")])

    assert payload(hass) == {"nodes": [], "edges": []}, (
        "a house with no Z-Wave gets no Z-Wave layer, not an empty controller"
    )


# ── The shared vocabulary ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("rssi", "expected"),
    [
        (-50, "good"), (-70, "good"),
        (-71, "fair"), (-85, "fair"),
        (-86, "poor"), (-100, "poor"),
        (None, "unknown"), ("", "unknown"), ("laut", "unknown"),
    ],
)
def test_rssi_maps_onto_the_words_every_provider_speaks(rssi, expected):
    assert _quality(rssi) == expected


def test_both_shapes_zwave_js_has_used_are_read():
    """The client has lived as an attribute and in a dict across releases."""
    for as_dict in (False, True):
        hass = FakeHass()
        install_driver(hass, FakeDriver(), as_dict=as_dict)
        assert len(payload(hass)["nodes"]) == 3, (
            f"client as {'dict entry' if as_dict else 'attribute'} not found"
        )
