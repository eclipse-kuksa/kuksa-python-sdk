# Asynchronous API (asyncio)

`kuksa_client.v2.aio.KuksaClient` is an asynchronous client for the
`kuksa.val.v2` protocol.

## Usage

```python
import asyncio

from kuksa_client.v2.aio import KuksaClient

async def main():
    async with KuksaClient("127.0.0.1", 55555) as client:
        speed = await client.get("Vehicle.Speed")
        if speed.value is not None:
            print(speed.value)

asyncio.run(main())
```

## Setting and actuating

```python
async def main():
    async with KuksaClient("127.0.0.1", 55555) as client:
        await client.set({"Vehicle.Speed": 42})
        await client.actuate({
            "Vehicle.Body.Windshield.Front.Wiping.System.TargetPosition": 45,
        })

asyncio.run(main())
```

## Subscribing

```python
async def main():
    async with KuksaClient("127.0.0.1", 55555) as client:
        async for updates in client.subscribe(["Vehicle.Speed"]):
            for path, datapoint in updates.items():
                print(f"{path} is now {datapoint.value}")

asyncio.run(main())
```

## Wildcards and metadata

```python
async def main():
    async with KuksaClient("127.0.0.1", 55555) as client:
        for path in await client.expand("Vehicle.Cabin.**"):
            print(path)

        for metadata in await client.list_metadata("Vehicle.Cabin.Sunroof.*"):
            print(metadata.path, metadata.data_type)

asyncio.run(main())
```

## Authorization

```python
async def main():
    async with KuksaClient("127.0.0.1", 55555, token="your-jwt-token") as client:
        print((await client.get("Vehicle.Speed")).value)

asyncio.run(main())
```
