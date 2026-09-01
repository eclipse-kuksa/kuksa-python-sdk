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
Connection / TLS / auth helpers shared by the synchronous and asynchronous
clients.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import grpc


def _build_credentials(root_certificates: Optional[Path]):
    if root_certificates is None:
        return None
    return grpc.ssl_channel_credentials(root_certificates.read_bytes())


def _channel_options(tls_server_name: Optional[str]):
    if tls_server_name:
        return [("grpc.ssl_target_name_override", tls_server_name)]
    return None


def create_sync_channel(
    host: str,
    port: int,
    root_certificates: Optional[Path] = None,
    tls_server_name: Optional[str] = None,
) -> grpc.Channel:
    target = f"{host}:{port}"
    credentials = _build_credentials(root_certificates)
    if credentials is not None:
        return grpc.secure_channel(target, credentials, _channel_options(tls_server_name))
    return grpc.insecure_channel(target)


def create_aio_channel(
    host: str,
    port: int,
    root_certificates: Optional[Path] = None,
    tls_server_name: Optional[str] = None,
) -> grpc.aio.Channel:
    target = f"{host}:{port}"
    credentials = _build_credentials(root_certificates)
    if credentials is not None:
        return grpc.aio.secure_channel(
            target, credentials, _channel_options(tls_server_name)
        )
    return grpc.aio.insecure_channel(target)
