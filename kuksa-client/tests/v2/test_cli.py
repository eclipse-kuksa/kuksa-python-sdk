# /********************************************************************************
# * Copyright (c) 2026 Contributors to the Eclipse Foundation
# *
# * SPDX-License-Identifier: Apache-2.0
# ********************************************************************************/

import io
import threading

import grpc
import pytest
from cmd2 import Cmd

from kuksa_client.__main__ import _BackgroundSubscription
from kuksa_client.__main__ import _check_actuator_paths
from kuksa_client.__main__ import _MockActuator
from kuksa_client.__main__ import _matching_paths
from kuksa_client.__main__ import coerce_assignments
from kuksa_client.__main__ import path_completer
from kuksa_client.__main__ import set_completer
from kuksa_client.__main__ import remove_mock_completer
from kuksa_client.__main__ import unsubscribe_completer
from kuksa_client.__main__ import KuksaShell
from kuksa_client.v2 import Datapoint
from kuksa_client.v2 import DataType
from kuksa_client.v2 import EntryType
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


class _EntryTypeClient:
    def __init__(self, entry_types):
        self._entry_types = entry_types

    def get_metadata(self, path):
        if path not in self._entry_types:
            raise KuksaError(f"Path '{path}' does not exist")
        return Metadata(path=path, entry_type=self._entry_types[path])


def test_check_actuator_paths_rejects_non_actuator():
    client = _EntryTypeClient({"Vehicle.Speed": EntryType.SENSOR})
    assert _check_actuator_paths(client, ["Vehicle.Speed"]) == "Vehicle.Speed is not an actuator"


def test_check_actuator_paths_accepts_actuator():
    client = _EntryTypeClient({"Vehicle.Body.Wiper.Pos": EntryType.ACTUATOR})
    assert _check_actuator_paths(client, ["Vehicle.Body.Wiper.Pos"]) is None


class _ParseClient:
    def __init__(self, connected=True):
        self.connected = connected

    @staticmethod
    def _parse_subscribe_response(response):
        return {"Vehicle.Speed": Datapoint(42.0)}

    @staticmethod
    def _translate_rpc_error(exc):
        return KuksaError(exc.details())


class _FakeStream:
    def __init__(self, n=1, error=None):
        self._n = n
        self._error = error
        self.cancelled = False

    def __iter__(self):
        for _ in range(self._n):
            yield object()
        if self._error is not None:
            raise self._error

    def cancel(self):
        self.cancelled = True


class _FakeThread:
    def __init__(self):
        self.joined = False

    def join(self, timeout=None):
        self.joined = True


def _alert_shell():
    shell = Cmd(stdout=io.StringIO(), allow_cli_args=False)
    shell._subscriptions = {}
    shell._subscription_lock = threading.Lock()
    shell._mocks = {}
    shell._mock_lock = threading.Lock()
    return shell


def _grpc_error(code, details):
    return grpc.aio.AioRpcError(
        code=code,
        initial_metadata=grpc.aio.Metadata(),
        trailing_metadata=grpc.aio.Metadata(),
        details=details,
    )


def test_subscribe_background_queues_alert():
    shell = _alert_shell()
    client = _ParseClient()
    KuksaShell._subscribe_background(shell, 1, client, _FakeStream(n=1))
    assert len(shell._alert_queue) == 1
    assert "42.0" in shell._alert_queue[0].msg


def test_subscribe_background_cancelled_silent():
    shell = _alert_shell()
    client = _ParseClient(connected=True)
    error = _grpc_error(grpc.StatusCode.CANCELLED, "cancelled")
    KuksaShell._subscribe_background(shell, 1, client, _FakeStream(n=0, error=error))
    assert len(shell._alert_queue) == 0


def test_subscribe_background_error_alerts_when_connected():
    shell = _alert_shell()
    client = _ParseClient(connected=True)
    error = _grpc_error(grpc.StatusCode.NOT_FOUND, "Path not found")
    KuksaShell._subscribe_background(shell, 1, client, _FakeStream(n=0, error=error))
    assert len(shell._alert_queue) == 1
    assert "Subscription error" in shell._alert_queue[0].msg


def test_subscribe_background_error_silent_when_disconnected():
    shell = _alert_shell()
    client = _ParseClient(connected=False)
    error = _grpc_error(grpc.StatusCode.NOT_FOUND, "Path not found")
    KuksaShell._subscribe_background(shell, 1, client, _FakeStream(n=0, error=error))
    assert len(shell._alert_queue) == 0


def test_unsubscribe_completer():
    shell = _alert_shell()
    shell._subscriptions = {
        1: _BackgroundSubscription(paths=["Vehicle.Speed"]),
        2: _BackgroundSubscription(paths=["Vehicle.Speed", "Vehicle.ADAS.ABS.IsActive"]),
    }
    completions = unsubscribe_completer(shell, "", "", 0, 0)
    by_text = {item.text: item.display for item in completions.items}
    assert set(by_text) == {"1", "2"}
    assert by_text["1"] == "1: Vehicle.Speed"
    assert by_text["2"] == "2: Vehicle.Speed, Vehicle.ADAS.ABS.IsActive"


def test_cancel_subscription():
    shell = _alert_shell()
    stream = _FakeStream()
    thread = _FakeThread()
    shell._subscriptions[3] = _BackgroundSubscription(
        paths=["Vehicle.Speed"], stream=stream, thread=thread
    )
    info = KuksaShell._cancel_subscription(shell, 3)
    assert info.paths == ["Vehicle.Speed"]
    assert stream.cancelled is True
    assert thread.joined is True
    assert 3 not in shell._subscriptions


def test_cancel_subscription_missing():
    shell = _alert_shell()
    assert KuksaShell._cancel_subscription(shell, 99) is None


class _FakeRequest:
    def __init__(self, path, value):
        self.path = path
        self.value = value


class _FakeProvider:
    def __init__(self, batches):
        self._batches = batches
        self.closed = False
        self.accepted = []

    def actuation_requests(self):
        yield from self._batches

    def accept(self, request, ok=True):
        self.accepted.append(request)

    def close(self):
        self.closed = True


def test_remove_mock_completer():
    shell = _alert_shell()
    shell._mocks = {
        1: _MockActuator(paths=["Vehicle.Body.Wiper.Pos"]),
        2: _MockActuator(paths=["Vehicle.Body.Wiper.Pos", "Vehicle.Cabin.Sunroof.Position"]),
    }
    completions = remove_mock_completer(shell, "", "", 0, 0)
    by_text = {item.text: item.display for item in completions.items}
    assert set(by_text) == {"1", "2"}
    assert by_text["1"] == "1: Vehicle.Body.Wiper.Pos"
    assert by_text["2"] == "2: Vehicle.Body.Wiper.Pos, Vehicle.Cabin.Sunroof.Position"


def test_cancel_mock():
    shell = _alert_shell()
    provider = _FakeProvider(batches=[])
    thread = _FakeThread()
    shell._mocks[5] = _MockActuator(paths=["Vehicle.Body.Wiper.Pos"], provider=provider, thread=thread)
    info = KuksaShell._cancel_mock(shell, 5)
    assert info.paths == ["Vehicle.Body.Wiper.Pos"]
    assert provider.closed is True
    assert thread.joined is True
    assert 5 not in shell._mocks


def test_cancel_mock_missing():
    shell = _alert_shell()
    assert KuksaShell._cancel_mock(shell, 99) is None


def test_mock_actuator_loop_accepts_and_alerts():
    shell = _alert_shell()
    request = _FakeRequest("Vehicle.Body.Wiper.Pos", 45.0)
    provider = _FakeProvider(batches=[[request]])
    KuksaShell._mock_actuator_loop(shell, 1, provider)
    assert len(shell._alert_queue) == 1
    assert "Vehicle.Body.Wiper.Pos" in shell._alert_queue[0].msg
    assert "45.0" in shell._alert_queue[0].msg
    assert provider.accepted == [request]
