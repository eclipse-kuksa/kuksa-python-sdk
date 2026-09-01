# Providers

A provider claims ownership of signals and actuators on the databroker, publishes
values at high frequency, and receives actuation requests.

## Synchronous provider

```python
from kuksa_client.v2 import KuksaClient, Provider

with KuksaClient("127.0.0.1", 55555) as client:
    provider = Provider(client)

    # Claim a signal (value is the minimum sample interval in ms, or None).
    provider.provide_signals({"Vehicle.Speed": None})

    # Claim an actuator.
    provider.provide_actuators(
        ["Vehicle.Body.Windshield.Front.Wiping.System.TargetPosition"]
    )

    # Publish a value (high-frequency path).
    provider.publish({"Vehicle.Speed": 42.5})

    # Receive and acknowledge actuation requests.
    for requests in provider.actuation_requests():
        for request in requests:
            print(f"Actuate {request.path} to {request.value}")
            provider.accept(request, ok=True)

    provider.close()
```

## Asynchronous provider

```python
import asyncio

from kuksa_client.v2.aio import KuksaClient, Provider

async def main():
    async with KuksaClient("127.0.0.1", 55555) as client:
        provider = Provider(client)
        await provider.provide_signals({"Vehicle.Speed": None})
        await provider.publish({"Vehicle.Speed": 42.5})

        await provider.provide_actuators(
            ["Vehicle.Body.Windshield.Front.Wiping.System.TargetPosition"]
        )
        async for requests in provider.actuation_requests():
            for request in requests:
                print(f"Actuate {request.path} to {request.value}")
                await provider.accept(request, ok=True)

        await provider.close()

asyncio.run(main())
```

## Notes

- `Provider` is backed by the bidirectional `OpenProviderStream` RPC. If the
  connection drops or the broker restarts, the stream ends and iteration/raises
  rather than hanging. Re-registration is the caller's explicit action.
- Advanced stream features (filters, `GetProviderValue`, error indications) are
  not yet exposed and can be reached via the raw `client.stub` escape hatch.
