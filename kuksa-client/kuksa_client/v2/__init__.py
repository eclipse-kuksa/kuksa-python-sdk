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
Public surface of the redesigned ``kuksa.val.v2`` SDK.

The synchronous client is exposed here as :class:`KuksaClient`; the async
variant lives in :mod:`kuksa_client.v2.aio`.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any
from typing import Dict
from typing import Iterable
from typing import Iterator
from typing import List
from typing import Optional

import grpc
from kuksa.val.v2 import val_pb2_grpc

from . import patterns
from . import transport
from .core import _KuksaCore
from .errors import Aborted
from .errors import AlreadyExists
from .errors import DataLoss
from .errors import InvalidArgument
from .errors import KuksaError
from .errors import KuksaStreamError
from .errors import KuksaTransportError
from .errors import NotFound
from .errors import PermissionDenied
from .errors import Unauthenticated
from .errors import Unavailable
from .errors import from_grpc_error
from .provider import Provider
from .types import DataType
from .types import Datapoint
from .types import EntryType
from .types import Metadata
from .types import ServerInfo
from .types import ValueRestriction

__all__ = [
    "KuksaClient",
    "Provider",
    "DataType",
    "EntryType",
    "Datapoint",
    "Metadata",
    "ValueRestriction",
    "ServerInfo",
    "KuksaError",
    "KuksaTransportError",
    "KuksaStreamError",
    "NotFound",
    "InvalidArgument",
    "PermissionDenied",
    "Unauthenticated",
    "Unavailable",
    "AlreadyExists",
    "Aborted",
    "DataLoss",
]


class KuksaClient(_KuksaCore):
    """Synchronous client for a ``kuksa.val.v2`` databroker."""

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
        self._exit_stack = contextlib.ExitStack()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------
    def __enter__(self) -> "KuksaClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.disconnect()

    def connect(self) -> None:
        self.disconnect()
        self._channel = self._exit_stack.enter_context(
            transport.create_sync_channel(
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

    def disconnect(self) -> None:
        self._exit_stack.close()
        self._channel = None
        self._stub = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Escape hatch: raw v2 stub
    # ------------------------------------------------------------------
    @property
    def stub(self):
        """The raw ``kuksa.val.v2.VALStub`` for power users."""
        return self._stub

    # ------------------------------------------------------------------
    # I/O primitives
    # ------------------------------------------------------------------
    def _call(self, rpc_name: str, request, timeout: Optional[float] = None):
        return getattr(self._stub, rpc_name)(
            request, timeout=timeout, metadata=self._metadata_kwargs()
        )

    def _stream(self, rpc_name: str, request, timeout: Optional[float] = None):
        return getattr(self._stub, rpc_name)(
            request, timeout=timeout, metadata=self._metadata_kwargs()
        )

    # ------------------------------------------------------------------
    # Internal metadata helpers
    # ------------------------------------------------------------------
    def _fetch_metadata(self, root: str) -> List[Metadata]:
        try:
            response = self._call(
                "ListMetadata", self._build_list_metadata_request(root)
            )
        except grpc.RpcError as exc:
            raise from_grpc_error(exc) from exc
        return self._parse_and_cache_list_metadata(response)

    def _resolve_data_types(self, paths: Iterable[str]) -> Dict[str, DataType]:
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
            self._fetch_metadata(path)
            metadata = self._metadata_store.get(path)
            if metadata is None:
                self._metadata_store.mark_missing(path)
                raise NotFound(f"Path '{path}' does not exist on the server")
            result[path] = metadata.data_type
        return result

    def _resolve_signal_ids(self, paths: Iterable[str]) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for path in paths:
            signal_id = self._metadata_store.signal_id(path)
            if signal_id is not None:
                result[path] = signal_id
                continue
            if self._metadata_store.is_missing(path):
                raise NotFound(f"Path '{path}' does not exist on the server")
            self._fetch_metadata(path)
            signal_id = self._metadata_store.signal_id(path)
            if signal_id is None:
                self._metadata_store.mark_missing(path)
                raise NotFound(f"Path '{path}' does not exist on the server")
            result[path] = signal_id
        return result

    def _existing_signals(self, paths: Iterable[str]) -> set:
        existing = set()
        for path in paths:
            if self._metadata_store.has(path):
                existing.add(path)
                continue
            if self._metadata_store.is_missing(path):
                continue
            try:
                self._fetch_metadata(path)
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

    def get(self, path_or_paths):
        """
        Get the current value of a signal, or of several signals.

        With a single path returns a :class:`Datapoint`; with a collection of
        paths returns ``Dict[str, Datapoint]``. A missing path raises
        :class:`NotFound`; a path that exists but has no data yet yields
        ``Datapoint(value=None)``.
        """
        self._check_connected()
        if isinstance(path_or_paths, str):
            try:
                response = self._call(
                    "GetValue", self._build_get_value_request(path_or_paths)
                )
            except grpc.RpcError as exc:
                raise from_grpc_error(exc) from exc
            return self._parse_get_value_response(response)

        paths = list(path_or_paths)
        try:
            response = self._call("GetValues", self._build_get_values_request(paths))
        except grpc.RpcError as exc:
            raise from_grpc_error(exc) from exc
        return self._parse_get_values_response(response, paths)

    def set(
        self,
        values: Dict[str, Any],
        data_type: Optional[DataType] = None,
    ) -> None:
        """
        Set the current value of signals.

        ``values`` maps signal paths to native Python values or
        :class:`Datapoint`. Data types are auto-resolved (and cached); pass
        ``data_type`` to bypass the lookup for every path.
        """
        self._check_connected()
        updates = self._normalize_updates(values)
        if data_type is not None:
            data_types = {path: data_type for path in updates}
        else:
            data_types = self._resolve_data_types(updates.keys())
        for path, datapoint in updates.items():
            try:
                self._call(
                    "PublishValue",
                    self._build_publish_value_request(
                        path, datapoint, data_types[path]
                    ),
                )
            except grpc.RpcError as exc:
                raise from_grpc_error(exc) from exc

    def actuate(
        self,
        values: Dict[str, Any],
        data_type: Optional[DataType] = None,
    ) -> None:
        """
        Actuate one or more actuators simultaneously (target values).
        """
        self._check_connected()
        updates = self._normalize_updates(values)
        if data_type is not None:
            data_types = {path: data_type for path in updates}
        else:
            data_types = self._resolve_data_types(updates.keys())
        try:
            self._call(
                "BatchActuate",
                self._build_batch_actuate_request(updates, data_types),
            )
        except grpc.RpcError as exc:
            raise from_grpc_error(exc) from exc

    def _subscribe_stream(self, paths: Iterable[str], buffer_size: Optional[int] = None):
        """Return the raw, cancellable ``Subscribe`` stream for ``paths``."""
        request = self._build_subscribe_request(paths, buffer_size)
        return self._stream("Subscribe", request)

    def subscribe(
        self,
        paths: Iterable[str],
        buffer_size: Optional[int] = None,
    ) -> Iterator[Dict[str, Datapoint]]:
        """
        Subscribe to updates of ``paths``.

        Yields ``Dict[str, Datapoint]`` for each batch of updates. The current
        value of every subscribed signal is yielded immediately.

        To unsubscribe, ``break`` out of the loop (or drop the generator); the
        underlying stream is cancelled automatically.
        """
        self._check_connected()
        stream = self._subscribe_stream(paths, buffer_size)
        try:
            for response in stream:
                yield self._parse_subscribe_response(response)
        except grpc.RpcError as exc:
            raise from_grpc_error(exc) from exc
        finally:
            if hasattr(stream, "cancel"):
                stream.cancel()

    def get_metadata(self, path: str) -> Metadata:
        """Return the metadata of a single signal."""
        self._check_connected()
        self._resolve_data_types([path])
        metadata = self._metadata_store.get(path)
        if metadata is None:
            raise NotFound(f"Path '{path}' does not exist on the server")
        return metadata

    def list_metadata(self, pattern: str) -> List[Metadata]:
        """
        Return metadata for signals matching ``pattern`` (exact path or
        wildcard), sorted by path.
        """
        self._check_connected()
        root = patterns.literal_prefix(pattern)
        metadatas = self._fetch_metadata(root)
        return sorted(
            self._filter_by_pattern(metadatas, pattern),
            key=lambda m: m.path or "",
        )

    def expand(
        self, pattern: str, entry_type: Optional[EntryType] = None
    ) -> List[str]:
        """
        Return the concrete leaf signal paths matching ``pattern``.

        Optionally filter by :class:`EntryType` (SENSOR / ACTUATOR / ATTRIBUTE).
        """
        self._check_connected()
        metadatas = self.list_metadata(pattern)
        paths = [
            metadata.path
            for metadata in metadatas
            if entry_type is None or metadata.entry_type == entry_type
        ]
        return sorted(paths)

    def has_signal(self, path: str) -> bool:
        """Return whether ``path`` is a signal known to the databroker."""
        self._check_connected()
        return bool(self._existing_signals([path]))

    def has_signals(self, paths: Iterable[str]) -> bool:
        """Return whether all given ``paths`` exist."""
        self._check_connected()
        paths = list(paths)
        return len(self._existing_signals(paths)) == len(paths)

    def missing_signals(self, paths: Iterable[str]) -> set:
        """Return the subset of ``paths`` that do not exist."""
        self._check_connected()
        paths = list(paths)
        existing = self._existing_signals(paths)
        return {path for path in paths if path not in existing}

    def get_server_info(self) -> ServerInfo:
        """Return databroker name / version / commit hash."""
        self._check_connected()
        try:
            response = self._call(
                "GetServerInfo", self._build_get_server_info_request()
            )
        except grpc.RpcError as exc:
            raise from_grpc_error(exc) from exc
        return self._parse_server_info(response)
