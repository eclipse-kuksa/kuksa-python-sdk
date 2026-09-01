# /********************************************************************************
# * Copyright (c) 2026 Contributors to the Eclipse Foundation
# *
# * SPDX-License-Identifier: Apache-2.0
# ********************************************************************************/

import io

import pytest
from cmd2 import Cmd

from kuksa_client.__main__ import _matching_paths
from kuksa_client.__main__ import coerce_assignments
from kuksa_client.__main__ import path_completer
from kuksa_client.__main__ import set_completer
from kuksa_client.__main__ import KuksaShell
from kuksa_client.v2 import Datapoint
from kuksa_client.v2 import DataType
from kuksa_client.v2 import KuksaError
from kuksa_client.v2 import Metadata

PATHS = [
    "Vehicle.ADAS.ABS.IsActive",
    "Vehicle.Cabin.Sunroof.Position",
    "Vehicle.Cabin.Sunroof.Switch",
    "Vehicle.SomeString",
    "Vehicle.Speed",
]


class _FakeClient:
    def __init__(self, paths):
        self._paths = paths

    def expand(self, pattern):
        assert pattern == ""
        return self._paths


def _make_shell(paths=PATHS):
    shell = Cmd(stdout=io.StringIO(), allow_cli_args=False)
    shell.client = _FakeClient(paths)
    shell._completion_paths = []
    return shell


def test_matching_paths_case_insensitive():
    shell = _make_shell()
    assert _matching_paths(shell, "Vehicle.S") == ["Vehicle.SomeString", "Vehicle.Speed"]
    assert _matching_paths(shell, "vehicle.s") == ["Vehicle.SomeString", "Vehicle.Speed"]
    assert _matching_paths(shell, "Kuksa") == []


def test_matching_paths_caches():
    shell = _make_shell()
    _matching_paths(shell, "Vehicle.S")
    assert shell._completion_paths == PATHS


def test_path_completer():
    shell = _make_shell()
    completions = path_completer(
        shell, "Vehicle.Cabin.Sunroof.", "", 0, len("Vehicle.Cabin.Sunroof.")
    )
    assert sorted(item.text for item in completions.items) == [
        "Vehicle.Cabin.Sunroof.Position",
        "Vehicle.Cabin.Sunroof.Switch",
    ]


def test_path_completer_not_connected():
    shell = Cmd(stdout=io.StringIO(), allow_cli_args=False)
    shell.client = None
    shell._completion_paths = []
    completions = path_completer(shell, "Vehicle.", "", 0, 8)
    assert list(completions.items) == []


def test_set_completer_preserves_value_suffix():
    shell = _make_shell()
    text = "Vehicle.S=42"
    completions = set_completer(shell, text, "set Vehicle.S=42", 4, 4 + len(text))
    assert sorted(item.text for item in completions.items) == [
        "Vehicle.SomeString",
        "Vehicle.Speed",
    ]


def test_set_completer_without_equals():
    shell = _make_shell()
    completions = set_completer(shell, "Vehicle.S", "set Vehicle.S", 4, 4 + len("Vehicle.S"))
    assert sorted(item.text for item in completions.items) == [
        "Vehicle.SomeString",
        "Vehicle.Speed",
    ]


class _MetadataClient:
    def __init__(self, data_types):
        self._data_types = data_types

    def get_metadata(self, path):
        if path not in self._data_types:
            raise KuksaError(f"Path '{path}' does not exist")
        return Metadata(path=path, data_type=self._data_types[path])


def test_coerce_assignments():
    client = _MetadataClient({
        "Vehicle.Speed": DataType.FLOAT,
        "Vehicle.ADAS.ABS.IsActive": DataType.BOOLEAN,
        "Vehicle.OBD.DTCList": DataType.STRING_ARRAY,
    })
    updates = coerce_assignments(
        client,
        ["Vehicle.Speed=42", "Vehicle.ADAS.ABS.IsActive=true", "Vehicle.OBD.DTCList=['a','b']"],
    )
    assert updates == {
        "Vehicle.Speed": 42.0,
        "Vehicle.ADAS.ABS.IsActive": True,
        "Vehicle.OBD.DTCList": ["a", "b"],
    }


def test_coerce_assignments_missing_equals():
    client = _MetadataClient({})
    with pytest.raises(KuksaError):
        coerce_assignments(client, ["Vehicle.Speed"])


def test_coerce_assignments_unknown_path():
    client = _MetadataClient({})
    with pytest.raises(KuksaError):
        coerce_assignments(client, ["Vehicle.NoSuch=1"])


class _SubscribingClient:
    def __init__(self, batches, connected=True):
        self._batches = batches
        self.connected = connected

    def subscribe(self, paths):
        yield from self._batches


class _FailingClient:
    def __init__(self, connected=True):
        self.connected = connected

    def subscribe(self, paths):
        if False:  # pragma: no cover - make this a generator
            yield
        raise KuksaError("Path not found")


def _alert_shell():
    return Cmd(stdout=io.StringIO(), allow_cli_args=False)


def test_subscribe_background_queues_alert():
    shell = _alert_shell()
    client = _SubscribingClient([{"Vehicle.Speed": Datapoint(42.0)}])
    KuksaShell._subscribe_background(shell, client, ["Vehicle.Speed"])
    assert len(shell._alert_queue) == 1
    assert "42.0" in shell._alert_queue[0].msg


def test_subscribe_background_error_alerts_when_connected():
    shell = _alert_shell()
    client = _FailingClient(connected=True)
    KuksaShell._subscribe_background(shell, client, ["Vehicle.NoSuch"])
    assert len(shell._alert_queue) == 1
    assert "Subscription error" in shell._alert_queue[0].msg


def test_subscribe_background_error_silent_when_disconnected():
    shell = _alert_shell()
    client = _FailingClient(connected=False)
    KuksaShell._subscribe_background(shell, client, ["Vehicle.NoSuch"])
    assert len(shell._alert_queue) == 0
