# Changing, Testing and Troubleshoot Eclipse KUKSA Python SDK

## Running test suite & quality checks

This project uses pytest as its test framework and pylint as its linter.
To run the test suite:

```console
pytest
```

To run the linter:
```console
pylint kuksa_client
```


## Troubleshooting

1. The server/data broker is listening on its port but my client is unable to connect to it and returns an error:
```console
Error: Websocket could not be connected or the gRPC channel could not be created.
```
If you're running both client and server on your local host, make sure that:
- `localhost` domain name resolution is configured properly on your host.
- You are not using any proxies for localhost e.g. setting the `no_proxy` environment variable to `localhost,127.0.0.1`.
- If you are using the `gRPC` protocol in secure mode, the server certificate should have `CN = localhost` in its subject.

2. ``ImportError: cannot import name 'types_pb2' from 'kuksa.val.v1'``:
It sometimes happens that ``_pb2*.py`` files are not generated on editable installations of kuksa_client.
In order to manually generate those files and get more details if anything fails, run:
```console
python setup.py build_pb2
```


## Pre-commit set up
This repository is set up to use [pre-commit](https://pre-commit.com/) hooks.
Use `pip install pre-commit` to install pre-commit.
After you clone the project, run `pre-commit install` to install pre-commit into your git hooks.
Pre-commit will now run on every commit.
Every time you clone a project using pre-commit running pre-commit install should always be the first thing you do.

The Eclipse KUKSA Python SDK continuous integration perform the same tests as performed by the pre-commit checks,
so if you do not use pre-commit there is risk that the corresponding check in continuous integration will fail.
