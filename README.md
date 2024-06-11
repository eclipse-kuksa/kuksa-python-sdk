# KUKSA Python SDK

![kuksa.val Logo](https://raw.githubusercontent.com/eclipse-kuksa/kuksa-python-sdk/main/docs/pictures/logo.png)

KUKSA Python Client and SDK is a part of the open source project [Eclipse KUKSA](https://www.eclipse.org/kuksa/).
More about Eclipse KUKSA can be found in the [repository](https://github.com/eclipse/kuksa.val).

## Introduction

KUKSA Python SDK provides both a command-line interface (CLI) and a standalone library to interact with either
[KUKSA Server](https://github.com/eclipse/kuksa.val/tree/master/kuksa-val-server) or
[KUKSA Databroker](https://github.com/eclipse-kuksa/kuksa-databroker).

## Building and Installing the KUKSA Python SDK

The fastest way to start using KUKSA Python SDK is to install a pre-built version from pypi.org:

```console
pip install kuksa-client
```

If you want to install from sources instead see the KUKSA Python SDK [Build documentation](https://github.com/eclipse-kuksa/kuksa-python-sdk/blob/main/docs/building.md).

## Using the Command Line Interface (CLI)

After you have installed the kuksa-client package via pip you can run the test client CLI directly by executing:

```console
kuksa-client
```

With default CLI arguments, the client will try to connect to a local Databroker, e.g. a server supporting the `kuksa.val.v1` protocol without using TLS. This is equivalent to executing

```console
kuksa-client grpc://127.0.0.1:55555
```

More details on how to use the CLI is available in the KUKSA Python SDK [CLI documentation](https://github.com/eclipse-kuksa/kuksa-python-sdk/blob/main/docs/cli.md)

## Using Docker for the CLI

The KUKSA Python SDK CLI is available as a [prebuilt docker container](https://github.com/eclipse-kuksa/kuksa-python-sdk/blob/main/docs/docker.md).

## Using KUKSA Python SDK as library

The KUKSA Python SDK provides three APIS for connecting and communicating with [KUKSA Server](https://github.com/eclipse/kuksa.val/tree/master/kuksa-val-server)
and [KUKSA Databroker](https://github.com/eclipse-kuksa/kuksa-databroker).
For more details see the KUKSA Python SDK [Library documentation](https://github.com/eclipse-kuksa/kuksa-python-sdk/blob/main/docs/library.md).

## Contributing to KUKSA Python SDK

The KUKSA project welcomes contributions.

See the KUKSA Python SDK [Contribition document](https://github.com/eclipse-kuksa/kuksa-python-sdk/blob/main/CONTRIBUTING.md) for formal requirements.

## Development and Troubleshooting

For information on tools useful for KUKSA Python SDK development environment and help on troubleshooting frequent problems please visit
the KUKSA Python SDK [development and troubleshooting documentation](https://github.com/eclipse-kuksa/kuksa-python-sdk/blob/main/docs/development_troubleshoot.md).
