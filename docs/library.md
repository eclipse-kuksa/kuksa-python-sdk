# Using KUKSA Python SDK as Library

The `kuksa-client` package provides two generations of APIs:

- **`kuksa_client.v2`** — the redesigned, Pythonic client for the `kuksa.val.v2`
  protocol (this document).
- **Legacy APIs** (`kuksa_client.grpc`, `kuksa_client.grpc.aio`,
  `kuksa_client.KuksaClientThread`) — frozen and deprecated, kept for backwards
  compatibility. See [the migration notes](#migrating-from-the-legacy-api).

## Install

```console
pip install kuksa-client
```

## The `kuksa_client.v2` API

The new SDK targets `kuksa.val.v2` only and comes in two flavours that mirror
each other 1:1:

- `kuksa_client.v2.KuksaClient` — synchronous
- `kuksa_client.v2.aio.KuksaClient` — asynchronous (asyncio)

The public surface is available from `kuksa_client.v2`:

```python
from kuksa_client.v2 import KuksaClient, DataType, Datapoint, Provider
```

### Quick start (synchronous)

```python
from kuksa_client.v2 import KuksaClient

with KuksaClient("127.0.0.1", 55555) as client:
    speed = client.get("Vehicle.Speed")          # -> Datapoint
    print(speed.value)

    client.set({"Vehicle.Speed": 42})            # native values, type auto-resolved

    values = client.get(["Vehicle.Speed", "Vehicle.ADAS.ABS.IsActive"])  # -> dict

    for updates in client.subscribe(["Vehicle.Speed"]):
        print(updates["Vehicle.Speed"].value)
```

The asynchronous client is identical, except methods are `await`ed and
subscriptions are `async for` loops:

```python
import asyncio
from kuksa_client.v2.aio import KuksaClient

async def main():
    async with KuksaClient("127.0.0.1", 55555) as client:
        speed = await client.get("Vehicle.Speed")
        await client.set({"Vehicle.Speed": 42})
        async for updates in client.subscribe(["Vehicle.Speed"]):
            print(updates["Vehicle.Speed"].value)

asyncio.run(main())
```

## Client reference

### Connection

```python
KuksaClient(
    host="127.0.0.1",
    port=55555,
    token=None,               # optional JWT token
    root_certificates=None,   # optional pathlib.Path to a CA for TLS
    tls_server_name=None,     # optional TLS server name override
    unix_socket=None,         # optional path to a unix domain socket (ignores host/port)
)
```

Both clients are context managers; entering them connects, exiting disconnects.
You may also call `connect()` / `disconnect()` explicitly.

To connect over a unix domain socket, pass `unix_socket`:

```python
with KuksaClient(unix_socket="/tmp/kuksa.sock") as client:
    ...
```

### Values (`get` / `set`)

- `get(path)` returns a `Datapoint`. A non-existent path raises `NotFound`;
  a path that exists but has no data yet returns `Datapoint(value=None)`.
- `get([paths...]) -> Dict[str, Datapoint]` is all-or-nothing: if any path is
  missing the whole call raises and returns nothing.
- `set(values, data_type=None)` publishes native values (or `Datapoint`s).
  Types are resolved via `ListMetadata` and cached; pass `data_type` to skip the
  lookup.
- `actuate(values, data_type=None)` sends actuator target values.

```python
from kuksa_client.v2 import KuksaClient, DataType, Datapoint

with KuksaClient("127.0.0.1", 55555) as client:
    client.set({"Vehicle.Speed": 42})                       # auto-resolve type
    client.set({"Vehicle.Speed": 42}, data_type=DataType.FLOAT)
    client.set({"Vehicle.Speed": Datapoint(42)})
    client.actuate({"Vehicle.Body.Windshield.Front.Wiping.System.TargetPosition": 45})
```

### Metadata

```python
md = client.get_metadata("Vehicle.Speed")     # -> Metadata (raises NotFound)
tree = client.list_metadata("Vehicle.Cabin")  # -> list[Metadata]
```

### Wildcards and path expansion

`get`/`set`/`subscribe` operate on exact paths only. To work with a branch use
`expand()` to obtain concrete leaf paths first:

```python
paths = client.expand("**.TyrePressure")                  # -> list[str]
sensors = client.expand("Vehicle.**", entry_type=EntryType.SENSOR)
client.subscribe(client.expand("**.TyrePressure"))
```

`*` matches exactly one path segment, `**` matches zero or more segments.

### Signal availability

```python
client.has_signal("Vehicle.Speed")                        # -> bool
client.has_signals(["Vehicle.Speed", "Vehicle.NoSuch"])   # -> bool
client.missing_signals(["Vehicle.Speed", "Vehicle.NoSuch"])  # -> set[str]
```

### Authorization and server info

```python
client.authorize(token)                 # attach token to subsequent requests
info = client.get_server_info()         # -> ServerInfo(name, version, commit_hash)
```

### Subscribing and unsubscribing

`subscribe(paths)` returns an iterator (sync) / async iterator (async). The
current value of every subscribed signal is yielded immediately, followed by
batches of updates.

To **unsubscribe**, break out of the loop (or drop the iterator); the underlying
stream is cancelled automatically.

```python
# synchronous
for updates in client.subscribe(["Vehicle.Speed"]):
    print(updates)
    if done:
        break            # unsubscribe
```

```python
# asynchronous
async for updates in client.subscribe(["Vehicle.Speed"]):
    print(updates)
    if done:
        break            # unsubscribe (or: await sub.aclose())
```

## Providers

A provider claims signals/actuators, publishes values at high frequency and
receives actuation requests:

```python
from kuksa_client.v2 import KuksaClient, DataType, Provider

with KuksaClient("127.0.0.1", 55555) as client:
    provider = Provider(client)
    provider.provide_signals({"Vehicle.Speed": None})      # path -> sample interval (ms)
    provider.publish({"Vehicle.Speed": 42.5})

    provider.provide_actuators(["Vehicle.Body.Windshield.Front.Wiping.System.TargetPosition"])
    for requests in provider.actuation_requests():
        for request in requests:
            print(f"Actuate {request.path} to {request.value}")
            provider.accept(request, ok=True)
    provider.close()
```

## Escape hatch

Power users can reach the raw `kuksa.val.v2` gRPC stub and codec:

```python
client.stub                      # the raw VALStub
from kuksa_client.v2 import codec
codec.to_proto_value(42, DataType.FLOAT)   # native -> proto
codec.from_proto_value(...)                # proto -> native
```

## Migrating from the legacy API

| Legacy (`kuksa_client.grpc`) | New (`kuksa_client.v2`) |
|------------------------------|--------------------------|
| `get_current_values([...])`  | `get([...])`             |
| `set_current_values({...})`  | `set({...})`             |
| `get_target_values([...])`   | `actuate({...})`         |
| `set_target_values({...})`   | `actuate({...})`         |
| `get_metadata([...])`        | `get_metadata(path)` / `list_metadata(pattern)` |
| `subscribe_current_values([...])` | `subscribe([...])`   |
| `updateVSSTree` / `updateMetaData` | dropped (metadata is read-only in v2) |
| `VSSClient`                  | `KuksaClient`            |

The legacy APIs remain available but emit a `DeprecationWarning`. Their
examples are kept under [`examples/legacy/`](examples/legacy/).

## Further reading

- [`architecture.md`](architecture.md) — how the `kuksa_client.v2` library is
  structured and its design patterns.
- [`Redesign.md`](../Redesign.md) — the design decisions behind the redesign.
