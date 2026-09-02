# /********************************************************************************
# * Copyright (c) 2026 Contributors to the Eclipse Foundation
# *
# * See the NOTICE file(s) distributed with this work for additional
# * information regarding copyright ownership.
# *
# * This program and the accompanying materials are made available under the
# * terms of the Apache License 2.0 which is available at
# * http://www.apache.org/licenses/LICENSE-2.0
# *
# * SPDX-License-Identifier: Apache-2.0
# ********************************************************************************/

import asyncio
import os
import shutil
import threading

import grpc
import pytest

from kuksa.val.v2 import types_pb2
from kuksa.val.v2 import val_pb2_grpc

from .mock_databroker import MockDatabroker


def build_default_tree() -> MockDatabroker:
    broker = MockDatabroker()
    broker.add_signal(
        "Vehicle.Speed",
        types_pb2.DATA_TYPE_FLOAT,
        types_pb2.ENTRY_TYPE_SENSOR,
        description="Vehicle speed.",
    )
    broker.add_signal(
        "Vehicle.ADAS.ABS.IsActive",
        types_pb2.DATA_TYPE_BOOLEAN,
        types_pb2.ENTRY_TYPE_SENSOR,
    )
    broker.add_signal(
        "Vehicle.SomeString",
        types_pb2.DATA_TYPE_STRING,
        types_pb2.ENTRY_TYPE_ATTRIBUTE,
    )
    broker.add_signal(
        "Vehicle.Body.Windshield.Front.Wiping.System.TargetPosition",
        types_pb2.DATA_TYPE_FLOAT,
        types_pb2.ENTRY_TYPE_ACTUATOR,
    )
    broker.add_signal(
        "Vehicle.Body.Windshield.Front.Wiping.System.Mode",
        types_pb2.DATA_TYPE_STRING,
        types_pb2.ENTRY_TYPE_ACTUATOR,
    )
    broker.add_signal(
        "Vehicle.Cabin.Sunroof.Position",
        types_pb2.DATA_TYPE_FLOAT,
        types_pb2.ENTRY_TYPE_ACTUATOR,
    )
    broker.add_signal(
        "Vehicle.Cabin.Sunroof.Switch",
        types_pb2.DATA_TYPE_BOOLEAN,
        types_pb2.ENTRY_TYPE_ACTUATOR,
    )
    broker.add_signal(
        "Vehicle.Cabin.Sunroof.Shade.Position",
        types_pb2.DATA_TYPE_FLOAT,
        types_pb2.ENTRY_TYPE_ACTUATOR,
    )
    broker.add_signal(
        "Vehicle.Cabin.Sunroof.Shade.Switch",
        types_pb2.DATA_TYPE_BOOLEAN,
        types_pb2.ENTRY_TYPE_ACTUATOR,
    )
    broker.add_signal(
        "Vehicle.Cabin.Seat.Row1.Pos1.Position",
        types_pb2.DATA_TYPE_FLOAT,
        types_pb2.ENTRY_TYPE_ACTUATOR,
    )
    return broker


@pytest.fixture
def broker():
    return build_default_tree()


@pytest.fixture
def server(broker, unused_tcp_port):
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    holder = {}

    async def _setup():
        grpc_server = grpc.aio.server()
        val_pb2_grpc.add_VALServicer_to_server(broker, grpc_server)
        grpc_server.add_insecure_port(f"127.0.0.1:{unused_tcp_port}")
        await grpc_server.start()
        holder["server"] = grpc_server

    asyncio.run_coroutine_threadsafe(_setup(), loop).result()
    try:
        yield unused_tcp_port
    finally:
        async def _teardown():
            await holder["server"].stop(grace=0.5)

        asyncio.run_coroutine_threadsafe(_teardown(), loop).result()
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)


@pytest.fixture
def unix_server(broker):
    import tempfile

    tmp_dir = tempfile.mkdtemp(prefix="kuksa", dir="/tmp")
    socket_path = os.path.join(tmp_dir, "k.sock")
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    holder = {}

    async def _setup():
        grpc_server = grpc.aio.server()
        val_pb2_grpc.add_VALServicer_to_server(broker, grpc_server)
        grpc_server.add_insecure_port(f"unix:{socket_path}")
        await grpc_server.start()
        holder["server"] = grpc_server

    asyncio.run_coroutine_threadsafe(_setup(), loop).result()
    try:
        yield socket_path
    finally:
        async def _teardown():
            await holder["server"].stop(grace=0.5)

        asyncio.run_coroutine_threadsafe(_teardown(), loop).result()
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        shutil.rmtree(tmp_dir, ignore_errors=True)
