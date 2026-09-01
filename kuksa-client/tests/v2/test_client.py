# /********************************************************************************
# * Copyright (c) 2026 Contributors to the Eclipse Foundation
# *
# * SPDX-License-Identifier: Apache-2.0
# ********************************************************************************/

import pytest

from kuksa_client.v2 import DataType
from kuksa_client.v2 import Datapoint
from kuksa_client.v2 import EntryType
from kuksa_client.v2 import KuksaClient
from kuksa_client.v2 import NotFound


@pytest.fixture
def client(server):
    with KuksaClient("127.0.0.1", server) as client:
        yield client


def test_get_missing_raises_not_found(client):
    with pytest.raises(NotFound):
        client.get("Vehicle.DoesNotExist")


def test_get_no_value_returns_none(client):
    datapoint = client.get("Vehicle.Speed")
    assert datapoint.value is None


def test_set_and_get_round_trip(client):
    client.set({"Vehicle.Speed": 42.0})
    datapoint = client.get("Vehicle.Speed")
    assert datapoint.value == 42.0


def test_set_with_datapoint(client):
    client.set({"Vehicle.Speed": Datapoint(43.0)})
    assert client.get("Vehicle.Speed").value == 43.0


def test_set_with_explicit_data_type(client):
    client.set({"Vehicle.Speed": 44.0}, data_type=DataType.FLOAT)
    assert client.get("Vehicle.Speed").value == 44.0


def test_get_many(client):
    client.set({"Vehicle.Speed": 1.0, "Vehicle.ADAS.ABS.IsActive": True})
    values = client.get(["Vehicle.Speed", "Vehicle.ADAS.ABS.IsActive"])
    assert values["Vehicle.Speed"].value == 1.0
    assert values["Vehicle.ADAS.ABS.IsActive"].value is True


def test_get_many_all_or_nothing(client):
    with pytest.raises(NotFound):
        client.get(["Vehicle.Speed", "Vehicle.DoesNotExist"])


def test_get_metadata(client):
    metadata = client.get_metadata("Vehicle.Speed")
    assert metadata.data_type == DataType.FLOAT
    assert metadata.entry_type == EntryType.SENSOR
    assert metadata.description == "Vehicle speed."


def test_get_metadata_missing(client):
    with pytest.raises(NotFound):
        client.get_metadata("Vehicle.DoesNotExist")


def test_list_metadata_pattern(client):
    metadatas = client.list_metadata("Vehicle.Cabin.Sunroof.*")
    paths = {m.path for m in metadatas}
    assert paths == {"Vehicle.Cabin.Sunroof.Position", "Vehicle.Cabin.Sunroof.Switch"}


def test_expand(client):
    paths = client.expand("Vehicle.Cabin.Sunroof.**")
    assert "Vehicle.Cabin.Sunroof.Shade.Position" in paths
    assert "Vehicle.Cabin.Sunroof.Position" in paths


def test_expand_by_entry_type(client):
    sensors = client.expand("Vehicle.**", entry_type=EntryType.SENSOR)
    assert sensors == ["Vehicle.ADAS.ABS.IsActive", "Vehicle.Speed"]


def test_has_signal(client):
    assert client.has_signal("Vehicle.Speed") is True
    assert client.has_signal("Vehicle.DoesNotExist") is False


def test_has_signals(client):
    assert client.has_signals(["Vehicle.Speed", "Vehicle.ADAS.ABS.IsActive"]) is True
    assert client.has_signals(["Vehicle.Speed", "Vehicle.DoesNotExist"]) is False


def test_missing_signals(client):
    missing = client.missing_signals(["Vehicle.Speed", "Vehicle.DoesNotExist"])
    assert missing == {"Vehicle.DoesNotExist"}


def test_get_server_info(client):
    info = client.get_server_info()
    assert info.name == "mock-databroker"
    assert info.version == "0.0.0"


def test_subscribe(client):
    client.set({"Vehicle.Speed": 10.0})
    iterator = client.subscribe(["Vehicle.Speed"])
    first = next(iterator)
    assert first["Vehicle.Speed"].value == 10.0

    client.set({"Vehicle.Speed": 20.0})
    second = next(iterator)
    assert second["Vehicle.Speed"].value == 20.0
