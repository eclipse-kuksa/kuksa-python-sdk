# Using and Building Docker for the CLI

The KUKSA Python SDK CLI is available as a [prebuilt docker container](https://github.com/eclipse-kuksa/kuksa-python-sdk/pkgs/container/kuksa-python-sdk%2Fkuksa-client).
Not the most effcient way to pack a small python script, but it is easy to get started.
Pre-built containers are published whenever something is merged to `main` branch but also whenever a new release of KUKSA Python SDK is created.

The latest released docker version container can be run like this, arguments can be used in the same way as running a local client.

```console
docker run --rm -it --net=host ghcr.io/eclipse-kuksa/kuksa-python-sdk/kuksa-client:latest
```

If the ghcr registry is not easily accessible to you, e.g. if you are a China mainland user,  we also made the container images available at quay.io:

```console
docker run --rm -it --net=host quay.io/eclipse-kuksa/kuksa-client:latest
```

You can build a local docker image of the testclient using the [`Dockerfile`](../kuksa-client/Dockerfile).
The Dockerfile needs to be built from the repo root directory.

```console
cd /some/dir/kuksa-python-sdk/
docker build -f kuksa-client/Dockerfile -t kuksa-client:latest .
```

To run the newly built image:

```console
docker run --rm -it --net=host kuksa-client:latest --help
```

Notes:

- `--rm` ensures we do not keep the docker container lying around after closing kuksa-client and `--net=host` makes sure you can reach locally running kuksa.val-server or kuksa-val docker with port forwarding on the host using the default `127.0.0.1` address.
- CLI arguments that follow image name (e.g. `kuksa-client:latest`) will be passed through to kuksa-client entry point (e.g. `--help`).
