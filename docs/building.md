# Building and running a local version of KUKSA Puthon SDK

For development purposes it may be necessary to customize the code for the client and run a locally built version. To be able to build all submodules must be present, and you build from the `kuksa-client` folder.

```console
git submodule update --init
cd kuksa-client
```

Hint: If you want to use another branch than master exchange the first command with

```console
git submodule update --recursive --remote --init
```

First we suggest you create a dedicated [python virtual environment](https://docs.python.org/3/library/venv.html) for kuksa-client:

```console
mkdir --parents ~/.venv
python3 -m venv ~/.venv/kuksa-client
source ~/.venv/kuksa-client/bin/activate  # Run this every time you want to activate kuksa-client's virtual environment
```

To use the right api interfaces of databroker run the following

```console
python3 -m prototagandcopy
```

This should copy the corresponding proto files to the kuksa-client directory.

You still might need to compile the proto files, to do so do

```console
python3 -m protobuild
```

Your prompt should change to somehting indicating you are in the virutal environment now, e.g.

```console
(kuksa-client) $
```
Inside the virtual environment install the dependencies
```console
pip install --upgrade pip
```

Now in order to ensure local `*.py` files will be used when running the client, we need to install kuksa-client in editable mode:

```console
pip install -r requirements.txt -e .
```

If you wish to also install test dependencies, run instead:

```console
pip install -r test-requirements.txt -e ".[test]"
```

Now you should be able to start using `kuksa-client`:
```console
kuksa-client --help
```

Whenever you want to exit kuksa-client's virtual environment, simply run:
```console
deactivate
```

# Managing Build Requirements

`kuksa-client` relies on [pip-tools](https://pip-tools.readthedocs.io/en/latest/) to pin requirements versions.
This guide gives you instructions to pin requirements for python3.8 which is the minimum version kuksa-client supports.

## Upgrade Requirements

We're using `pip-tools` against our `setup.cfg` file. This means `pip-tools` will make sure that the versions it will pin
match constraints from `setup.cfg`.

First install `pip-tools`:
```console
$ pip install pip-tools
```

Then, check requirements version constraints within `setup.cfg` are still valid or update them accordingly.
Then:

To upgrade requirements versions within `requirements.txt`, do:
```console
$ python3.8 -m piptools compile --upgrade --resolver=backtracking setup.cfg
```

To upgrade requirements versions within `test-requirements.txt`, do:
```console
$ python3.8 -m piptools compile --upgrade --extra=test --output-file=test-requirements.txt --resolver=backtracking setup.cfg
```

If you wish to upgrade individual packages see [Updating requirements](https://pip-tools.readthedocs.io/en/latest/#updating-requirements).
