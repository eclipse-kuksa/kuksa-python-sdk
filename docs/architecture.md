# Architecture of the `kuksa_client.v2` library

This document describes how the redesigned `kuksa_client.v2` package is
structured and the patterns it follows. It is intended as a starting point for
anyone extending or understanding the implementation. It deliberately does **not**
cover the CLI (`kuksa_client.__main__`), which is a consumer of this library.

See also the design rationale in [`Redesign.md`](../Redesign.md) and the
user-facing [`library.md`](library.md).

## Goals in one paragraph

The v2 SDK talks to a **`kuksa.val.v2`** databroker only. It exposes two
first-class clients — synchronous (`kuksa_client.v2.KuksaClient`) and
asynchronous (`kuksa_client.v2.aio.KuksaClient`) — with the same API, plus a
`Provider` for claiming/publishing/actuating signals. The currency of the API is
native Python values. Every power-user need that is not covered by the typed API
is reachable through a raw-proto "escape hatch".

## Module map

| Module | Responsibility |
|--------|----------------|
| `types.py` | Pure dataclasses/enums (`Datapoint`, `Metadata`, `DataType`, `EntryType`, `ServerInfo`, …). No proto imports. |
| `codec.py` | The single source of truth for `native value ↔ kuksa.val.v2 Value/Datapoint` encoding. |
| `patterns.py` | Client-side wildcard matching (databroker semantics pinned locally). |
| `metadata.py` | `MetadataStore`: an in-memory, per-connection metadata/id cache. |
| `errors.py` | `KuksaError` hierarchy + mappers from gRPC status codes and v2 `ErrorCode`s. |
| `transport.py` | Channel + TLS construction helpers for sync and aio (TCP or unix socket). |
| `core.py` | `_KuksaCore`: transport-agnostic shared state and protocol logic. |
| `__init__.py` | The synchronous `KuksaClient`. |
| `aio.py` | The asynchronous `KuksaClient` and asynchronous `Provider`. |
| `provider.py` | `Provider` (shared base + sync implementation) and `ActuationRequest`. |

Dependency direction is one-way: `types`/`errors` are leaf modules; `codec`,
`patterns`, `metadata`, `transport` depend only on them; `core` composes those;
`__init__`/`aio`/`provider` sit on top.

## Core design: shared core + thin I/O

The central pattern is a **transport-agnostic core** (`_KuksaCore` in `core.py`)
plus two **thin I/O backends** (sync in `__init__.py`, async in `aio.py`).

`_KuksaCore` owns everything that is *not* I/O:

- connection parameters, the `authorization` header, and the `MetadataStore`;
- **request builders** (`_build_get_value_request`, `_build_subscribe_request`, …);
- **response parsers** (`_parse_get_value_response`, `_parse_subscribe_response`, …);
- pure helpers for path expansion, error translation, and connection checks.

The concrete clients are expected to implement only a handful of primitives:

```python
class _KuksaCore:
    def _call(self, rpc_name, request, timeout=None): ...      # unary
    def _stream(self, rpc_name, request, timeout=None): ...    # server-streaming
    def connect(self): ...
    def disconnect(self): ...
```

The sync client implements these against `grpc` + the generated `VALStub`; the
async client implements them against `grpc.aio` + the same `VALStub`.

### Why the public method bodies are thin twins

gRPC ships distinct synchronous and asynchronous stubs, and Python cannot share
an `await`/`async for` with a plain `for`/return without introducing a background
event loop. To keep both clients genuinely native, the public methods (`get`,
`set`, `subscribe`, `actuate`, `get_metadata`, …) exist in both clients and are
small, differing only in `await`/`async for`. All the *protocol* logic they need
— building requests, parsing responses, resolving data types, mapping errors —
lives once in `core.py` / `codec.py` / `metadata.py`.

For example, `subscribe` is written once per client as:

```python
# sync
def subscribe(self, paths, buffer_size=None):
    stream = self._subscribe_stream(paths, buffer_size)
    try:
        for response in stream:
            yield self._parse_subscribe_response(response)
    except grpc.RpcError as exc:
        raise from_grpc_error(exc) from exc
    finally:
        stream.cancel()
```

```python
# async
async def subscribe(self, paths, buffer_size=None):
    stream = self._stream("Subscribe", self._build_subscribe_request(paths, buffer_size))
    try:
        async for response in stream:
            yield self._parse_subscribe_response(response)
    except grpc.RpcError as exc:
        raise from_grpc_error(exc) from exc
    finally:
        stream.cancel()
```

`_parse_subscribe_response` and `_build_subscribe_request` are shared (in
`core.py`); only the loop and `await` differ. The `finally: stream.cancel()`
makes "unsubscribing" (breaking out of the loop) cancel the underlying gRPC call
cleanly.

## Value encoding (`codec.py`)

`codec.py` holds the single mapping `DataType → (proto Value field, Python type)`
(see `_FIELD_MAP`). Everything that turns native values into `kuksa.val.v2.Value`
or `Datapoint` (and back) goes through it.

Notable points:

- protobuf has no `int8`/`int16`/`uint8`/`uint16`, so those `DataType`s alias to
  `int32`/`uint32` fields — this aliasing is encoded in the map, not scattered.
- `TIMESTAMP`/`TIMESTAMP_ARRAY` are intentionally absent (the v2 `Value` oneof
  has no timestamp field).
- No string casting happens here — values are expected to be native Python values
  of the right type. (The CLI does its own coercion.)
- `to_proto_value` / `from_proto_value` are the public escape hatch for raw
  value encoding.

Adding a new data type is a one-line change to `_FIELD_MAP`.

## Metadata caching (`metadata.py`)

`MetadataStore` is an in-memory cache bound to a connection, mapping a signal
path to its `Metadata` (which carries `id`, `data_type`, `entry_type`, etc.). It
caches both positively (known signals) and negatively (paths known not to exist)
and is cleared on reconnect.

There is deliberately **no TTL**: VSS metadata is assumed static while a system
runs. This is what makes `set`/`actuate` without an explicit data type a cached
lookup rather than a round-trip, and it also warms the `id ↔ path` mapping that
the `Provider` relies on.

## Client-side wildcard matching (`patterns.py`)

`get`/`set`/`subscribe` operate on exact paths. Wildcards are handled entirely
client-side, pinning the databroker's `wildcard_matching.md` semantics so the
client never depends on server-side matching:

- `*` matches exactly one segment, `**` zero-or-more segments, both valid anywhere;
- a plain branch path matches the branch and everything below it;
- `**` combined with consecutive `*` segments is unsupported (raises `ValueError`).

`literal_prefix(pattern)` returns the longest literal prefix, which is used to
bound a `ListMetadata(root=<prefix>)` call; `*` is never sent to the broker.
`expand(pattern, entry_type=...)` and `list_metadata(pattern)` fetch the bounded
subtree once and then match client-side via `patterns.compile_pattern`.

## Error hierarchy (`errors.py`)

Two kinds of failures are modelled:

- **transport/gRPC errors** — unary/stream RPC status codes — mapped by
  `from_grpc_error(exc)` to subclasses such as `NotFound`, `PermissionDenied`,
  `Unauthenticated`, `Unavailable`, `AlreadyExists`, `Aborted`, `DataLoss`, plus
  the generic `KuksaTransportError`.
- **application/stream errors** — in-stream v2 `Error` messages and provider
  errors — mapped by `from_error_message(error)` to `KuksaStreamError` and
  friends.

All exceptions derive from `KuksaError`, so `except KuksaError` catches
everything the SDK raises.

## Providers (`provider.py`)

A `Provider` is backed by the bidirectional `OpenProviderStream` RPC. The
message types are id-keyed (`ProvideSignalRequest` = `map<int32, SampleInterval>`,
`PublishValuesRequest` = `map<int32, Datapoint>`), so the provider depends on the
`MetadataStore` id↔path mapping (populated via `ListMetadata`).

Shared protocol logic lives in `_ProviderBase` (request building, id/type
resolution, request_id generation, actuation-request parsing). The two concrete
implementations differ only in stream plumbing:

- **sync** (`provider.py`): a reader thread iterates the stream and dispatches
  responses; requests are sent through a `queue.Queue`; `close()` cancels the
  underlying stream so the databroker releases the provider's claims.
- **async** (`aio.py`): an asyncio task reads the stream into an
  `asyncio.Queue`; `await _send()` writes; `close()` cancels the stream and the
  reader task.

A connection drop terminates the stream, so provider iteration ends/raises rather
than hanging; re-registration after a reconnect is the caller's explicit action.

## Authentication

`authorize(token)` just stores an `authorization: Bearer <token>` header that is
attached as per-call gRPC metadata on every subsequent RPC. The old v1
`GetServerInfo` pseudo-auth round-trip is not carried over.

## Escape hatch

For features the typed API does not expose:

- `client.stub` — the raw generated `kuksa.val.v2.VALStub`;
- `codec.to_proto_value` / `codec.from_proto_value` — raw value encoding.

## How to extend

- **Add a unary RPC**: add `_build_*` / `_parse_*` helpers to `core.py`, then a
  thin public method to both `__init__.py` (sync) and `aio.py` (async) that
  calls `self._call(...)` and the parser.
- **Add a streaming RPC**: same, but use `self._stream(...)` and mirror the
  `for`/`async for` + `finally: stream.cancel()` shape of `subscribe`.
- **Add a provider feature**: add the message builder to `_ProviderBase` and the
  response handling to the sync `_dispatch` and async `_dispatch`.
- **Add a data type**: add one row to `codec._FIELD_MAP`.

## References

- [`Redesign.md`](../Redesign.md) — the design decisions and rationale.
- [`library.md`](library.md) — the public API documentation.
- [`examples/`](examples/) — synchronous, asynchronous, and provider examples.
