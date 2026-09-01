# API / SDK Redesign

## Context & constraints
- PyPI distribution stays **`kuksa-client`**, top-level package stays **`kuksa_client`** — existing users must be unaffected.
- The redesigned SDK is added **in this repo**, in a new subpackage **`kuksa_client.v2`** (no name clash with today's `kuksa_client.grpc` / `kuksa_client.ws` / proto package `kuksa.val.v2`).
- Both old and new ship in the same wheel (one release train); the old API is frozen + deprecated.

## Current issues (from codebase)
1. Dual-stack complexity: `kuksa_client/grpc/__init__.py` (1592 LOC) and `grpc/aio.py` interleave kuksa.val.v1/v2 — `try_v2` flags, `UNIMPLEMENTED` fallbacks, `EntryUpdate.from_tuple` vs `from_message`, `ListMetadata` branch-expansion, `ensure_id_mapping`.
2. Value encoding duplicated: `v1_to_message`/`v2_to_message` are near-identical `DataType → proto field` dicts; string-casting magic (`cast_array_values`, `cast_bool`, `cast_str`) is CLI logic living in the library.
3. Return shapes drift by call path: simplified API returns `Dict[str, Datapoint]`, full API `List[DataEntry]`, CLI re-serializes via `DatabrokerEncoder` isinstance-chain.
4. Redundant object model: `Metadata`/`Datapoint`/`DataEntry`/`EntryRequest`/`EntryUpdate`/`SubscribeEntry`/`Field`/`View`/`MetadataField` re-implement proto messages with `from_message`/`to_message`/`to_dict` everywhere.
5. No first-class provider API: `OpenProviderStream` used internally only to receive actuate requests; signal publishing not exposed.
6. CLI/threading complexity: `KuksaClientThread` + `cli_backend` with message queues, JSON-string responses, ws/VISS + gRPC backends, camelCase + snake_case APIs mixed.
7. Build complexity: proto generation in `setup.py` custom commands + git submodule.

## Goals
- Support **kuksa.val.v2 only** — no protocol abstractions.
- Support **providers** (OpenProviderStream: provide signals/actuators, publish, actuation).
- "Reasonably fast": native-value sets with cached type lookup; high-frequency via provider stream.
- Pythonic; typed signatures with native Python values.
- Not exposing every gRPC feature is acceptable — but keep a clean **escape hatch** to raw proto.
- Backwards compatible: old code kept for a while; class rename `VSSClient → KuksaClient`.
- Keep the CLI, rebuilt on the new client.

## Decisions (confirmed)
- **Namespace:** new SDK at `kuksa_client.v2` in the same distribution.
- **Sync/async:** shared core — both first-class; protocol logic once, I/O per-client.
- **Granularity:** clean core + escape hatch (raw proto access for power users/providers).

## Target module layout (`kuksa_client/v2/`)
```
__init__.py    # public surface: KuksaClient, DataType, Datapoint, Metadata, Provider, errors
aio.py         # async KuksaClient
core.py        # shared protocol logic (get/set/subscribe/actuate/metadata) using injected _call/_stream
transport.py   # connection/TLS/auth; blocking + aio stubs, abstract call/stream interface
types.py       # Datapoint(value, timestamp), Metadata, DataType, ValueRestriction (pure, no proto leakage)
codec.py       # single source of truth: python value <-> proto Value/Datapoint
metadata.py    # MetadataStore: cached metadata (id, data_type, entry_type) + type lookups, invalidation
patterns.py    # wildcard pattern matching (compile pattern -> segment matcher), client-side
provider.py    # Provider on OpenProviderStream
errors.py      # KuksaError hierarchy (transport/gRPC vs stream/application errors)
```

## API surface
```python
from kuksa_client.v2 import KuksaClient, DataType, Datapoint, Provider

with KuksaClient("127.0.0.1", 55555) as client:
    dp = client.get("Vehicle.Speed")                        # Datapoint (raises NotFound if path doesn't exist)
    values = client.get(["Vehicle.Speed", "Vehicle.ADAS.ABS.IsActive"])  # Dict[str, Datapoint]
    client.set({"Vehicle.Speed": 42})                       # native values; type auto-resolved + cached
    client.set({"Vehicle.Speed": Datapoint(42, ts)})
    client.set({"Vehicle.Speed": 42}, data_type=DataType.FLOAT)  # explicit type = no lookup
    for updates in client.subscribe(["Vehicle.Speed"]):     # Iterator[Dict[str, Datapoint]]
        ...
    client.actuate({"Vehicle.Body.Wiper.Pos": 45})          # target values
    md = client.get_metadata("Vehicle.Speed")               # Metadata
    tree = client.list_metadata("Vehicle")
    has = client.has_signal("Vehicle.Speed")                # bool
    missing = client.missing_signals(["Vehicle.Speed", "Vehicle.NoSuch"])  # set[str]
    client.authorize(token)
    info = client.get_server_info()

provider = Provider(client)
provider.provide_signals({"Vehicle.Speed": DataType.FLOAT}) # claim signals
provider.publish({"Vehicle.Speed": 42.5})                   # publish values (stream, high-frequency path)
provider.provide_actuators(["Vehicle.Body.Wiper.Pos"])      # claim actuators
for req in provider.actuation_requests():                   # receive actuation requests
    provider.accept(req, ok=True, reason=None)
```
Async mirrors this 1:1 with `await`/`async for` from `kuksa_client.v2.aio`.

**Escape hatch:** `codec` exposes `to_proto_value`/`from_proto_value`, `client.raw_*` (or the stub) for raw v2 messages — providers and power users are not blocked.

### get / set semantics
- `get(path)` returns a `Datapoint`. A **non-existent** VSS path raises `NotFound`; a path that exists but has no data yet returns `Datapoint(value=None)`. The two cases must be distinguishable — never collapse "missing" into `None`.
- `get([paths...]) -> Dict[str, Datapoint]` is **all-or-nothing**: if any requested path does not exist, the whole call raises and returns nothing. Paths that exist but have no data are fine and yield `Datapoint(value=None)`. (This maps 1:1 onto the v2 `GetValues` RPC: `NOT_FOUND` if any signal is missing, otherwise positional `data_points` are zipped back with the request order.)
- `set` auto-resolves types via `MetadataStore` (one cached lookup); a batch resolves all paths with a single `ListMetadata` first.

### Path handling — no magical wildcards
- `get`, `set`, `subscribe` operate on **exact VSS paths only**. No silent `ListMetadata` expansion of branches or `.*` (unlike today's `subscribe_current_values`, which auto-expands/falls back).
- "Everything under a branch" is done via an **explicit helper** that returns concrete leaf paths, which the user then feeds to `get`/`subscribe`. The expansion is a named operation — never hidden inside another call.

### Wildcard / path expansion
- **Grammar:** reuse the databroker `wildcard_matching.md` semantics — `*` matches exactly one path segment, `**` matches zero-or-more segments, both valid anywhere in the path; a plain branch path matches the branch and everything below; the `**` combined with consecutive `*` segments exception carries over.
- **`patterns.py`** implements the matcher **client-side** (compile pattern → segment matcher), pinning the semantics and making it unit-testable and independent of any future server-side changes.
- **Never send `*` to the databroker:** all heavy lifting happens client-side. `expand`/`list_metadata` always call `ListMetadata(root=<literal prefix>)`, where the prefix is everything *before the first wildcard*, and match the remainder in `patterns.py`. A pattern starting with a wildcard (`**.TyrePressure`) has an empty prefix and therefore triggers a full-tree `ListMetadata(root="")` — acceptable, but documented/commented as such.
- **`expand(pattern, entry_type=None) -> list[str]`** — the single bridge into `get`/`subscribe`. Fetches `ListMetadata(root=<literal prefix>)` to bound the data, matches client-side, optionally filters by `EntryType` (SENSOR / ACTUATOR / ATTRIBUTE), and returns sorted concrete leaf paths. Covers both "give me a list of paths to analyse" and "all sensors/actuators/leaves under X" (e.g. `expand("**.TyrePressure", entry_type=EntryType.SENSOR)`).
- **`list_metadata(pattern) -> list[Metadata]`** (already planned) accepts the same patterns and returns entries *with* metadata (each `Metadata` carries its `.path`) for further analysis; `expand` is `list_metadata` + path extraction + optional type filter.
- Example flow: `client.subscribe(client.expand("**.TyrePressure"))`.

### Metadata is read-only
- `kuksa.val.v2` has **no metadata write path** (no `Set`/`UpdateMetadata` RPC) — metadata can only be *read* via `ListMetadata`. Consequently `get_metadata`/`list_metadata` exist in v2, but `set_metadata`, `updateVSSTree`, and `updateMetaData` have no v2 equivalent and are **dropped** (see migration table).

### Signal availability checks
- An app often depends on a set of VSS signals but cannot know whether a given car/databroker supports them, so the client offers explicit existence checks:
  - `has_signal(path) -> bool`
  - `has_signals(paths) -> bool` — `True` if all given paths exist
  - `missing_signals(paths) -> set[str]` — cheap companion; apps usually need to know *which* ones are missing to log/adapt (existence check is one batched `ListMetadata` call, so this comes for free)
- **Semantics:** existence in the VSS tree known to the broker (`ListMetadata`; `NOT_FOUND` → `False`), *not* "currently provided by a provider" (that is dynamic and out of scope for v1).
- **Tie-in with `MetadataStore`:** consults the cache first; on miss does one `ListMetadata` per batch and caches **positively and negatively** (absent paths), invalidated on reconnect like the rest of the store. Bonus: `ListMetadata` returns full metadata incl. `id`, `data_type`, and `entry_type`, so a `has_signals()` check also warms the type/id cache and makes subsequent `set()`/provider calls lookup-free.
- Exact paths only (see path handling above).

### Provider & reconnect
- `Provider` is backed by the bidirectional `OpenProviderStream`. Provide/publish/actuate message types are **id-keyed** (`ProvideSignalRequest` = `map<int32, SampleInterval>`, `PublishValuesRequest` = `map<int32, Datapoint>`), so the provider path relies on the `MetadataStore` id↔path cache populated via `ListMetadata`. `request_id` matching is used for `PublishValues`/`GetProviderValue` request/response correlation.
- **Reconnect:** `OpenProviderStream` is a gRPC stream, so a connection drop / broker restart terminates the stream — the provider's iteration ends/raises rather than hanging. The client invalidates its `MetadataStore`/id cache on reconnect; re-registration (re-`ProvideSignal`/re-`ProvideActuation`) is the caller's explicit action. Note broker-assigned signal ids are arbitrary and may change across a restart, so cached ids must never survive a reconnect.

### Errors & authentication
- `KuksaError` hierarchy distinguishes **transport/gRPC errors** (unary RPC status codes) from **application/stream errors** (in-stream `Error`/`ErrorCode` messages and `ProviderErrorIndication` on the provider stream).
- `authorize(token)` attaches the token as per-call gRPC metadata (the v1 `GetServerInfo` pseudo-auth trick is not carried over).

## Typing strategy
- Currency of the API = **native Python values** (int/float/str/bool/list). One complete `DataType ↔ python type` map in `codec.py`.
- **`TIMESTAMP` / `TIMESTAMP_ARRAY` are dropped** — the v2 `Value` oneof has no timestamp field, so these data types cannot be represented in values. `INT8`/`INT16`/`UINT8`/`UINT16` have no dedicated proto fields and are encoded as `int32`/`uint32`; the codec map carries this aliasing.
- No string-casting in the library; coercion lives in the CLI.
- `Datapoint` is a dataclass `Datapoint(value, timestamp: datetime | None)`; typed signatures throughout.

## Performance
- `MetadataStore` is an **in-memory cache bound to a connection** (cleared on reconnect). **No TTL needed**: VSS metadata is assumed static while a system is running. Invalidation happens on NOT_FOUND or via an explicit `refresh`/re-fetch method for special cases → `set()` without explicit type is one cached lookup, not a round-trip.
- High-frequency publishing is the `Provider`/OpenProviderStream path.

## CLI
- Rebuilt on the new sync client; drop ws/VISS and the thread/queue machinery.
- Keep the interactive cmd2 shell for compatibility; add one-shot commands:
  `kuksa-client get Vehicle.Speed` / `kuksa-client set Vehicle.Speed=42` / `kuksa-client subscribe Vehicle.Speed`.
- Value coercion in the CLI layer.

## Backwards compatibility & migration
- Old API (`kuksa_client.grpc`, `kuksa_client.grpc.aio`, `kuksa_client.KuksaClientThread`) frozen, deprecated via docs + `DeprecationWarning`, kept ≥ 2 minor releases.
- Class rename `VSSClient → KuksaClient`; publish a mapping table (getValue→get, setValue→set, updateVSSTree/updateMetaData→dropped (metadata is read-only in v2), subscribe→subscribe).
- ws/VISS support dropped in v2 (not ported).

## Testing
- In-memory **v2-only** mock databroker (gRPC servicer), same pattern as current `tests/conftest.py`.
- Codec round-trip / property tests across all `DataType`s.
- Client + provider tests against the mock; old-API suite kept green for regression.
- Optional dockerized integration suite against a real databroker.

## Build & packaging
- Keep distribution `kuksa-client`; add `kuksa_client/v2/` to the package.
- **Keep proto generation during build** (as today): the `.proto` files in the `kuksa-proto` submodule stay the single source of truth for the API. Committed/bundled generated files risk going stale and complicate proto/grpcio version bumps, so generation at build time from the submodule is intentional and should be preserved (and adapted for the new `kuksa_client/v2/` code that also consumes `kuksa.val.v2`).

## Open questions / next steps
- Exact CLI one-shot command grammar.
- Provider: which advanced `OpenProviderStream` features to expose in the first v2 SDK release (subscription `filters`/`UpdateFilterRequest`, on-demand `GetProviderValue`, and `ProviderErrorIndication`) vs. defer to the raw escape hatch.
