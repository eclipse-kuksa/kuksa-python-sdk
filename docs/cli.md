# Using the Command Line Interface (CLI)

After you have installed the kuksa-client package via pip you can run the client
CLI directly by executing:

```console
kuksa-client
```

This starts an interactive shell connected to a local databroker (a server
supporting the `kuksa.val.v2` protocol). This is equivalent to:

```console
kuksa-client --server grpc://127.0.0.1:55555
```

If the server can be contacted you will get an output similar to:

```console
Connecting to databroker at 127.0.0.1 port 55555...
Connected to databroker version 0.7.1
Kuksa Client>
```

## One-shot commands

Instead of the interactive shell, a single command can be executed:

```console
kuksa-client --server grpc://127.0.0.1:55555 get Vehicle.Speed
kuksa-client --server grpc://127.0.0.1:55555 set Vehicle.Speed=42
kuksa-client --server grpc://127.0.0.1:55555 subscribe Vehicle.Speed
```

Available one-shot commands:

| Command | Description |
|---------|-------------|
| `get <path...>` | Get the value of one or more paths |
| `set <Path=Value...>` | Set values (e.g. `Vehicle.Speed=42`) |
| `actuate <Path=Value...>` | Actuate actuators (e.g. `Vehicle.Body.Wiper.Pos=45`) |
| `subscribe <path...>` | Subscribe to one or more paths |
| `mock-actuator <path...>` | Provide a mock actuator that accepts and prints received actuations (until terminated) |
| `get-metadata <path>` | Get the metadata of a path |
| `list-metadata <pattern>` | List metadata matching a pattern |
| `expand <pattern>` | Expand a wildcard pattern into paths |
| `has-signal <path>` | Check whether a signal exists |
| `server-info` | Show databroker info |

## Interactive shell commands

| Command | Description |
|---------|-------------|
| `connect <grpc://host:port>` | Connect to a databroker |
| `disconnect` | Disconnect from the databroker |
| `authorize <token>` | Authorize with a JWT token or token file |
| `get <path...>` | Get the value of one or more paths |
| `set <Path=Value...>` | Set values |
| `actuate <Path=Value...>` | Actuate actuators (target values) |
| `subscribe <path...>` | Subscribe to updates |
| `subscribe -b <path...>` | Subscribe in the background; updates print as alerts while the prompt stays usable |
| `unsubscribe <id>` | Stop a background subscription |
| `mock_actuator <path...>` | Register a mock provider that accepts and prints actuations |
| `remove_mock <id>` | Remove a mock actuator provider |
| `get_metadata <path>` | Get the metadata of a path |
| `list_metadata <pattern>` | List metadata matching a pattern |
| `expand <pattern>` | Expand a wildcard pattern into paths |
| `has_signal <path>` | Check whether a signal exists |
| `info` / `version` | Show client info / version |

Refer `help` for further information.

## Logging

The log level can be set with the `LOG_LEVEL` environment variable
(`error`, `warning`, `info` (default), `debug`):

```console
LOG_LEVEL=debug kuksa-client
```

## TLS

KUKSA Client uses TLS to connect to a databroker when the server scheme is
`grpcs`. The root certificate must be specified with `--cacertificate <path>`:

```console
kuksa-client --server grpcs://localhost:55555 --cacertificate ~/kuksa-common/tls/CA.pem
```

If connecting by IP address, `--tls-server-name` may also be required:

```console
kuksa-client --server grpcs://127.0.0.1:55555 --cacertificate ~/kuksa-common/tls/CA.pem --tls-server-name Server
```

## Authorization

If the databroker requires authorization, authorize with a token or token file:

```console
Kuksa Client> authorize /some/path/jwt/provide-all.token
```

or via the one-shot commands using `--token`:

```console
kuksa-client --token /some/path/jwt/provide-all.token --server grpc://127.0.0.1:55555 get Vehicle.Speed
```

## Value syntax

Values passed to `set` are coerced to the signal's data type automatically:

```console
Kuksa Client> set Vehicle.Speed=43
Kuksa Client> set Vehicle.Speed=45.2
Kuksa Client> set Vehicle.Cabin.Light.InteractiveLightBar.Effect='Almost green'
```

Array values use JSON-like syntax:

```console
Kuksa Client> set Vehicle.OBD.DTCList='["abc","def"]'
Kuksa Client> set Vehicle.SomeInt='[123,456]'
```
