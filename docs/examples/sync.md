# Synchronous API

`kuksa_client.v2.KuksaClient` is a synchronous client for the `kuksa.val.v2`
protocol.

## Usage

```python
from kuksa_client.v2 import KuksaClient

with KuksaClient("127.0.0.1", 55555) as client:
    speed = client.get("Vehicle.Speed")
    if speed.value is not None:
        print(speed.value)
```

You can also connect explicitly instead of using the context manager:

```python
client = KuksaClient("127.0.0.1", 55555)
client.connect()
print(client.get("Vehicle.Speed").value)
client.disconnect()
```

## Setting and actuating

```python
from kuksa_client.v2 import KuksaClient, Datapoint

with KuksaClient("127.0.0.1", 55555) as client:
    client.set({"Vehicle.Speed": 42})
    client.set({"Vehicle.Speed": Datapoint(42)})

    client.actuate({
        "Vehicle.Body.Windshield.Front.Wiping.System.TargetPosition": 45,
    })
```

## Subscribing

```python
with KuksaClient("127.0.0.1", 55555) as client:
    for updates in client.subscribe(["Vehicle.Speed"]):
        for path, datapoint in updates.items():
            print(f"{path} is now {datapoint.value}")
```

## Wildcards and metadata

```python
with KuksaClient("127.0.0.1", 55555) as client:
    for path in client.expand("Vehicle.Cabin.**"):
        print(path)

    for metadata in client.list_metadata("Vehicle.Cabin.Sunroof.*"):
        print(metadata.path, metadata.data_type)
```

## Authorization

```python
with KuksaClient("127.0.0.1", 55555) as client:
    client.authorize("your-jwt-token")
    print(client.get("Vehicle.Speed").value)
```

The token may also be passed to the constructor:

```python
with KuksaClient("127.0.0.1", 55555, token="your-jwt-token") as client:
    ...
```
