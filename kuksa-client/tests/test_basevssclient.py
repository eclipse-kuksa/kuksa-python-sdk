# /********************************************************************************
# * Copyright (c) 2024 Contributors to the Eclipse Foundation
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

import pytest
import http
from kuksa_client.grpc import BaseVSSClient
from kuksa_client.grpc import VSSClientError
from kuksa.val.v1 import val_pb2
from kuksa.val.v1 import types_pb2


def test_response_no_error():
    """

    """
    error = types_pb2.Error(
            code=http.HTTPStatus.OK, reason='not_found', message="Does.Not.Exist not found")
    errors = (types_pb2.DataEntryError(
            path='Does.Not.Exist', error=error),)
    resp = val_pb2.GetResponse(
            error=error, errors=errors)

    base_vss_client = BaseVSSClient("hostname", 1234)

    # No exception expected on next line
    base_vss_client._raise_if_invalid(resp)


def test_response_error_404():
    """

    """
    error = types_pb2.Error(
            code=404, reason='not_found', message="Does.Not.Exist not found")
    errors = (types_pb2.DataEntryError(
            path='Does.Not.Exist', error=error),)
    resp = val_pb2.GetResponse(
            error=error, errors=errors)

    base_vss_client = BaseVSSClient("hostname", 1234)

    with pytest.raises(VSSClientError):
        base_vss_client._raise_if_invalid(resp)


def test_response_no_code():
    """
    To make sure that a proper is error is generated when code is missing in response
    """
    error = types_pb2.Error(
            reason='not_found', message="Does.Not.Exist not found")
    errors = (types_pb2.DataEntryError(
            path='Does.Not.Exist', error=error),)
    resp = val_pb2.GetResponse(
            error=error, errors=errors)

    base_vss_client = BaseVSSClient("hostname", 1234)

    with pytest.raises(VSSClientError):
        base_vss_client._raise_if_invalid(resp)


def test_response_error_in_errors():
    """
    Logic for now is that we cannot always expect that "error" gives the aggregated state.
    A command might be OK even if individual calls failed
    """

    no_error = types_pb2.Error(
            code=http.HTTPStatus.OK, reason='', message="")
    error = types_pb2.Error(
            code=404, reason='not_found', message="Does.Not.Exist not found")
    errors = (types_pb2.DataEntryError(
            path='Does.Not.Exist', error=error),)
    resp = val_pb2.GetResponse(
            error=no_error, errors=errors)

    base_vss_client = BaseVSSClient("hostname", 1234)

    with pytest.raises(VSSClientError):
        base_vss_client._raise_if_invalid(resp)


def test_response_no_code_in_error_in_errors():
    """
    To make sure that a proper is error is generated when code is missing in response
    """

    no_error = types_pb2.Error(
            code=http.HTTPStatus.OK, reason='', message="")
    error = types_pb2.Error(
            reason='not_found', message="Does.Not.Exist not found")
    errors = (types_pb2.DataEntryError(
            path='Does.Not.Exist', error=error),)
    resp = val_pb2.GetResponse(
            error=no_error, errors=errors)

    base_vss_client = BaseVSSClient("hostname", 1234)

    with pytest.raises(VSSClientError):
        base_vss_client._raise_if_invalid(resp)


def test_response_no_error_in_errors():
    """
    To make sure that a proper is error is generated when code is missing in response
    """

    no_error = types_pb2.Error(
            code=http.HTTPStatus.OK, reason='', message="")
    errors = (types_pb2.DataEntryError(
            path='Does.Not.Exist'),)  # Note no error given
    resp = val_pb2.GetResponse(
            error=no_error, errors=errors)

    base_vss_client = BaseVSSClient("hostname", 1234)

    with pytest.raises(VSSClientError):
        base_vss_client._raise_if_invalid(resp)
