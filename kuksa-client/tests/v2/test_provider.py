# /********************************************************************************
# * Copyright (c) 2026 Contributors to the Eclipse Foundation
# *
# * SPDX-License-Identifier: Apache-2.0
# ********************************************************************************/

from kuksa_client.v2 import KuksaClient
from kuksa_client.v2 import Provider


def test_provider_publish(server):
    with KuksaClient("127.0.0.1", server) as client:
        provider = Provider(client)
        try:
            provider.provide_signals({"Vehicle.Speed": None})
            provider.publish({"Vehicle.Speed": 42.5})
            assert client.get("Vehicle.Speed").value == 42.5
        finally:
            provider.close()


def test_provider_actuation(server):
    with KuksaClient("127.0.0.1", server) as client:
        provider = Provider(client)
        try:
            provider.provide_actuators(
                ["Vehicle.Body.Windshield.Front.Wiping.System.TargetPosition"]
            )
            client.actuate(
                {"Vehicle.Body.Windshield.Front.Wiping.System.TargetPosition": 45.0}
            )
            requests = next(provider.actuation_requests())
            assert len(requests) == 1
            request = requests[0]
            assert request.path == "Vehicle.Body.Windshield.Front.Wiping.System.TargetPosition"
            assert request.value == 45.0
            provider.accept(request, ok=True)
        finally:
            provider.close()
