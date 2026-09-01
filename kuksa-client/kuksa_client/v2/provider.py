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
Provider support, backed by the bidirectional ``OpenProviderStream`` RPC.

A provider claims ownership of signals/actuators, publishes values at high
frequency, and receives actuation requests.
"""

from __future__ import annotations

import dataclasses
import logging
import queue
import threading
from typing import Any
from typing import Dict
from typing import Iterable
from typing import Iterator
from typing import Mapping
from typing import Optional

import grpc

from kuksa.val.v2 import types_pb2
from kuksa.val.v2 import val_pb2

from . import codec
from .errors import KuksaStreamError
from .errors import from_grpc_error
from .types import Datapoint

logger = logging.getLogger(__name__)

_STOP = object()


@dataclasses.dataclass
class ActuationRequest:
    """A single actuation request received from the databroker."""

    path: str
    value: Any
    provider: "Provider"
    signal_id: types_pb2.SignalID


class _ProviderBase:
    """Shared provider protocol logic (message building, id/type resolution)."""

    def __init__(self, client):
        self._client = client
        self._request_id = 0
        self._closed = False

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _check_not_closed(self) -> None:
        if self._closed:
            raise KuksaStreamError("Provider is closed")

    def _path_from_signal_id(self, signal_id: types_pb2.SignalID) -> str:
        if signal_id.HasField("path"):
            return signal_id.path
        if signal_id.HasField("id"):
            path = self._client._metadata_store.path_for_id(signal_id.id)
            if path is not None:
                return path
        return "<unknown>"

    # ------------------------------------------------------------------
    # Request builders (pure)
    # ------------------------------------------------------------------
    def _build_provide_signal_request(
        self, signals: Mapping[str, Optional[int]], ids: Mapping[str, int]
    ) -> val_pb2.OpenProviderStreamRequest:
        signals_sample_intervals: Dict[int, types_pb2.SampleInterval] = {}
        for path, interval in signals.items():
            sample_interval = types_pb2.SampleInterval()
            if interval is not None:
                sample_interval.interval_ms = interval
            signals_sample_intervals[ids[path]] = sample_interval
        return val_pb2.OpenProviderStreamRequest(
            provide_signal_request=val_pb2.ProvideSignalRequest(
                signals_sample_intervals=signals_sample_intervals
            )
        )

    def _build_provide_actuation_request(
        self, paths: Iterable[str]
    ) -> val_pb2.OpenProviderStreamRequest:
        return val_pb2.OpenProviderStreamRequest(
            provide_actuation_request=val_pb2.ProvideActuationRequest(
                actuator_identifiers=[
                    types_pb2.SignalID(path=path) for path in paths
                ]
            )
        )

    def _build_publish_values_request(
        self,
        values: Mapping[str, Any],
        ids: Mapping[str, int],
        data_types: Mapping[str, Any],
        request_id: int,
    ) -> val_pb2.OpenProviderStreamRequest:
        data_points: Dict[int, types_pb2.Datapoint] = {}
        for path, value in values.items():
            datapoint = value if isinstance(value, Datapoint) else Datapoint(value=value)
            data_points[ids[path]] = codec.to_proto_datapoint(
                datapoint, data_types[path]
            )
        return val_pb2.OpenProviderStreamRequest(
            publish_values_request=val_pb2.PublishValuesRequest(
                request_id=request_id, data_points=data_points
            )
        )

    def _build_batch_actuate_stream_response(
        self, signal_id: types_pb2.SignalID, ok: bool, reason: Optional[str]
    ) -> val_pb2.OpenProviderStreamRequest:
        error = types_pb2.Error()
        if ok:
            error.code = types_pb2.ERROR_CODE_OK
        else:
            error.code = types_pb2.ERROR_CODE_INVALID_ARGUMENT
            if reason:
                error.message = reason
        return val_pb2.OpenProviderStreamRequest(
            batch_actuate_stream_response=val_pb2.BatchActuateStreamResponse(
                signal_id=signal_id, error=error
            )
        )

    def _parse_actuation_request(
        self, actuate_request: val_pb2.ActuateRequest
    ) -> ActuationRequest:
        return ActuationRequest(
            path=self._path_from_signal_id(actuate_request.signal_id),
            value=codec.from_proto_value(actuate_request.value),
            provider=self,
            signal_id=actuate_request.signal_id,
        )

    def _handle_publish_response(
        self, response: val_pb2.PublishValuesResponse
    ) -> None:
        for signal_id, error in response.status.items():
            logger.warning(
                "Publish error for signal id %s: %s (%s)",
                signal_id,
                error.message,
                types_pb2.ErrorCode.Name(error.code),
            )


class Provider(_ProviderBase):
    """Synchronous provider backed by ``OpenProviderStream``."""

    def __init__(self, client):
        super().__init__(client)
        self._send_queue: queue.Queue = queue.Queue()
        self._actuation_queue: queue.Queue = queue.Queue()
        self._reader_thread = None
        self._pending: Dict[str, threading.Event] = {}
        self._stream_error = None

    def __enter__(self) -> "Provider":
        self._open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Stream plumbing
    # ------------------------------------------------------------------
    def _open(self) -> None:
        self._check_not_closed()
        if self._reader_thread is not None:
            return
        self._reader_thread = threading.Thread(
            target=self._run, name="kuksa-provider", daemon=True
        )
        self._reader_thread.start()

    def _request_iterator(self) -> Iterator[val_pb2.OpenProviderStreamRequest]:
        while True:
            item = self._send_queue.get()
            if item is _STOP:
                return
            yield item

    def _run(self) -> None:
        try:
            responses = self._client._stub.OpenProviderStream(
                self._request_iterator(),
                metadata=self._client._metadata_kwargs(),
            )
            for response in responses:
                self._dispatch(response)
        except Exception as exc:  # noqa: BLE001
            self._stream_error = exc
        finally:
            self._actuation_queue.put(_STOP)
            for event in self._pending.values():
                event.set()

    def _dispatch(self, response: val_pb2.OpenProviderStreamResponse) -> None:
        action = response.WhichOneof("action")
        if action == "batch_actuate_stream_request":
            requests = [
                self._parse_actuation_request(actuate_request)
                for actuate_request in response.batch_actuate_stream_request.actuate_requests
            ]
            self._actuation_queue.put(requests)
        elif action in ("provide_signal_response", "provide_actuation_response"):
            event = self._pending.get(action)
            if event is not None:
                event.set()
        elif action == "publish_values_response":
            self._handle_publish_response(response.publish_values_response)
        else:
            logger.warning("Unhandled provider stream response: %s", action)

    def _send(self, request: val_pb2.OpenProviderStreamRequest) -> None:
        self._send_queue.put(request)

    def _raise_if_stream_error(self) -> None:
        if self._stream_error is not None:
            error = self._stream_error
            if isinstance(error, grpc.RpcError):
                raise from_grpc_error(error) from error
            raise KuksaStreamError(str(error)) from error

    def _register(self, kind: str) -> threading.Event:
        event = threading.Event()
        self._pending[kind] = event
        return event

    def _wait(self, kind: str, timeout: Optional[float] = None) -> None:
        event = self._pending.get(kind)
        try:
            if event is not None:
                event.wait(timeout=timeout)
        finally:
            self._pending.pop(kind, None)
        self._raise_if_stream_error()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def provide_signals(
        self, signals: Mapping[str, Optional[int]], timeout: Optional[float] = None
    ) -> None:
        """
        Claim ownership of ``signals`` (path -> sample interval in ms, or None).
        """
        self._open()
        ids = self._client._resolve_signal_ids(signals.keys())
        request = self._build_provide_signal_request(signals, ids)
        self._register("provide_signal_response")
        self._send(request)
        self._wait("provide_signal_response", timeout=timeout)

    def provide_actuators(
        self, paths: Iterable[str], timeout: Optional[float] = None
    ) -> None:
        """Claim ownership of the actuators identified by ``paths``."""
        self._open()
        request = self._build_provide_actuation_request(paths)
        self._register("provide_actuation_response")
        self._send(request)
        self._wait("provide_actuation_response", timeout=timeout)

    def publish(self, values: Mapping[str, Any]) -> None:
        """Publish values (high-frequency path)."""
        self._open()
        ids = self._client._resolve_signal_ids(values.keys())
        data_types = self._client._resolve_data_types(values.keys())
        request = self._build_publish_values_request(
            values, ids, data_types, self._next_request_id()
        )
        self._send(request)

    def actuation_requests(self) -> Iterator[Iterable[ActuationRequest]]:
        """Iterate over incoming actuation request batches."""
        self._open()
        while True:
            item = self._actuation_queue.get()
            if item is _STOP:
                self._raise_if_stream_error()
                return
            yield item

    def accept(
        self,
        actuation_request: ActuationRequest,
        ok: bool = True,
        reason: Optional[str] = None,
    ) -> None:
        """Acknowledge (or reject) a received actuation request."""
        self._check_not_closed()
        request = self._build_batch_actuate_stream_response(
            actuation_request.signal_id, ok, reason
        )
        self._send(request)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._send_queue.put(_STOP)
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=5)
            self._reader_thread = None


__all__ = ["Provider", "ActuationRequest"]
