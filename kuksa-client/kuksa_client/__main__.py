#! /usr/bin/env python
########################################################################
# Copyright (c) 2020 Robert Bosch GmbH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0
########################################################################

import argparse
import dataclasses
import json
import logging
import os
import pathlib
import sys
import threading
from urllib.parse import urlparse

import grpc
from cmd2 import Cmd
from cmd2 import Cmd2ArgumentParser
from cmd2 import CompletionItem
from cmd2 import with_argparser
from cmd2 import with_category
from cmd2 import constants
from pygments import formatters
from pygments import highlight
from pygments import lexers

from kuksa_client import _metadata
from kuksa_client.kuksa_logger import KuksaLogger
from kuksa_client.v2 import EntryType
from kuksa_client.v2 import KuksaClient
from kuksa_client.v2 import KuksaError
from kuksa_client.v2 import NotFound
from kuksa_client.v2 import Provider
from kuksa_client.v2.coercion import coerce_value

scriptDir = os.path.dirname(os.path.realpath(__file__))

DEFAULT_KUKSA_ADDRESS = os.environ.get("KUKSA_ADDRESS", "grpc://127.0.0.1:55555")
DEFAULT_TOKEN_OR_TOKENFILE = os.environ.get("TOKEN_OR_TOKENFILE", None)
DEFAULT_CACERTIFICATE = os.environ.get("CACERTIFICATE", None)
DEFAULT_TLS_SERVER_NAME = os.environ.get("TLS_SERVER_NAME", None)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Value coercion (thin wrapper over kuksa_client.v2.coercion)
# ---------------------------------------------------------------------------


def coerce_assignments(client, assignments):
    """
    Coerce ``Path=Value`` assignment strings into a ``{path: native value}``
    mapping using each signal's data type.
    """
    updates = {}
    for assignment in assignments:
        if "=" not in assignment:
            raise KuksaError(f"Invalid assignment: {assignment} (expected Path=Value)")
        path, value = assignment.split("=", maxsplit=1)
        data_type = client.get_metadata(path).data_type
        updates[path] = coerce_value(value, data_type)
    return updates


def _check_actuator_paths(client, paths):
    """
    Return an error message if any of ``paths`` is not an actuator, else None.

    The databroker does not reliably reject non-actuator paths on
    ``ProvideActuationRequest``, so the CLI validates this client-side.
    """
    for path in paths:
        metadata = client.get_metadata(path)
        if metadata.entry_type != EntryType.ACTUATOR:
            return f"{path} is not an actuator"
    return None


def _expand_wildcard_paths(client, paths):
    """
    Resolve ``paths`` into concrete signal paths.

    Paths containing ``*`` are expanded via ``client.expand``; exact paths are
    passed through unchanged. Duplicates are removed, order is preserved.
    """
    resolved = []
    for path in paths:
        if "*" in path:
            resolved.extend(client.expand(path))
        else:
            resolved.append(path)
    seen = set()
    result = []
    for path in resolved:
        if path not in seen:
            seen.add(path)
            result.append(path)
    return result


# ---------------------------------------------------------------------------
# Path completion (interactive shell)
# ---------------------------------------------------------------------------

def _matching_paths(shell, text):
    if shell.client is None:
        return []
    if not shell._completion_paths:
        try:
            shell._completion_paths = shell.client.expand("")
        except KuksaError:
            return []
    lowered = text.lower()
    return [
        path for path in shell._completion_paths if path.lower().startswith(lowered)
    ]


def path_completer(shell, text, line, begidx, endidx):
    """Complete VSS signal paths (e.g. ``get Vehicle.S<tab>``)."""
    return shell.basic_complete(
        text, line, begidx, endidx, _matching_paths(shell, text)
    )


def set_completer(shell, text, line, begidx, endidx):
    """Complete the path portion of a ``Path=Value`` argument."""
    if "=" in text:
        path_part = text.split("=", maxsplit=1)[0]
        endidx = begidx + len(path_part)
        return shell.basic_complete(
            path_part, line, begidx, endidx, _matching_paths(shell, path_part)
        )
    return shell.basic_complete(
        text, line, begidx, endidx, _matching_paths(shell, text)
    )


def unsubscribe_completer(shell, text, line, begidx, endidx):
    """Complete active background subscription ids."""
    items = []
    with shell._subscription_lock:
        for sub_id, info in shell._subscriptions.items():
            items.append(
                CompletionItem(str(sub_id), display=f"{sub_id}: {', '.join(info.paths)}")
            )
    return shell.basic_complete(text, line, begidx, endidx, items)


def remove_mock_completer(shell, text, line, begidx, endidx):
    """Complete active mock actuator provider ids."""
    items = []
    with shell._mock_lock:
        for mock_id, info in shell._mocks.items():
            items.append(
                CompletionItem(str(mock_id), display=f"{mock_id}: {', '.join(info.paths)}")
            )
    return shell.basic_complete(text, line, begidx, endidx, items)


# ---------------------------------------------------------------------------
# Interactive shell
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class _BackgroundSubscription:
    paths: list
    stream: object = None
    thread: threading.Thread = None


@dataclasses.dataclass
class _MockActuator:
    paths: list
    provider: object = None
    thread: threading.Thread = None
    loopback: bool = False


class KuksaShell(Cmd):
    COMM_SETUP_COMMANDS = "Communication Set-up Commands"
    VSS_COMMANDS = "Kuksa Interaction Commands"
    INFO_COMMANDS = "Info Commands"

    ap_connect = Cmd2ArgumentParser()
    ap_connect.add_argument(
        "server",
        help="Databroker to connect to. Format: grpc://host[:port], grpcs://host[:port] or unix:///path/to/socket.",
    )

    ap_authorize = Cmd2ArgumentParser()
    ap_authorize.add_argument("token", help="JWT token or path to a .token file")

    ap_get = Cmd2ArgumentParser()
    ap_get.add_argument(
        "Path", help="Path whose value is to be read", nargs="+", completer=path_completer
    )

    ap_set = Cmd2ArgumentParser()
    ap_set.add_argument(
        "Path=Value",
        help="Path and new value, e.g. Vehicle.Speed=42",
        nargs="+",
        completer=set_completer,
    )

    ap_actuate = Cmd2ArgumentParser()
    ap_actuate.add_argument(
        "Path=Value",
        help="Path and target value, e.g. Vehicle.Body.Wiper.Pos=45",
        nargs="+",
        completer=set_completer,
    )

    ap_subscribe = Cmd2ArgumentParser()
    ap_subscribe.add_argument(
        "Path", help="Path to subscribe to", nargs="+", completer=path_completer
    )
    ap_subscribe.add_argument(
        "-b",
        "--background",
        action="store_true",
        help="Subscribe in the background and print updates as alerts",
    )

    ap_unsubscribe = Cmd2ArgumentParser()
    ap_unsubscribe.add_argument(
        "SubscribeId",
        type=int,
        help="Id of a background subscription to stop",
        completer=unsubscribe_completer,
    )

    ap_mock_actuator = Cmd2ArgumentParser()
    ap_mock_actuator.add_argument(
        "Path",
        help="Actuator path to provide",
        nargs="+",
        completer=path_completer,
    )
    ap_mock_actuator.add_argument(
        "-l",
        "--loopback",
        action="store_true",
        help="Also set the received value as the signal's current value",
    )

    ap_remove_mock = Cmd2ArgumentParser()
    ap_remove_mock.add_argument(
        "Id",
        type=int,
        help="Id of a mock actuator provider to remove",
        completer=remove_mock_completer,
    )

    ap_get_metadata = Cmd2ArgumentParser()
    ap_get_metadata.add_argument(
        "Path", help="Path whose metadata is to be read", completer=path_completer
    )

    ap_list_metadata = Cmd2ArgumentParser()
    ap_list_metadata.add_argument(
        "Pattern", help="Exact path or wildcard pattern", completer=path_completer
    )

    ap_has_signal = Cmd2ArgumentParser()
    ap_has_signal.add_argument("Path", help="Path to check", completer=path_completer)

    def __init__(self, server, token_or_tokenfile=None, cacertificate=None, tls_server_name=None):
        shortcuts = constants.DEFAULT_SHORTCUTS
        shortcuts.update({"exit": "quit"})
        super().__init__(
            persistent_history_file=".kuksa_client_history",
            persistent_history_length=100,
            shortcuts=shortcuts,
            allow_cli_args=False,
        )
        self.prompt = "Kuksa Client> "
        self.server = server
        self.token_or_tokenfile = token_or_tokenfile
        self.cacertificate = cacertificate
        self.tls_server_name = tls_server_name
        self.client = None
        self._completion_paths = []
        self._subscriptions = {}
        self._subscription_lock = threading.Lock()
        self._subscription_counter = 0
        self._mocks = {}
        self._mock_lock = threading.Lock()
        self._mock_counter = 0

        with (pathlib.Path(scriptDir) / "logo").open("r", encoding="utf-8") as logo_file:
            print(logo_file.read().replace("%ver%", str(_metadata.__version__)))
        print()
        self.connect()

    # ------------------------------------------------------------------
    def _load_token(self, token_or_tokenfile):
        if token_or_tokenfile is None:
            return None
        path = pathlib.Path(token_or_tokenfile)
        if path.is_file():
            return path.expanduser().read_text(encoding="utf-8").rstrip("\n")
        return token_or_tokenfile

    def _connect_kwargs(self):
        srv = urlparse(self.server)
        if srv.scheme == "unix":
            kwargs = {
                "unix_socket": srv.path,
                "tls_server_name": self.tls_server_name,
            }
            token = self._load_token(self.token_or_tokenfile)
            if token:
                kwargs["token"] = token
            return kwargs
        host = srv.hostname or "127.0.0.1"
        port = srv.port or 55555
        kwargs = {
            "host": host,
            "port": port,
            "tls_server_name": self.tls_server_name,
        }
        token = self._load_token(self.token_or_tokenfile)
        if token:
            kwargs["token"] = token
        if srv.scheme in ("grpcs",):
            if self.cacertificate is None:
                print("TLS cannot be used as no CA Certificate was specified!")
                return None
            kwargs["root_certificates"] = pathlib.Path(self.cacertificate)
        return kwargs

    def _require_client(self):
        if self.client is None:
            self.connect()
        if self.client is None:
            raise KuksaError("Not connected to a databroker")
        return self.client

    # ------------------------------------------------------------------
    def connect(self):
        if self.client is not None:
            self.client.disconnect()
            self.client = None
        self._completion_paths = []
        kwargs = self._connect_kwargs()
        if kwargs is None:
            return
        if "unix_socket" in kwargs:
            print(f"Connecting to databroker at unix://{kwargs['unix_socket']}...")
        else:
            print(f"Connecting to databroker at {kwargs['host']} port {kwargs['port']}...")
        self.client = KuksaClient(**kwargs)
        self.client.connect()
        try:
            info = self.client.get_server_info()
            print(f"Connected to {info.name} version {info.version}")
        except KuksaError as exc:
            print(f"Connected (server info unavailable: {exc})")

    def _print_json(self, obj):
        print(
            highlight(
                json.dumps(obj, indent=2, default=str),
                lexers.JsonLexer(),
                formatters.TerminalFormatter(),
            )
        )

    def _stop_subscriptions(self):
        with self._subscription_lock:
            infos = list(self._subscriptions.values())
            self._subscriptions.clear()
        for info in infos:
            if info.stream is not None:
                info.stream.cancel()
        for info in infos:
            if info.thread is not None:
                info.thread.join(timeout=1)

    def _stop_mocks(self):
        with self._mock_lock:
            infos = list(self._mocks.values())
            self._mocks.clear()
        for info in infos:
            if info.provider is not None:
                info.provider.close()
        for info in infos:
            if info.thread is not None:
                info.thread.join(timeout=1)

    @with_category(COMM_SETUP_COMMANDS)
    @with_argparser(ap_connect)
    def do_connect(self, args):
        """Connect to a databroker"""
        self.server = args.server
        self.connect()

    @with_category(COMM_SETUP_COMMANDS)
    def do_disconnect(self, _args):
        """Disconnect from the databroker"""
        if self.client is not None:
            self.client.disconnect()
            self.client = None
        self._completion_paths = []
        self._stop_subscriptions()
        self._stop_mocks()

    @with_category(COMM_SETUP_COMMANDS)
    @with_argparser(ap_authorize)
    def do_authorize(self, args):
        """Authorize the client with a JWT token"""
        token = self._load_token(args.token)
        client = self._require_client()
        client.authorize(token)
        print("Authenticated")

    @with_category(VSS_COMMANDS)
    @with_argparser(ap_get)
    def do_get(self, args):
        """Get the value of one or more paths (wildcards are expanded)"""
        client = self._require_client()
        single = len(args.Path) == 1 and not any("*" in path for path in args.Path)
        try:
            resolved = _expand_wildcard_paths(client, args.Path)
        except KuksaError as exc:
            print(f"Error: {exc}")
            return
        if not resolved:
            print("No signals match the given path(s)")
            return
        try:
            if single:
                result = client.get(resolved[0])
            else:
                result = client.get(resolved)
        except KuksaError as exc:
            print(f"Error: {exc}")
            return
        if single:
            self._print_json({"value": result.value, "timestamp": result.timestamp})
        else:
            self._print_json({path: dp.value for path, dp in result.items()})

    @with_category(VSS_COMMANDS)
    @with_argparser(ap_set)
    def do_set(self, args):
        """Set the value of one or more paths"""
        client = self._require_client()
        try:
            updates = coerce_assignments(client, getattr(args, "Path=Value"))
        except (KuksaError, ValueError) as exc:
            print(f"Error: {exc}")
            return
        try:
            client.set(updates)
        except KuksaError as exc:
            print(f"Error: {exc}")

    @with_category(VSS_COMMANDS)
    @with_argparser(ap_actuate)
    def do_actuate(self, args):
        """Actuate one or more actuators (target values)"""
        client = self._require_client()
        try:
            updates = coerce_assignments(client, getattr(args, "Path=Value"))
        except (KuksaError, ValueError) as exc:
            print(f"Error: {exc}")
            return
        try:
            client.actuate(updates)
        except KuksaError as exc:
            print(f"Error: {exc}")

    @with_category(VSS_COMMANDS)
    @with_argparser(ap_subscribe)
    def do_subscribe(self, args):
        """Subscribe to updates of one or more paths (wildcards are expanded)"""
        client = self._require_client()
        try:
            resolved = _expand_wildcard_paths(client, args.Path)
        except KuksaError as exc:
            print(f"Error: {exc}")
            return
        if not resolved:
            print("No signals match the given path(s)")
            return
        if args.background:
            stream = client._subscribe_stream(resolved)
            with self._subscription_lock:
                self._subscription_counter += 1
                sub_id = self._subscription_counter
            thread = threading.Thread(
                target=self._subscribe_background,
                args=(sub_id, client, stream),
                daemon=True,
            )
            with self._subscription_lock:
                self._subscriptions[sub_id] = _BackgroundSubscription(
                    paths=list(args.Path), stream=stream, thread=thread
                )
            thread.start()
            print(f"Subscribed to {', '.join(args.Path)} (subscription {sub_id})")
            return
        try:
            for updates in client.subscribe(resolved):
                self._print_json({path: dp.value for path, dp in updates.items()})
        except KuksaError as exc:
            print(f"Error: {exc}")

    def _subscribe_background(self, sub_id, client, stream):
        try:
            for response in stream:
                updates = client._parse_subscribe_response(response)
                message = highlight(
                    json.dumps(
                        {path: dp.value for path, dp in updates.items()},
                        indent=2,
                        default=str,
                    ),
                    lexers.JsonLexer(),
                    formatters.TerminalFormatter(),
                )
                self.add_alert(msg=message)
        except grpc.RpcError as exc:
            if exc.code() != grpc.StatusCode.CANCELLED and client.connected:
                self.add_alert(msg=f"Subscription error: {client._translate_rpc_error(exc)}")
        except Exception:
            # The stream was terminated, e.g. by a disconnect.
            pass
        finally:
            with self._subscription_lock:
                self._subscriptions.pop(sub_id, None)

    @with_category(VSS_COMMANDS)
    @with_argparser(ap_unsubscribe)
    def do_unsubscribe(self, args):
        """Stop a background subscription"""
        info = self._cancel_subscription(args.SubscribeId)
        if info is None:
            print(f"No active subscription with id {args.SubscribeId}")
            return
        print(f"Unsubscribed {args.SubscribeId} ({', '.join(info.paths)})")

    def _cancel_subscription(self, sub_id):
        with self._subscription_lock:
            info = self._subscriptions.pop(sub_id, None)
        if info is None:
            return None
        if info.stream is not None:
            info.stream.cancel()
        if info.thread is not None:
            info.thread.join(timeout=1)
        return info

    @with_category(VSS_COMMANDS)
    @with_argparser(ap_mock_actuator)
    def do_mock_actuator(self, args):
        """Register a mock provider that accepts and prints actuations"""
        client = self._require_client()
        try:
            error = _check_actuator_paths(client, args.Path)
        except KuksaError as exc:
            print(f"Error: {exc}")
            return
        if error is not None:
            print(f"Error: {error}")
            return

        provider = Provider(client)
        try:
            provider.provide_actuators(args.Path)
        except KuksaError as exc:
            provider.close()
            print(f"Error: {exc}")
            return

        with self._mock_lock:
            self._mock_counter += 1
            mock_id = self._mock_counter
        thread = threading.Thread(
            target=self._mock_actuator_loop,
            args=(mock_id, provider, client, args.loopback),
            daemon=True,
        )
        with self._mock_lock:
            self._mocks[mock_id] = _MockActuator(
                paths=list(args.Path),
                provider=provider,
                thread=thread,
                loopback=args.loopback,
            )
        thread.start()
        print(f"Registered mock actuator {mock_id} for {', '.join(args.Path)}")

    def _mock_actuator_loop(self, mock_id, provider, client=None, loopback=False):
        try:
            for requests in provider.actuation_requests():
                updates = {}
                for request in requests:
                    message = highlight(
                        json.dumps(
                            {"path": request.path, "value": request.value},
                            indent=2,
                            default=str,
                        ),
                        lexers.JsonLexer(),
                        formatters.TerminalFormatter(),
                    )
                    self.add_alert(msg=message)
                    try:
                        provider.accept(request, ok=True)
                    except Exception:
                        pass
                    if loopback:
                        updates[request.path] = request.value
                if loopback and updates and client is not None:
                    try:
                        client.set(updates)
                    except Exception as exc:
                        self.add_alert(msg=f"Loopback error: {exc}")
        except Exception:
            # The stream was terminated, e.g. by a disconnect or removal.
            pass
        finally:
            with self._mock_lock:
                self._mocks.pop(mock_id, None)

    @with_category(VSS_COMMANDS)
    @with_argparser(ap_remove_mock)
    def do_remove_mock(self, args):
        """Remove a mock actuator provider"""
        info = self._cancel_mock(args.Id)
        if info is None:
            print(f"No active mock actuator with id {args.Id}")
            return
        print(f"Removed mock actuator {args.Id} ({', '.join(info.paths)})")

    def _cancel_mock(self, mock_id):
        with self._mock_lock:
            info = self._mocks.pop(mock_id, None)
        if info is None:
            return None
        if info.provider is not None:
            info.provider.close()
        if info.thread is not None:
            info.thread.join(timeout=1)
        return info

    @with_category(VSS_COMMANDS)
    @with_argparser(ap_get_metadata)
    def do_get_metadata(self, args):
        """Get the metadata of a path"""
        client = self._require_client()
        try:
            metadata = client.get_metadata(args.Path)
            self._print_json(_metadata_to_dict(metadata))
        except KuksaError as exc:
            print(f"Error: {exc}")

    @with_category(VSS_COMMANDS)
    @with_argparser(ap_list_metadata)
    def do_list_metadata(self, args):
        """List metadata of signals matching a pattern"""
        client = self._require_client()
        try:
            metadatas = client.list_metadata(args.Pattern)
            self._print_json([_metadata_to_dict(m) for m in metadatas])
        except KuksaError as exc:
            print(f"Error: {exc}")

    @with_category(VSS_COMMANDS)
    @with_argparser(ap_has_signal)
    def do_has_signal(self, args):
        """Check whether a signal exists"""
        client = self._require_client()
        try:
            print(client.has_signal(args.Path))
        except KuksaError as exc:
            print(f"Error: {exc}")

    @with_category(INFO_COMMANDS)
    def do_info(self, _args):
        """Show summary info of the client"""
        print("kuksa-client version " + _metadata.__version__)
        print("Uri: " + _metadata.__uri__)
        print("Author: " + _metadata.__author__)
        print("Copyright: " + _metadata.__copyright__)

    @with_category(INFO_COMMANDS)
    def do_version(self, _args):
        """Show the client version"""
        print(_metadata.__version__)

    def stop(self):
        if self.client is not None:
            self.client.disconnect()
            self.client = None
        self._stop_subscriptions()
        self._stop_mocks()


def _metadata_to_dict(metadata):
    result = {
        "path": metadata.path,
        "data_type": metadata.data_type.name,
        "entry_type": metadata.entry_type.name,
    }
    for field in ("description", "comment", "deprecation", "unit"):
        value = getattr(metadata, field, None)
        if value is not None:
            result[field] = value
    if metadata.value_restriction is not None:
        result["value_restriction"] = {
            "min": metadata.value_restriction.min,
            "max": metadata.value_restriction.max,
            "allowed_values": metadata.value_restriction.allowed_values,
        }
    return result


# ---------------------------------------------------------------------------
# One-shot commands
# ---------------------------------------------------------------------------

def _build_one_shot_parser():
    parser = argparse.ArgumentParser(prog="kuksa-client", description="KUKSA Databroker client")
    parser.add_argument(
        "--server",
        default=DEFAULT_KUKSA_ADDRESS,
        help="Databroker to connect to. Format: grpc://host[:port], grpcs://host[:port] or unix:///path/to/socket.",
    )
    parser.add_argument("--token", default=DEFAULT_TOKEN_OR_TOKENFILE, help="JWT token or path to a .token file")
    parser.add_argument("--cacertificate", default=DEFAULT_CACERTIFICATE, help="Client root cert file (.pem)")
    parser.add_argument("--tls-server-name", default=DEFAULT_TLS_SERVER_NAME, help="CA name of the server")

    subparsers = parser.add_subparsers(dest="command")

    p_get = subparsers.add_parser("get", help="Get the value of one or more paths")
    p_get.add_argument("paths", nargs="+")

    p_set = subparsers.add_parser("set", help="Set values, e.g. Vehicle.Speed=42")
    p_set.add_argument("assignments", nargs="+", help="Path=Value pairs")

    p_act = subparsers.add_parser("actuate", help="Actuate actuators, e.g. Vehicle.Body.Wiper.Pos=45")
    p_act.add_argument("assignments", nargs="+", help="Path=Value pairs")

    p_sub = subparsers.add_parser("subscribe", help="Subscribe to one or more paths")
    p_sub.add_argument("paths", nargs="+")

    p_mock = subparsers.add_parser(
        "mock-actuator",
        help="Provide a mock actuator that prints received actuations",
    )
    p_mock.add_argument("paths", nargs="+", help="Actuator paths to provide")
    p_mock.add_argument(
        "-l",
        "--loopback",
        action="store_true",
        help="Also set the received value as the signal's current value",
    )

    p_md = subparsers.add_parser("get-metadata", help="Get the metadata of a path")
    p_md.add_argument("path")

    p_lmd = subparsers.add_parser("list-metadata", help="List metadata matching a pattern")
    p_lmd.add_argument("pattern")

    p_has = subparsers.add_parser("has-signal", help="Check whether a signal exists")
    p_has.add_argument("path")

    subparsers.add_parser("server-info", help="Show databroker info")

    return parser


def _open_client(args):
    srv = urlparse(args.server)
    if srv.scheme == "unix":
        kwargs = {"unix_socket": srv.path, "tls_server_name": args.tls_server_name}
        token = args.token
        if token and pathlib.Path(token).is_file():
            token = pathlib.Path(token).read_text(encoding="utf-8").rstrip("\n")
        if token:
            kwargs["token"] = token
        return KuksaClient(**kwargs)
    host = srv.hostname or "127.0.0.1"
    port = srv.port or 55555
    kwargs = {"host": host, "port": port, "tls_server_name": args.tls_server_name}
    token = args.token
    if token and pathlib.Path(token).is_file():
        token = pathlib.Path(token).read_text(encoding="utf-8").rstrip("\n")
    if token:
        kwargs["token"] = token
    if srv.scheme == "grpcs":
        if args.cacertificate is None:
            raise KuksaError("TLS cannot be used as no CA Certificate was specified!")
        kwargs["root_certificates"] = pathlib.Path(args.cacertificate)
    return KuksaClient(**kwargs)


def _run_one_shot(args):
    client = _open_client(args)
    try:
        with client:
            command = args.command
            if command == "get":
                paths = args.paths
                single = len(paths) == 1 and not any("*" in p for p in paths)
                resolved = _expand_wildcard_paths(client, paths)
                if not resolved:
                    print("No signals match the given path(s)", file=sys.stderr)
                    return 1
                if single:
                    result = client.get(resolved[0])
                    print(json.dumps({"value": result.value, "timestamp": result.timestamp}, indent=2, default=str))
                else:
                    result = client.get(resolved)
                    print(json.dumps({p: dp.value for p, dp in result.items()}, indent=2, default=str))
            elif command == "set":
                client.set(coerce_assignments(client, args.assignments))
            elif command == "actuate":
                client.actuate(coerce_assignments(client, args.assignments))
            elif command == "subscribe":
                resolved = _expand_wildcard_paths(client, args.paths)
                if not resolved:
                    print("No signals match the given path(s)", file=sys.stderr)
                    return 1
                for updates in client.subscribe(resolved):
                    print(json.dumps({p: dp.value for p, dp in updates.items()}, default=str))
            elif command == "mock-actuator":
                provider = Provider(client)
                provider.provide_actuators(args.paths)
                try:
                    for requests in provider.actuation_requests():
                        updates = {}
                        for request in requests:
                            print(
                                json.dumps(
                                    {"path": request.path, "value": request.value},
                                    default=str,
                                )
                            )
                            provider.accept(request, ok=True)
                            if args.loopback:
                                updates[request.path] = request.value
                        if args.loopback and updates:
                            try:
                                client.set(updates)
                            except Exception as exc:
                                print(f"Loopback error: {exc}", file=sys.stderr)
                except KeyboardInterrupt:
                    pass
                finally:
                    provider.close()
            elif command == "get-metadata":
                print(json.dumps(_metadata_to_dict(client.get_metadata(args.path)), indent=2))
            elif command == "list-metadata":
                print(json.dumps([_metadata_to_dict(m) for m in client.list_metadata(args.pattern)], indent=2))
            elif command == "has-signal":
                print(client.has_signal(args.path))
            elif command == "server-info":
                info = client.get_server_info()
                print(
                    json.dumps(
                        {
                            "name": info.name,
                            "version": info.version,
                            "commit_hash": info.commit_hash,
                        },
                        indent=2,
                    )
                )
    except (KuksaError, NotFound, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def main():
    kuksa_logger = KuksaLogger()
    kuksa_logger.init_logging()

    parser = _build_one_shot_parser()
    args = parser.parse_args()

    if args.command:
        return _run_one_shot(args)

    shell = KuksaShell(
        args.server,
        token_or_tokenfile=args.token,
        cacertificate=args.cacertificate,
        tls_server_name=args.tls_server_name,
    )
    try:
        shell.cmdloop()
    finally:
        shell.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
