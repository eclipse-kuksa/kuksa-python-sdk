# Using KUKSA Python SDK as Library


## Usage

The kuksa-client package needs to be installed with `pip`. Then the package can be imported:

```python
>>> import kuksa_client
>>> kuksa_client.__version__
'<your version, e.g. 0.1.7>'
```

## Available APIs

This package holds 3 different APIs depending on your application's requirements:

- `kuksa_client.grpc.aio.VSSClient` provides an asynchronous client that only supports `grpc` to interact with `kuksa_databroker`
  ([check out examples](examples/async-grpc.md)).
- `kuksa_client.grpc.VSSClient` provides a synchronous client that only supports `grpc` to interact with `kuksa_databroker`
  ([check out examples](examples/sync-grpc.md)).
- `kuksa_client.KuksaClientThread` provides a thread-based client that supports both `ws` and `grpc` to interact with either `kuksa-val-server` or `kuksa_databroker`
  ([check out examples](examples/threaded.md)).


## TLS configuration

Clients like [KUKSA CAN Provider](https://github.com/eclipse-kuksa/kuksa-can-provider)
that use KUKSA Client library must typically set the path to the root CA certificate.
If the path is set the VSSClient will try to establish a secure connection.

```
# Shall TLS be used (default False for Databroker, True for KUKSA Server)
# tls = False
tls = True

# TLS-related settings
# Path to root CA, needed if using TLS
root_ca_path=../../kuksa.val/kuksa_certificates/CA.pem
# Server name, typically only needed if accessing server by IP address like 127.0.0.1
# and typically only if connection to KUKSA Databroker
# If using KUKSA example certificates the names "Server" or "localhost" can be used.
# tls_server_name=Server
```
