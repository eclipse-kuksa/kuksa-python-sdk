########################################################################
# Copyright (c) 2022 Robert Bosch GmbH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0
########################################################################

import pathlib

import grpc.aio
import pytest
import pytest_asyncio

from kuksa.val.v1 import val_pb2_grpc as val_v1
from kuksa.val.v2 import val_pb2_grpc as val_v2

import tests


@pytest.fixture(name='resources_path', scope='function')
def resources_path_fixture():
    return pathlib.Path(tests.__path__[0]) / 'resources'


@pytest.fixture(name="val_servicer_v1", scope="function")
def val_servicer_v1_fixture(mocker):
    servicer_v1 = val_v1.VALServicer()
    mocker.patch.object(servicer_v1, "Get", spec=True)
    mocker.patch.object(servicer_v1, "Set", spec=True)
    mocker.patch.object(servicer_v1, "Subscribe", spec=True)
    mocker.patch.object(servicer_v1, "GetServerInfo", spec=True)

    return servicer_v1


@pytest.fixture(name="val_servicer_v2", scope="function")
def val_servicer_v2_fixture(mocker):
    servicer_v2 = val_v2.VALServicer()
    mocker.patch.object(servicer_v2, "PublishValue", spec=True)
    mocker.patch.object(servicer_v2, "Subscribe", spec=True)

    return servicer_v2


@pytest_asyncio.fixture(name="mocked_databroker", scope="function")
async def val_server_fixture(unused_tcp_port, val_servicer_v1, val_servicer_v2):
    server = grpc.aio.server()
    val_v1.add_VALServicer_to_server(val_servicer_v1, server)
    val_v2.add_VALServicer_to_server(val_servicer_v2, server)
    server.add_insecure_port(f"127.0.0.1:{unused_tcp_port}")
    await server.start()
    try:
        yield server
    finally:
        await server.stop(grace=2.0)


@pytest_asyncio.fixture(name="secure_mocked_databroker", scope="function")
async def secure_val_server_fixture(
    unused_tcp_port, resources_path, val_servicer_v1, val_servicer_v2
):
    server = grpc.aio.server()
    val_v1.add_VALServicer_to_server(val_servicer_v1, server)
    val_v2.add_VALServicer_to_server(val_servicer_v2, server)
    server.add_secure_port(
        f"localhost:{unused_tcp_port}",
        grpc.ssl_server_credentials(
            private_key_certificate_chain_pairs=[
                (
                    (resources_path / "test-server.key").read_bytes(),
                    (resources_path / "test-server.pem").read_bytes(),
                )
            ],
            root_certificates=(resources_path / "test-ca.pem").read_bytes(),
            require_client_auth=False,
        ),
    )
    await server.start()
    try:
        yield server
    finally:
        await server.stop(grace=2.0)
