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
from kuksa_client.v2 import DataType
from kuksa_client.v2 import EntryType
from kuksa_client.v2 import KuksaClient
from kuksa_client.v2 import KuksaError
from kuksa_client.v2 import NotFound

scriptDir = os.path.dirname(os.path.realpath(__file__))

DEFAULT_KUKSA_ADDRESS = os.environ.get("KUKSA_ADDRESS", "grpc://127.0.0.1:55555")
DEFAULT_TOKEN_OR_TOKENFILE = os.environ.get("TOKEN_OR_TOKENFILE", None)
DEFAULT_CACERTIFICATE = os.environ.get("CACERTIFICATE", None)
DEFAULT_TLS_SERVER_NAME = os.environ.get("TLS_SERVER_NAME", None)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Value coercion (CLI layer only)
# ---------------------------------------------------------------------------

_BOOL_TRUE = {"true", "t", "1", "yes", "on"}
_BOOL_FALSE = {"false", "f", "0", "no", "off"}
_INT_TYPES = {
    DataType.INT8,
    DataType.INT16,
    DataType.INT32,
    DataType.INT64,
    DataType.UINT8,
    DataType.UINT16,
    DataType.UINT32,
    DataType.UINT64,
}
_FLOAT_TYPES = {DataType.FLOAT, DataType.DOUBLE}
_INT_ARRAYS = {
    DataType.INT8_ARRAY,
    DataType.INT16_ARRAY,
    DataType.INT32_ARRAY,
    DataType.INT64_ARRAY,
    DataType.UINT8_ARRAY,
    DataType.UINT16_ARRAY,
    DataType.UINT32_ARRAY,
    DataType.UINT64_ARRAY,
}
_FLOAT_ARRAYS = {DataType.FLOAT_ARRAY, DataType.DOUBLE_ARRAY}


def _parse_array(text, data_type):
    stripped = text.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        stripped = stripped[1:-1]
    items = [item.strip() for item in stripped.split(",") if item.strip() != ""]
    if data_type == DataType.STRING_ARRAY:
        def cast(s):
            return s.strip("\"'")
    elif data_type == DataType.BOOLEAN_ARRAY:
        cast = _coerce_bool
    elif data_type in _INT_ARRAYS:
        cast = int
    elif data_type in _FLOAT_ARRAYS:
        cast = float
    else:
        cast = str
    return [cast(item) for item in items]


def _coerce_bool(text):
    lowered = text.strip().lower()
    if lowered in _BOOL_TRUE:
        return True
    if lowered in _BOOL_FALSE:
        return False
    raise ValueError(f"Invalid boolean value: {text}")


def coerce_value(text, data_type):
    if data_type is None or data_type == DataType.UNSPECIFIED:
        return text
    if data_type == DataType.BOOLEAN:
        return _coerce_bool(text)
    if data_type in _FLOAT_TYPES:
        return float(text)
    if data_type in _INT_TYPES:
        return int(text)
    if data_type.name.endswith("_ARRAY"):
        return _parse_array(text, data_type)
    return text


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


# ---------------------------------------------------------------------------
# Interactive shell
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class _BackgroundSubscription:
    paths: list
    stream: object = None
    thread: threading.Thread = None


class KuksaShell(Cmd):
    COMM_SETUP_COMMANDS = "Communication Set-up Commands"
    VSS_COMMANDS = "Kuksa Interaction Commands"
    INFO_COMMANDS = "Info Commands"

    ap_connect = Cmd2ArgumentParser()
    ap_connect.add_argument(
        "server",
        help="Databroker to connect to. Format: grpc://host[:port] or grpcs://host[:port].",
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

    ap_get_metadata = Cmd2ArgumentParser()
    ap_get_metadata.add_argument(
        "Path", help="Path whose metadata is to be read", completer=path_completer
    )

    ap_list_metadata = Cmd2ArgumentParser()
    ap_list_metadata.add_argument(
        "Pattern", help="Exact path or wildcard pattern", completer=path_completer
    )

    ap_expand = Cmd2ArgumentParser()
    ap_expand.add_argument("Pattern", help="Wildcard pattern", completer=path_completer)
    ap_expand.add_argument(
        "-t",
        "--entry-type",
        choices=[e.name for e in EntryType],
        default=None,
        help="Only list signals of this entry type",
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
        """Get the value of one or more paths"""
        client = self._require_client()
        try:
            result = client.get(args.Path if len(args.Path) > 1 else args.Path[0])
        except KuksaError as exc:
            print(f"Error: {exc}")
            return
        if isinstance(result, dict):
            self._print_json({path: dp.value for path, dp in result.items()})
        else:
            self._print_json({"value": result.value, "timestamp": result.timestamp})

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
        """Subscribe to updates of one or more paths"""
        client = self._require_client()
        if args.background:
            stream = client._subscribe_stream(args.Path)
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
            for updates in client.subscribe(args.Path):
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
    @with_argparser(ap_expand)
    def do_expand(self, args):
        """Expand a wildcard pattern into concrete signal paths"""
        client = self._require_client()
        try:
            entry_type = EntryType[args.entry_type] if args.entry_type else None
            paths = client.expand(args.Pattern, entry_type=entry_type)
            self._print_json(paths)
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
        help="Databroker to connect to. Format: grpc://host[:port] or grpcs://host[:port].",
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

    p_md = subparsers.add_parser("get-metadata", help="Get the metadata of a path")
    p_md.add_argument("path")

    p_lmd = subparsers.add_parser("list-metadata", help="List metadata matching a pattern")
    p_lmd.add_argument("pattern")

    p_exp = subparsers.add_parser("expand", help="Expand a wildcard pattern into paths")
    p_exp.add_argument("pattern")

    p_has = subparsers.add_parser("has-signal", help="Check whether a signal exists")
    p_has.add_argument("path")

    subparsers.add_parser("server-info", help="Show databroker info")

    return parser


def _open_client(args):
    srv = urlparse(args.server)
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
                result = client.get(paths if len(paths) > 1 else paths[0])
                if isinstance(result, dict):
                    print(json.dumps({p: dp.value for p, dp in result.items()}, indent=2, default=str))
                else:
                    print(json.dumps({"value": result.value, "timestamp": result.timestamp}, indent=2, default=str))
            elif command == "set":
                client.set(coerce_assignments(client, args.assignments))
            elif command == "actuate":
                client.actuate(coerce_assignments(client, args.assignments))
            elif command == "subscribe":
                for updates in client.subscribe(args.paths):
                    print(json.dumps({p: dp.value for p, dp in updates.items()}, default=str))
            elif command == "get-metadata":
                print(json.dumps(_metadata_to_dict(client.get_metadata(args.path)), indent=2))
            elif command == "list-metadata":
                print(json.dumps([_metadata_to_dict(m) for m in client.list_metadata(args.pattern)], indent=2))
            elif command == "expand":
                print("\n".join(client.expand(args.pattern)))
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
