# /********************************************************************************
# * Copyright (c) 2026 Contributors to the Eclipse Foundation
# *
# * SPDX-License-Identifier: Apache-2.0
# ********************************************************************************/

import threading
import time

from kuksa_client.v2 import KuksaClient
from kuksa_client.v2 import Provider


class _BlockingBidiStream:
    def __init__(self):
        self.cancelled = False
        self._stop = threading.Event()

    def __iter__(self):
        self._stop.wait()
        return iter(())

    def cancel(self):
        self.cancelled = True
        self._stop.set()


class _FakeStub:
    def __init__(self, stream):
        self._stream = stream

    def OpenProviderStream(self, request_iterator, metadata=None):
        return self._stream


class _FakeClient:
    def __init__(self, stream):
        self._stub = _FakeStub(stream)

    def _metadata_kwargs(self):
        return []


def test_provider_close_cancels_stream():
    stream = _BlockingBidiStream()
    provider = Provider(_FakeClient(stream))
    provider._open()

    start = time.monotonic()
    provider.close()
    elapsed = time.monotonic() - start

    assert stream.cancelled is True
    assert elapsed < 2.0


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
