"""Home Assistant stubs, so the test suite needs nothing installed.

The adapter reaches into three corners of Home Assistant: the type it
annotates with, the device registry it asks for areas, and the timer it
hangs its refresh on. None of those need to be real to answer the only
question these tests ask -- what does this provider hand the hub? -- so
they are stubbed here rather than pulled in as a dependency.

Kept deliberately thin. A stub that grows features nobody asserts on is a
second implementation to keep in step with the first.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))


def _module(name: str, **attributes) -> types.ModuleType:
    if name not in sys.modules:
        module = types.ModuleType(name)
        module.__path__ = []  # importable as a package
        sys.modules[name] = module
    module = sys.modules[name]
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


class HomeAssistant:  # noqa: D101 - a name to annotate with, nothing more
    pass


def callback(func):  # noqa: D103 - HA's marker decorator, identity here
    return func


class ConfigEntry:  # noqa: D101 - another name to annotate with
    pass


_module("homeassistant")
_module("homeassistant.core", HomeAssistant=HomeAssistant, callback=callback)
_module("homeassistant.config_entries", ConfigEntry=ConfigEntry)
_module("homeassistant.helpers")

# ── The device registry ───────────────────────────────────────────────
#
# Only the two things the adapter reads: look a device up by its
# identifiers, and iterate everything to find the Z-Wave ones.


class FakeDevice:
    def __init__(self, identifiers, *, name="", name_by_user=None,
                 area_id=None, manufacturer="", model="", device_id=None):
        self.identifiers = set(identifiers)
        self.name = name
        self.name_by_user = name_by_user
        self.area_id = area_id
        self.manufacturer = manufacturer
        self.model = model
        self.id = device_id or name or "device"


class FakeDeviceRegistry:
    def __init__(self, devices=()):
        self.devices = {device.id: device for device in devices}

    def async_get_device(self, identifiers=None, **_kwargs):
        wanted = set(identifiers or ())
        for device in self.devices.values():
            if device.identifiers & wanted:
                return device
        return None


_REGISTRY = FakeDeviceRegistry()


def set_devices(devices) -> None:
    """Point the stubbed registry at a set of devices for one test."""
    _REGISTRY.devices = {device.id: device for device in devices}


_module(
    "homeassistant.helpers.device_registry",
    async_get=lambda _hass: _REGISTRY,
)

# ── The refresh timer ─────────────────────────────────────────────────
#
# Recorded rather than run: whether the adapter asks for a tick is worth
# asserting, whether the clock works is not this suite's problem.

SCHEDULED: list = []


def async_track_time_interval(_hass, action, interval, **_kwargs):
    SCHEDULED.append((action, interval))
    return lambda: SCHEDULED.remove((action, interval))


_module(
    "homeassistant.helpers.event",
    async_track_time_interval=async_track_time_interval,
)


def async_dispatcher_send(_hass, _signal, *_args):
    return None


def async_dispatcher_connect(_hass, _signal, _target):
    return lambda: None


_module(
    "homeassistant.helpers.dispatcher",
    async_dispatcher_send=async_dispatcher_send,
    async_dispatcher_connect=async_dispatcher_connect,
)


# ── Stand-ins the tests build with ────────────────────────────────────


class FakeHass:
    """Just the ``data`` dict -- which is the whole coupling to the hub."""

    def __init__(self):
        self.data = {}

    @property
    def registrations(self):
        return self.data.get("spatial_hub_providers", {})


class FakeEntry:
    """A ConfigEntry stand-in that records its unload hooks."""

    domain = "spatial_zwave"

    def __init__(self):
        self.unload_hooks = []

    def async_on_unload(self, func):
        self.unload_hooks.append(func)

    def unload(self):
        for hook in self.unload_hooks:
            hook()
