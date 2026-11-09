# /********************************************************************************
# * Copyright (c) 2026 Contributors to the Eclipse Foundation
# *
# * SPDX-License-Identifier: Apache-2.0
# ********************************************************************************/

import asyncio

import pytest

from kuksa_client.v2.aio import KuksaClient
from kuksa_client.v2.aio import Provider


async def _wait_for_value(client, path, expected, timeout=5.0):
    """Wait until a published value becomes visible in the databroker."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if (await client.get(path)).value == expected:
            return
        await asyncio.sleep(0.01)
    assert (await client.get(path)).value == expected


@pytest.mark.asyncio
async def test_provider_publish(server):
    async with KuksaClient("127.0.0.1", server) as client:
        provider = Provider(client)
        try:
            await provider.provide_signals({"Vehicle.Speed": None})
            await provider.publish({"Vehicle.Speed": 42.5})
            await _wait_for_value(client, "Vehicle.Speed", 42.5)
        finally:
            await provider.close()


@pytest.mark.asyncio
async def test_provider_actuation(server):
    async with KuksaClient("127.0.0.1", server) as client:
        provider = Provider(client)
        try:
            await provider.provide_actuators(
                ["Vehicle.Body.Windshield.Front.Wiping.System.TargetPosition"]
            )
            await client.actuate(
                {"Vehicle.Body.Windshield.Front.Wiping.System.TargetPosition": 45.0}
            )
            requests = await provider.actuation_requests().__anext__()
            assert len(requests) == 1
            request = requests[0]
            assert request.path == "Vehicle.Body.Windshield.Front.Wiping.System.TargetPosition"
            assert request.value == 45.0
            await provider.accept(request, ok=True)
        finally:
            await provider.close()
