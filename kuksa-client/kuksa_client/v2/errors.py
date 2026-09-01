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
Error hierarchy for the v2 SDK.

Transport/gRPC errors (unary RPC status codes) are distinct from
application/stream errors (in-stream ``Error`` / ``ErrorCode`` messages and
``ProviderErrorIndication`` on the provider stream).
"""

from __future__ import annotations

import grpc
from kuksa.val.v2 import types_pb2


class KuksaError(Exception):
    """Base class for all SDK errors."""

    def __init__(self, message=None, *, code=None):
        super().__init__(message)
        self.message = message
        self.code = code

    def __str__(self):
        return str(self.message)


class KuksaTransportError(KuksaError):
    """A gRPC/transport level error (e.g. an unexpected status code)."""


class NotFound(KuksaError):
    """A requested signal/actuator does not exist."""


class InvalidArgument(KuksaError):
    """The request was invalid (bad path, wrong data type, out of range)."""


class PermissionDenied(KuksaError):
    """Access was denied."""


class Unauthenticated(KuksaError):
    """No credentials were provided or they have expired."""


class Unavailable(KuksaError):
    """The service (or provider) is currently unavailable."""


class AlreadyExists(KuksaError):
    """A provider already claimed ownership of a signal/actuator."""


class Aborted(KuksaError):
    """A provider has not claimed the signals it tried to publish."""


class DataLoss(KuksaError):
    """An internal transmission failure occurred."""


class KuksaStreamError(KuksaError):
    """An application/stream level error (in-stream error message)."""


_GRPC_ERROR_TYPES = {
    grpc.StatusCode.NOT_FOUND: NotFound,
    grpc.StatusCode.INVALID_ARGUMENT: InvalidArgument,
    grpc.StatusCode.PERMISSION_DENIED: PermissionDenied,
    grpc.StatusCode.UNAUTHENTICATED: Unauthenticated,
    grpc.StatusCode.UNAVAILABLE: Unavailable,
    grpc.StatusCode.ALREADY_EXISTS: AlreadyExists,
    grpc.StatusCode.ABORTED: Aborted,
    grpc.StatusCode.DATA_LOSS: DataLoss,
}

_ERROR_CODE_TYPES = {
    types_pb2.ERROR_CODE_INVALID_ARGUMENT: InvalidArgument,
    types_pb2.ERROR_CODE_NOT_FOUND: NotFound,
    types_pb2.ERROR_CODE_PERMISSION_DENIED: PermissionDenied,
}


def from_grpc_error(exc: grpc.RpcError) -> KuksaError:
    """Map a gRPC ``RpcError`` to the appropriate :class:`KuksaError`."""
    code = exc.code()
    error_type = _GRPC_ERROR_TYPES.get(code, KuksaTransportError)
    return error_type(exc.details(), code=code)


def from_error_message(error: types_pb2.Error) -> KuksaError:
    """Map an in-stream v2 ``Error`` message to a :class:`KuksaError`."""
    error_type = _ERROR_CODE_TYPES.get(error.code, KuksaStreamError)
    return error_type(error.message, code=error.code)


__all__ = [
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
    "from_grpc_error",
    "from_error_message",
]
