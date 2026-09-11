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
Asynchronous (asyncio) client and provider for ``kuksa.val.v2``.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any
from typing import AsyncIterator
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional

import grpc
from kuksa.val.v2 import val_pb2_grpc

from . import coercion
from . import patterns
from . import transport
from .core import _KuksaCore
from .errors import NotFound
from .errors import from_grpc_error
from .provider import ActuationRequest
from .provider import _ProviderBase
from .provider import _STOP
from .types import DataType
from .types import Datapoint
from .types import EntryType
from .types import Metadata
from .types import ServerInfo

__all__ = ["KuksaClient", "Provider"]


class KuksaClient(_KuksaCore):
    """Asynchronous client for a ``kuksa.val.v2`` databroker."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 55555,
        token: Optional[str] = None,
        root_certificates: Optional[Path] = None,
        tls_server_name: Optional[str] = None,
        unix_socket: Optional[Path] = None,
        ensure_startup_connection: bool = True,
    ):
        super().__init__(
            host,
            port,
            token=token,
            root_certificates=root_certificates,
            tls_server_name=tls_server_name,
            unix_socket=unix_socket,
            ensure_startup_connection=ensure_startup_connection,
        )
        self._channel = None
        self._stub = None
        self._exit_stack = contextlib.AsyncExitStack()

    async def __aenter__(self) -> "KuksaClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        await self.disconnect()
        self._channel = await self._exit_stack.enter_async_context(
            transport.create_aio_channel(
                self.host,
                self.port,
                self.root_certificates,
                self.tls_server_name,
                self.unix_socket,
            )
        )
        self._stub = val_pb2_grpc.VALStub(self._channel)
        self._connected = True
        self._metadata_store.invalidate()

    async def disconnect(self) -> None:
        await self._exit_stack.aclose()
        self._channel = None
        self._stub = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def stub(self):
        """The raw ``kuksa.val.v2.VALStub`` for power users."""
        return self._stub

    async def _call(self, rpc_name: str, request, timeout: Optional[float] = None):
        return await getattr(self._stub, rpc_name)(
            request, timeout=timeout, metadata=self._metadata_kwargs()
        )

    def _stream(self, rpc_name: str, request, timeout: Optional[float] = None):
        return getattr(self._stub, rpc_name)(
            request, timeout=timeout, metadata=self._metadata_kwargs()
        )

    # ------------------------------------------------------------------
    # Internal metadata helpers
    # ------------------------------------------------------------------
    async def _fetch_metadata(self, root: str) -> List[Metadata]:
        try:
            response = await self._call(
                "ListMetadata", self._build_list_metadata_request(root)
            )
        except grpc.RpcError as exc:
            raise from_grpc_error(exc) from exc
        return self._parse_and_cache_list_metadata(response)

    async def _resolve_data_types(self, paths: Iterable[str]) -> Dict[str, DataType]:
        result: Dict[str, DataType] = {}
        for path in paths:
            data_type = self._metadata_store.data_type(path)
            if data_type is not None and data_type != DataType.UNSPECIFIED:
                result[path] = data_type
                continue
            metadata = self._metadata_store.get(path)
            if metadata is not None:
                result[path] = metadata.data_type
                continue
            if self._metadata_store.is_missing(path):
                raise NotFound(f"Path '{path}' does not exist on the server")
            await self._fetch_metadata(path)
            metadata = self._metadata_store.get(path)
            if metadata is None:
                self._metadata_store.mark_missing(path)
                raise NotFound(f"Path '{path}' does not exist on the server")
            result[path] = metadata.data_type
        return result

    async def _resolve_signal_ids(self, paths: Iterable[str]) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for path in paths:
            signal_id = self._metadata_store.signal_id(path)
            if signal_id is not None:
                result[path] = signal_id
                continue
            if self._metadata_store.is_missing(path):
                raise NotFound(f"Path '{path}' does not exist on the server")
            await self._fetch_metadata(path)
            signal_id = self._metadata_store.signal_id(path)
            if signal_id is None:
                self._metadata_store.mark_missing(path)
                raise NotFound(f"Path '{path}' does not exist on the server")
            result[path] = signal_id
        return result

    async def _existing_signals(self, paths: Iterable[str]) -> set:
        existing = set()
        for path in paths:
            if self._metadata_store.has(path):
                existing.add(path)
                continue
            if self._metadata_store.is_missing(path):
                continue
            try:
                await self._fetch_metadata(path)
            except NotFound:
                self._metadata_store.mark_missing(path)
                continue
            if self._metadata_store.has(path):
                existing.add(path)
            else:
                self._metadata_store.mark_missing(path)
        return existing

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_updates(values: Dict[str, Any]) -> Dict[str, Datapoint]:
        return {
            path: (value if isinstance(value, Datapoint) else Datapoint(value=value))
            for path, value in values.items()
        }

    async def coerce_updates(self, values: Dict[str, Any]) -> Dict[str, Any]:
        """
        Coerce string values to each signal's data type.

        ``values`` maps signal paths to values (typically strings, e.g. from a
        CSV file). The data type of every path is resolved from the databroker
        and cached, then each value is coerced accordingly. Non-string values
        are returned unchanged.
        """
        data_types = await self._resolve_data_types(values.keys())
        return coercion.coerce_values(values, data_types)

    async def get(self, path_or_paths):
        self._check_connected()
        if isinstance(path_or_paths, str):
            try:
                response = await self._call(
                    "GetValue", self._build_get_value_request(path_or_paths)
                )
            except grpc.RpcError as exc:
                raise from_grpc_error(exc) from exc
            return self._parse_get_value_response(response)

        paths = list(path_or_paths)
        try:
            response = await self._call(
                "GetValues", self._build_get_values_request(paths)
            )
        except grpc.RpcError as exc:
            raise from_grpc_error(exc) from exc
        return self._parse_get_values_response(response, paths)

    async def set(
        self, values: Dict[str, Any], data_type: Optional[DataType] = None
    ) -> None:
        self._check_connected()
        updates = self._normalize_updates(values)
        if data_type is not None:
            data_types = {path: data_type for path in updates}
        else:
            data_types = await self._resolve_data_types(updates.keys())
        for path, datapoint in updates.items():
            try:
                await self._call(
                    "PublishValue",
                    self._build_publish_value_request(
                        path, datapoint, data_types[path]
                    ),
                )
            except grpc.RpcError as exc:
                raise from_grpc_error(exc) from exc

    async def actuate(
        self, values: Dict[str, Any], data_type: Optional[DataType] = None
    ) -> None:
        self._check_connected()
        updates = self._normalize_updates(values)
        if data_type is not None:
            data_types = {path: data_type for path in updates}
        else:
            data_types = await self._resolve_data_types(updates.keys())
        try:
            await self._call(
                "BatchActuate",
                self._build_batch_actuate_request(updates, data_types),
            )
        except grpc.RpcError as exc:
            raise from_grpc_error(exc) from exc

    async def subscribe(
        self, paths: Iterable[str], buffer_size: Optional[int] = None
    ) -> AsyncIterator[Dict[str, Datapoint]]:
        self._check_connected()
        request = self._build_subscribe_request(paths, buffer_size)
        stream = self._stream("Subscribe", request)
        try:
            async for response in stream:
                yield self._parse_subscribe_response(response)
        except grpc.RpcError as exc:
            raise from_grpc_error(exc) from exc
        finally:
            if hasattr(stream, "cancel"):
                stream.cancel()

    async def get_metadata(self, path: str) -> Metadata:
        self._check_connected()
        await self._resolve_data_types([path])
        metadata = self._metadata_store.get(path)
        if metadata is None:
            raise NotFound(f"Path '{path}' does not exist on the server")
        return metadata

    async def list_metadata(self, pattern: str) -> List[Metadata]:
        self._check_connected()
        root = patterns.literal_prefix(pattern)
        metadatas = await self._fetch_metadata(root)
        return sorted(
            self._filter_by_pattern(metadatas, pattern),
            key=lambda m: m.path or "",
        )

    async def expand(
        self, pattern: str, entry_type: Optional[EntryType] = None
    ) -> List[str]:
        self._check_connected()
        metadatas = await self.list_metadata(pattern)
        paths = [
            metadata.path
            for metadata in metadatas
            if entry_type is None or metadata.entry_type == entry_type
        ]
        return sorted(paths)

    async def has_signal(self, path: str) -> bool:
        self._check_connected()
        return bool(await self._existing_signals([path]))

    async def has_signals(self, paths: Iterable[str]) -> bool:
        self._check_connected()
        paths = list(paths)
        return len(await self._existing_signals(paths)) == len(paths)

    async def missing_signals(self, paths: Iterable[str]) -> set:
        self._check_connected()
        paths = list(paths)
        existing = await self._existing_signals(paths)
        return {path for path in paths if path not in existing}

    async def get_server_info(self) -> ServerInfo:
        self._check_connected()
        try:
            response = await self._call(
                "GetServerInfo", self._build_get_server_info_request()
            )
        except grpc.RpcError as exc:
            raise from_grpc_error(exc) from exc
        return self._parse_server_info(response)


class Provider(_ProviderBase):
    """Asynchronous provider backed by ``OpenProviderStream``."""

    def __init__(self, client: KuksaClient):
        super().__init__(client)
        self._stream = None
        self._actuation_queue: asyncio.Queue = asyncio.Queue()
        self._pending: Dict[str, asyncio.Event] = {}
        self._stream_error = None
        self._reader_task = None

    async def __aenter__(self) -> "Provider":
        await self._open()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Stream plumbing
    # ------------------------------------------------------------------
    async def _open(self) -> None:
        self._check_not_closed()
        if self._stream is not None:
            return
        self._stream = self._client._stub.OpenProviderStream(
            metadata=self._client._metadata_kwargs()
        )
        self._reader_task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            async for response in self._stream:
                await self._dispatch(response)
        except Exception as exc:  # noqa: BLE001
            # Cancellation (e.g. close()) is expected and not an error.
            if not (
                isinstance(exc, grpc.RpcError)
                and exc.code() == grpc.StatusCode.CANCELLED
            ):
                self._stream_error = exc
        finally:
            await self._actuation_queue.put(_STOP)
            for event in self._pending.values():
                event.set()

    async def _dispatch(self, response) -> None:
        action = response.WhichOneof("action")
        if action == "batch_actuate_stream_request":
            requests = [
                self._parse_actuation_request(actuate_request)
                for actuate_request in response.batch_actuate_stream_request.actuate_requests
            ]
            await self._actuation_queue.put(requests)
        elif action in ("provide_signal_response", "provide_actuation_response"):
            event = self._pending.get(action)
            if event is not None:
                event.set()
        elif action == "publish_values_response":
            self._handle_publish_response(response.publish_values_response)

    async def _send(self, request) -> None:
        await self._stream.write(request)

    def _raise_if_stream_error(self) -> None:
        if self._stream_error is not None:
            error = self._stream_error
            if isinstance(error, grpc.RpcError):
                raise from_grpc_error(error) from error
            raise error

    def _register(self, kind: str) -> asyncio.Event:
        event = asyncio.Event()
        self._pending[kind] = event
        return event

    async def _wait(self, kind: str, timeout: Optional[float] = None) -> None:
        event = self._pending.get(kind)
        try:
            if event is not None:
                await asyncio.wait_for(event.wait(), timeout=timeout)
        finally:
            self._pending.pop(kind, None)
        self._raise_if_stream_error()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def provide_signals(
        self, signals, timeout: Optional[float] = None
    ) -> None:
        await self._open()
        ids = await self._client._resolve_signal_ids(signals.keys())
        request = self._build_provide_signal_request(signals, ids)
        self._register("provide_signal_response")
        await self._send(request)
        await self._wait("provide_signal_response", timeout=timeout)

    async def provide_actuators(
        self, paths: Iterable[str], timeout: Optional[float] = None
    ) -> None:
        # NOTE: does not verify that each path is an actuator (see the sync
        # Provider.provide_actuators for details); callers should check
        # Metadata.entry_type if they care.
        await self._open()
        paths = list(paths)
        # Resolve ids so incoming (id-keyed) actuation requests can be mapped
        # back to their path, and so non-existent paths fail early.
        await self._client._resolve_signal_ids(paths)
        request = self._build_provide_actuation_request(paths)
        self._register("provide_actuation_response")
        await self._send(request)
        await self._wait("provide_actuation_response", timeout=timeout)

    async def publish(self, values) -> None:
        await self._open()
        ids = await self._client._resolve_signal_ids(values.keys())
        data_types = await self._client._resolve_data_types(values.keys())
        request = self._build_publish_values_request(
            values, ids, data_types, self._next_request_id()
        )
        await self._send(request)

    async def actuation_requests(self) -> AsyncIterator[Iterable[ActuationRequest]]:
        await self._open()
        while True:
            item = await self._actuation_queue.get()
            if item is _STOP:
                self._raise_if_stream_error()
                return
            yield item

    async def accept(
        self,
        actuation_request: ActuationRequest,
        ok: bool = True,
        reason: Optional[str] = None,
    ) -> None:
        self._check_not_closed()
        request = self._build_batch_actuate_stream_response(
            actuation_request.signal_id, ok, reason
        )
        await self._send(request)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._stream is not None:
            self._stream.cancel()
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._reader_task = None
