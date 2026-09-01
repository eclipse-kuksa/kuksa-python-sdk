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

"""
In-memory ``kuksa.val.v2`` databroker used for testing the SDK.

Implements the full VAL service over an in-memory VSS tree so that streaming
(subscribe) and provider (OpenProviderStream) paths are genuinely exercised.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
from typing import Dict
from typing import Optional

import grpc

from kuksa.val.v2 import types_pb2
from kuksa.val.v2 import val_pb2
from kuksa.val.v2 import val_pb2_grpc

_END = object()


@dataclasses.dataclass
class _Signal:
    path: str
    signal_id: int
    data_type: int
    entry_type: int
    description: str = ""


class _ProviderConnection:
    def __init__(self):
        self.outgoing: asyncio.Queue = asyncio.Queue()


class MockDatabroker(val_pb2_grpc.VALServicer):
    def __init__(self):
        self._signals: Dict[str, _Signal] = {}
        self._id_to_path: Dict[int, str] = {}
        self._values: Dict[str, types_pb2.Datapoint] = {}
        self._subscribers = []  # list of (set(paths), asyncio.Queue)
        self._providers: Dict[str, _ProviderConnection] = {}
        self._next_id = 1

    # ------------------------------------------------------------------
    # Tree construction helpers
    # ------------------------------------------------------------------
    def add_signal(
        self,
        path: str,
        data_type: int,
        entry_type: int,
        description: str = "",
        value=None,
    ) -> "_Signal":
        signal = _Signal(path, self._next_id, data_type, entry_type, description)
        self._next_id += 1
        self._signals[path] = signal
        self._id_to_path[signal.signal_id] = path
        if value is not None:
            self._values[path] = _to_datapoint(value, data_type)
        return signal

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _signal_path(self, signal_id: types_pb2.SignalID) -> Optional[str]:
        if signal_id.HasField("path"):
            return signal_id.path
        if signal_id.HasField("id"):
            return self._id_to_path.get(signal_id.id)
        return None

    def _get_datapoint(self, path: str) -> types_pb2.Datapoint:
        return self._values.get(path, types_pb2.Datapoint())

    def _to_metadata(self, signal: _Signal) -> types_pb2.Metadata:
        return types_pb2.Metadata(
            path=signal.path,
            id=signal.signal_id,
            data_type=signal.data_type,
            entry_type=signal.entry_type,
            description=signal.description,
        )

    def _notify(self, entries: Dict[str, types_pb2.Datapoint]) -> None:
        for subscribed_paths, queue in self._subscribers:
            matched = {
                path: dp for path, dp in entries.items() if path in subscribed_paths
            }
            if matched:
                queue.put_nowait(matched)

    # ------------------------------------------------------------------
    # Unary RPCs
    # ------------------------------------------------------------------
    async def GetValue(self, request, context):
        path = self._signal_path(request.signal_id)
        if path is None or path not in self._signals:
            await context.abort(grpc.StatusCode.NOT_FOUND, "Path not found")
        return val_pb2.GetValueResponse(data_point=self._get_datapoint(path))

    async def GetValues(self, request, context):
        data_points = []
        for signal_id in request.signal_ids:
            path = self._signal_path(signal_id)
            if path is None or path not in self._signals:
                await context.abort(grpc.StatusCode.NOT_FOUND, "Path not found")
            data_points.append(self._get_datapoint(path))
        return val_pb2.GetValuesResponse(data_points=data_points)

    async def ListMetadata(self, request, context):
        root = request.root
        if root == "":
            metadata = [self._to_metadata(s) for s in self._signals.values()]
            return val_pb2.ListMetadataResponse(metadata=metadata)

        if root in self._signals:
            return val_pb2.ListMetadataResponse(
                metadata=[self._to_metadata(self._signals[root])]
            )

        prefix = root + "."
        metadata = [
            self._to_metadata(s)
            for s in self._signals.values()
            if s.path.startswith(prefix)
        ]
        if metadata:
            return val_pb2.ListMetadataResponse(metadata=metadata)

        await context.abort(grpc.StatusCode.NOT_FOUND, "Path not found")

    async def PublishValue(self, request, context):
        path = self._signal_path(request.signal_id)
        if path is None or path not in self._signals:
            await context.abort(grpc.StatusCode.NOT_FOUND, "Path not found")
        self._values[path] = request.data_point
        self._notify({path: request.data_point})
        return val_pb2.PublishValueResponse()

    async def Actuate(self, request, context):
        await self._actuate([request], context)
        return val_pb2.ActuateResponse()

    async def BatchActuate(self, request, context):
        await self._actuate(request.actuate_requests, context)
        return val_pb2.BatchActuateResponse()

    async def _actuate(self, actuate_requests, context):
        for actuate_request in actuate_requests:
            path = self._signal_path(actuate_request.signal_id)
            if path is None or path not in self._signals:
                await context.abort(grpc.StatusCode.NOT_FOUND, "Path not found")
            if self._signals[path].entry_type != types_pb2.ENTRY_TYPE_ACTUATOR:
                await context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT, "Path is not an actuator"
                )
        for actuate_request in actuate_requests:
            path = self._signal_path(actuate_request.signal_id)
            provider = self._providers.get(path)
            if provider is None:
                await context.abort(
                    grpc.StatusCode.UNAVAILABLE, "No provider for actuator"
                )
        for actuate_request in actuate_requests:
            path = self._signal_path(actuate_request.signal_id)
            request = val_pb2.BatchActuateStreamRequest(
                actuate_requests=[actuate_request]
            )
            self._providers[path].outgoing.put_nowait(
                val_pb2.OpenProviderStreamResponse(
                    batch_actuate_stream_request=request
                )
            )

    async def GetServerInfo(self, request, context):
        return val_pb2.GetServerInfoResponse(
            name="mock-databroker", version="0.0.0", commit_hash="deadbeef"
        )

    # ------------------------------------------------------------------
    # Streaming RPCs
    # ------------------------------------------------------------------
    async def Subscribe(self, request, context):
        for path in request.signal_paths:
            if path not in self._signals:
                await context.abort(grpc.StatusCode.NOT_FOUND, "Path not found")

        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append((set(request.signal_paths), queue))
        initial = {
            path: self._get_datapoint(path) for path in request.signal_paths
        }
        yield val_pb2.SubscribeResponse(entries=initial)
        while True:
            entries = await queue.get()
            yield val_pb2.SubscribeResponse(entries=entries)

    async def OpenProviderStream(self, request_iterator, context):
        provider = _ProviderConnection()

        async def handle_requests():
            try:
                async for request in request_iterator:
                    await self._handle_provider_request(provider, request, context)
            except Exception:  # noqa: BLE001
                pass
            finally:
                await provider.outgoing.put(_END)

        reader = asyncio.create_task(handle_requests())
        try:
            while True:
                item = await provider.outgoing.get()
                if item is _END:
                    return
                yield item
        finally:
            reader.cancel()

    async def _handle_provider_request(self, provider, request, context):
        action = request.WhichOneof("action")
        if action == "provide_signal_request":
            for signal_id in request.provide_signal_request.signals_sample_intervals:
                if signal_id not in self._id_to_path:
                    await context.abort(
                        grpc.StatusCode.NOT_FOUND, "Signal not found"
                    )
            await provider.outgoing.put(
                val_pb2.OpenProviderStreamResponse(
                    provide_signal_response=val_pb2.ProvideSignalResponse()
                )
            )
        elif action == "provide_actuation_request":
            identifiers = request.provide_actuation_request.actuator_identifiers
            for signal_id in identifiers:
                path = self._signal_path(signal_id)
                if path is None or path not in self._signals:
                    await context.abort(
                        grpc.StatusCode.NOT_FOUND, "Actuator not found"
                    )
                self._providers[path] = provider
            await provider.outgoing.put(
                val_pb2.OpenProviderStreamResponse(
                    provide_actuation_response=val_pb2.ProvideActuationResponse()
                )
            )
        elif action == "publish_values_request":
            entries = {}
            for signal_id, datapoint in request.publish_values_request.data_points.items():
                path = self._id_to_path.get(signal_id)
                if path is None:
                    continue
                self._values[path] = datapoint
                entries[path] = datapoint
            self._notify(entries)
        elif action == "batch_actuate_stream_response":
            pass


def _to_datapoint(value, data_type: int) -> types_pb2.Datapoint:
    message = types_pb2.Datapoint()
    message.value.CopyFrom(_to_value(value, data_type))
    message.timestamp.FromDatetime(
        datetime.datetime.now(tz=datetime.timezone.utc)
    )
    return message


def _to_value(value, data_type: int) -> types_pb2.Value:
    from kuksa_client.v2 import codec  # noqa: PLC0415
    from kuksa_client.v2.types import DataType

    return codec.to_proto_value(value, DataType(data_type))
