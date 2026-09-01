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
Transport-agnostic protocol logic shared by the synchronous and asynchronous
clients.

This module contains no I/O of its own. Concrete clients supply the low level
``_call`` and ``_stream`` primitives (plus ``connect``/``disconnect``);
everything else (request building, response parsing, type/id resolution, error
mapping, path expansion) lives here so it is written exactly once.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional

import grpc

from kuksa.val.v2 import types_pb2
from kuksa.val.v2 import val_pb2

from . import codec
from . import patterns
from .errors import KuksaError
from .errors import NotFound
from .errors import from_grpc_error
from .metadata import MetadataStore
from .types import DataType
from .types import Datapoint
from .types import EntryType
from .types import Metadata
from .types import ServerInfo

logger = logging.getLogger(__name__)


class _KuksaCore:
    """Shared state and protocol logic. Subclasses supply the I/O primitives."""

    def __init__(
        self,
        host: str,
        port: int,
        token: Optional[str] = None,
        root_certificates: Optional[Path] = None,
        tls_server_name: Optional[str] = None,
        ensure_startup_connection: bool = True,
    ):
        self.host = host
        self.port = port
        self.token = token
        self.root_certificates = root_certificates
        self.tls_server_name = tls_server_name
        self.ensure_startup_connection = ensure_startup_connection
        self._authorization_header = self._get_authorization_header(token)
        self._metadata_store = MetadataStore()
        self._connected = False

    # ------------------------------------------------------------------
    # Abstract I/O primitives (implemented by sync / async subclasses)
    # ------------------------------------------------------------------
    def _call(self, rpc_name: str, request, timeout: Optional[float] = None):
        raise NotImplementedError

    def _stream(self, rpc_name: str, request, timeout: Optional[float] = None):
        raise NotImplementedError

    def connect(self):
        raise NotImplementedError

    def disconnect(self):
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------
    @staticmethod
    def _get_authorization_header(token: Optional[str]) -> Optional[str]:
        if token is None:
            return None
        return "Bearer " + token

    def _metadata_kwargs(self) -> List:
        if self._authorization_header is None:
            return []
        return [("authorization", self._authorization_header)]

    def authorize(self, token: str) -> None:
        """Attach ``token`` to subsequent requests as per-call gRPC metadata."""
        self._authorization_header = self._get_authorization_header(token)

    # ------------------------------------------------------------------
    # Connection state helpers
    # ------------------------------------------------------------------
    def _check_connected(self) -> None:
        if not self._connected:
            raise KuksaError(
                "Not connected to the databroker. "
                "Use the client as a context manager or call connect() first."
            )

    def _translate_rpc_error(self, exc: grpc.RpcError) -> KuksaError:
        return from_grpc_error(exc)

    # ------------------------------------------------------------------
    # Request builders (pure)
    # ------------------------------------------------------------------
    @staticmethod
    def _build_get_value_request(path: str) -> val_pb2.GetValueRequest:
        return val_pb2.GetValueRequest(signal_id=types_pb2.SignalID(path=path))

    @staticmethod
    def _build_get_values_request(paths: Iterable[str]) -> val_pb2.GetValuesRequest:
        return val_pb2.GetValuesRequest(
            signal_ids=[types_pb2.SignalID(path=path) for path in paths]
        )

    @staticmethod
    def _build_subscribe_request(
        paths: Iterable[str], buffer_size: Optional[int] = None
    ) -> val_pb2.SubscribeRequest:
        request = val_pb2.SubscribeRequest(signal_paths=list(paths))
        if buffer_size is not None:
            request.buffer_size = buffer_size
        return request

    @staticmethod
    def _build_list_metadata_request(root: str) -> val_pb2.ListMetadataRequest:
        return val_pb2.ListMetadataRequest(root=root)

    @staticmethod
    def _build_publish_value_request(
        path: str, datapoint: Datapoint, data_type: DataType
    ) -> val_pb2.PublishValueRequest:
        return val_pb2.PublishValueRequest(
            signal_id=types_pb2.SignalID(path=path),
            data_point=codec.to_proto_datapoint(datapoint, data_type),
        )

    @staticmethod
    def _build_batch_actuate_request(
        updates: Dict[str, Datapoint], data_types: Dict[str, DataType]
    ) -> val_pb2.BatchActuateRequest:
        actuate_requests = []
        for path, datapoint in updates.items():
            actuate_requests.append(
                val_pb2.ActuateRequest(
                    signal_id=types_pb2.SignalID(path=path),
                    value=codec.to_proto_value(datapoint.value, data_types[path]),
                )
            )
        return val_pb2.BatchActuateRequest(actuate_requests=actuate_requests)

    @staticmethod
    def _build_get_server_info_request() -> val_pb2.GetServerInfoRequest:
        return val_pb2.GetServerInfoRequest()

    # ------------------------------------------------------------------
    # Response parsers (pure)
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_get_value_response(response: val_pb2.GetValueResponse) -> Datapoint:
        return codec.from_proto_datapoint(response.data_point)

    @staticmethod
    def _parse_get_values_response(
        response: val_pb2.GetValuesResponse, paths: List[str]
    ) -> Dict[str, Datapoint]:
        data_points = [codec.from_proto_datapoint(dp) for dp in response.data_points]
        return dict(zip(paths, data_points))

    @staticmethod
    def _parse_subscribe_response(
        response: val_pb2.SubscribeResponse,
    ) -> Dict[str, Datapoint]:
        return {
            path: codec.from_proto_datapoint(datapoint)
            for path, datapoint in response.entries.items()
        }

    def _parse_and_cache_list_metadata(
        self, response: val_pb2.ListMetadataResponse
    ) -> List[Metadata]:
        metadatas = [codec.from_proto_metadata(m) for m in response.metadata]
        self._metadata_store.add_many(metadatas)
        return metadatas

    @staticmethod
    def _parse_server_info(response: val_pb2.GetServerInfoResponse) -> ServerInfo:
        return ServerInfo(
            name=response.name,
            version=response.version,
            commit_hash=response.commit_hash or None,
        )

    # ------------------------------------------------------------------
    # Shared orchestration helpers (pure logic, parameterised by fetch)
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_paths(paths) -> List[str]:
        if isinstance(paths, str):
            raise TypeError("Expected a collection of paths, got a single string")
        return list(paths)

    @staticmethod
    def _is_collection(paths) -> bool:
        return isinstance(paths, (list, tuple, set, frozenset))

    def _resolve_metadata_from_fetch(
        self, path: str, fetched: Iterable[Metadata]
    ) -> Metadata:
        """Update the store from a fetch and return the metadata for ``path``."""
        for metadata in fetched:
            self._metadata_store.add(metadata)
        metadata = self._metadata_store.get(path)
        if metadata is None:
            self._metadata_store.mark_missing(path)
            raise NotFound(f"Path '{path}' does not exist on the server")
        return metadata

    @staticmethod
    def _filter_by_pattern(
        metadatas: Iterable[Metadata], pattern: str
    ) -> List[Metadata]:
        matcher = patterns.compile_pattern(pattern)
        return [m for m in metadatas if m.path is not None and matcher.matches(m.path)]

    @staticmethod
    def _expand_from_metadata(
        metadatas: Iterable[Metadata],
        pattern: str,
        entry_type: Optional[EntryType] = None,
    ) -> List[str]:
        paths = set()
        matcher = patterns.compile_pattern(pattern)
        for metadata in metadatas:
            if metadata.path is None:
                continue
            if not matcher.matches(metadata.path):
                continue
            if entry_type is not None and metadata.entry_type != entry_type:
                continue
            paths.add(metadata.path)
        return sorted(paths)
