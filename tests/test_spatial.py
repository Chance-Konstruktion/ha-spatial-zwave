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


class FakeRoute:
    """statistics.lwr, in the shape a live network actually reports."""

    def __init__(self, repeaters=(), rssi=None):
        self.repeaters = list(repeaters)
        self.rssi = rssi
        self.repeaterRSSI = []
        self.protocolDataRate = 2


class FakeStatistics:
    def __init__(self, rssi=None, commands_tx=None, commands_dropped_tx=None,
                 repeaters=()):
        self.rssi = rssi
        self.commands_tx = commands_tx
        self.commands_dropped_tx = commands_dropped_tx
        self.lwr = FakeRoute(repeaters, rssi)


class FakeDeviceConfig:
    def __init__(self, manufacturer="Aeotec", label="Multisensor 7"):
        self.manufacturer = manufacturer
        self.label = label


class FakeNode:
    def __init__(self, node_id, *, name="", status="alive", rssi=-62,
                 firmware_version="1.2", repeaters=()):
        self.node_id = node_id
        self.name = name
        self.status = status
        self.statistics = FakeStatistics(rssi, commands_tx=140,
                                         commands_dropped_tx=2,
                                         repeaters=repeaters)
        self.device_config = FakeDeviceConfig()
        self.firmware_version = firmware_version


class FakeController:
    def __init__(self, nodes=None, own_node_id=1, home_id="3378617508"):
        self.own_node_id = own_node_id
        self.home_id = home_id
        self.nodes = {node.node_id: node for node in (nodes or [])}


class FakeDriver:
    def __init__(self, nodes=None, home_id="3378617508"):
        if nodes is None:
            nodes = [
                FakeNode(2, name="Flurlicht", rssi=-58),
                FakeNode(3, name="Fensterkontakt", status="asleep", rssi=-88),
            ]
        self.controller = FakeController(nodes, home_id=home_id)


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


def test_a_node_is_placed_by_the_home_id_node_id_identifier():
    """Z-Wave JS registers devices as f"{home_id}-{node_id}", not the
    domain name -- confirmed against a real installation's registry."""
    hass = FakeHass()
    install_driver(hass, FakeDriver(home_id="3378617508"))
    set_devices([
        FakeDevice({(ZWAVE_DOMAIN, "3378617508-2")}, name="Flurlicht",
                   area_id="flur", device_id="d2"),
    ])
    nodes = {n["id"]: n for n in payload(hass)["nodes"]}

    assert nodes["node-2"]["area_id"] == "flur"


def test_the_old_domain_prefixed_identifier_does_not_match():
    """Guessing "zwave_js-<id>" instead of the real home ID must not
    silently "work" by matching the wrong device."""
    hass = FakeHass()
    install_driver(hass, FakeDriver(home_id="3378617508"))
    set_devices([
        FakeDevice({(ZWAVE_DOMAIN, "zwave_js-2")}, name="Flurlicht",
                   area_id="flur", device_id="d2"),
    ])
    nodes = {n["id"]: n for n in payload(hass)["nodes"]}

    assert nodes["node-2"].get("area_id") is None


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


# ── The route, not a star ─────────────────────────────────────────────


def test_a_direct_node_is_one_hop_from_the_controller(mesh_or_none=None):
    """Most nodes in a small house have no repeaters; the route is empty."""
    hass = FakeHass()
    install_driver(hass, FakeDriver([FakeNode(2, name="Nah", repeaters=[])]))
    edges = payload(hass)["edges"]

    assert len(edges) == 1
    assert edges[0]["source"] == CONTROLLER_ID
    assert edges[0]["target"] == "node-2"
    assert edges[0]["dashed"], "no route known means the line is a claim"


def test_a_repeated_node_is_drawn_through_its_repeater():
    """The whole point of a mesh map: which node everything depends on."""
    hass = FakeHass()
    install_driver(hass, FakeDriver([
        FakeNode(2, name="Repeater"),
        FakeNode(7, name="Weit weg", repeaters=[2]),
    ]))
    hops = {(e["source"], e["target"]) for e in payload(hass)["edges"]}

    assert (CONTROLLER_ID, "node-2") in hops
    assert ("node-2", "node-7") in hops
    assert (CONTROLLER_ID, "node-7") not in hops, (
        "a straight line to the controller would hide the dependency"
    )


def test_a_known_route_is_drawn_solid():
    hass = FakeHass()
    install_driver(hass, FakeDriver([
        FakeNode(2, name="Repeater"),
        FakeNode(7, name="Weit weg", repeaters=[2]),
    ]))
    routed = [e for e in payload(hass)["edges"] if e["target"] == "node-7"]

    assert routed and not routed[0]["dashed"], "a measured hop is not a guess"


def test_two_nodes_behind_one_repeater_do_not_stack_the_same_line():
    hass = FakeHass()
    install_driver(hass, FakeDriver([
        FakeNode(2, name="Repeater"),
        FakeNode(7, name="A", repeaters=[2]),
        FakeNode(8, name="B", repeaters=[2]),
    ]))
    edges = payload(hass)["edges"]
    first = [e for e in edges if (e["source"], e["target"]) == (CONTROLLER_ID, "node-2")]

    assert len(first) == 1, "the shared hop is one line, drawn once"


def test_a_two_hop_route_keeps_both_hops_in_order():
    hass = FakeHass()
    install_driver(hass, FakeDriver([
        FakeNode(2), FakeNode(3), FakeNode(9, name="Ganz hinten", repeaters=[2, 3]),
    ]))
    hops = {(e["source"], e["target"]) for e in payload(hass)["edges"]}

    assert (CONTROLLER_ID, "node-2") in hops
    assert ("node-2", "node-3") in hops
    assert ("node-3", "node-9") in hops


def test_only_the_last_hop_carries_the_nodes_own_signal():
    """The hops before it belong to other nodes and are not this one's."""
    hass = FakeHass()
    install_driver(hass, FakeDriver([
        FakeNode(2, name="Repeater", rssi=-55),
        FakeNode(7, name="Weit weg", rssi=-91, repeaters=[2]),
    ]))
    last = next(e for e in payload(hass)["edges"] if e["target"] == "node-7")

    assert last["value"] == -91
    assert last["quality"] == "poor"


def test_a_route_in_a_shape_we_did_not_expect_costs_nothing():
    """Another integration's internals. A floor plan must not vanish
    because a repeater list arrived as something else."""
    hass = FakeHass()
    driver = FakeDriver([FakeNode(2)])
    driver.controller.nodes[2].statistics.lwr = "not a route at all"
    install_driver(hass, driver)

    edges = payload(hass)["edges"]
    assert len(edges) == 1 and edges[0]["dashed"], "falls back to the star"
