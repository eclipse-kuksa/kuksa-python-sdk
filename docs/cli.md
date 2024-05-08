# Using the Command Line Interface (CLI)

After you have installed the kuksa-client package via pip you can run the test client CLI directly by executing:

```console
kuksa-client
```

With default CLI arguments, the client will try to connect to a local Databroker, e.g. a server supporting the `kuksa.val.v1` protocol without using TLS. This is equivalent to executing

```console
kuksa-client grpc://127.0.0.1:55555
```


If everything works as expected and the server can be contacted you will get an output similar to below.


```console
Welcome to Kuksa Client version <some_version>

                  `-:+o/shhhs+:`
                ./oo/+o/``.-:ohhs-
              `/o+-  /o/  `..  :yho`
              +o/    /o/  oho    ohy`
             :o+     /o/`+hh.     sh+
             +o:     /oo+o+`      /hy
             +o:     /o+/oo-      +hs
             .oo`    oho `oo-    .hh:
              :oo.   oho  -+:   -hh/
               .+o+-`oho     `:shy-
                 ./o/ohy//+oyhho-
                    `-/+oo+/:.

Default tokens directory: /some/path/kuksa_certificates/jwt

Connecting to VSS server at 127.0.0.1 port 55555 using KUKSA GRPC protocol.
TLS will not be used.
INFO 2023-09-15 18:48:13,415 kuksa_client.grpc No Root CA present, it will not be posible to use a secure connection!
INFO 2023-09-15 18:48:13,415 kuksa_client.grpc.aio Establishing insecure channel
gRPC channel connected.
Test Client>
```

If you wish to connect to a VISS server e.g. `kuksa-val-server` (not using TLS), you should instead run:

```console
kuksa-client ws://127.0.0.1:8090
```

## Logging

The log level of `kuksa-client` can be set using the LOG_LEVEL environment variable. The following levels are supported

* `error`
* `warning`
* `info` (default)
* `debug`


To set the log level to DEBUG

```console
$ LOG_LEVEL=debug kuksa-client
```

It is possible to control log level in detail.
The example below sets log level to DEBUG, but for asyncio INFO.

```console
$ LOG_LEVEL=debug,asyncio=info kuksa-client
```

## TLS with databroker

KUKSA Client uses TLS to connect to Databroker when the schema part of the server URI is `grpcs`.
The KUKSA Python SDK does not include any default certificates or keys.
The root certificate used to authenticate the Databroker must be specified with `--cacertificate <path>`.
If you want to use KUKSA example Root CA you need to provide it from [kuksa-common](https://github.com/eclipse-kuksa/kuksa-common/tree/main/tls).


```
kuksa-client --cacertificate ~/kuksa-common/tls/CA.pem grpcs://localhost:55555
```

The example server protocol list 127.0.0.1 as an alternative name, but the TLS-client currently used does not accept it,
instead a valid server name must be given as argument.
Currently `Server` and `localhost` are valid names from the example certificates.

```
kuksa-client --cacertificate ~/kuksa-common/tls/CA.pem --tls-server-name Server grpcs://127.0.0.1:55555
```

## TLS with Websocket
Websocket access also supports TLS. KUKSA Client uses TLS to connect to Weboscket when the schema part of the server URI is `wss`.  A valid command to connect to a local TLS enabled VSS Server (KUKSA Databroker, VISSR, ...) supporting Websocket is


```
kuksa-client --cacertificate ~/kuksa-common/tls/CA.pem wss://localhost:8090
```

In some environments the `--tls-server-name` argument must be used to specify alternative server name
if connecting to the server by numerical IP address like `wss://127.0.0.1:8090`.

## Authorizing against KUKSA Server

If the connected KUKSA Server or KUKSA Databroker require authorization the first step after a connection is made is to authorize. KUKSA Server and KUKSA Databroker use different token formats.

The KUKSA jwt tokens for testing can be found in the [kuksa-common repository](https://github.com/eclipse/kuksa.val/tree/master/kuksa_certificates/jwt).

Select one of the tokens and use the `authorize` command like below:

```console
Test Client> authorize /some/path/kuksa_certificates/jwt/super-admin.json.token
```

## Authorizing against KUKSA Databroker

If the KUKSA Databroker use default example tokens then one of the
tokens in [kuksa-common](https://github.com/eclipse-kuksa/kuksa-common/tree/main/jwt) can be used, like in the example below:

```console
Test Client> authorize /some/path/jwt/provide-all.token
```

## Usage Instructions

Refer help for further information

```console
Test Client> help -v

Documented commands (use 'help -v' for verbose/'help <topic>' for details):

Communication Set-up Commands
================================================================================
authorize           Authorize the client to interact with the server
connect             Connect to a VSS server
disconnect          Disconnect from the VISS/gRPC Server
getServerAddress    Gets the IP Address for the VISS/gRPC Server

Info Commands
================================================================================
info                Show summary info of the client
version             Show version of the client

Kuksa Interaction Commands
================================================================================
getMetaData          Get MetaData of the path
getTargetValue       Get the value of a path
getTargetValues      Get the value of given paths
getValue             Get the value of a path
getValues            Get the value of given paths
setTargetValue       Set the target value of a path
setTargetValues      Set the target value of given paths
setValue             Set the value of a path
setValues            Set the value of given paths
subscribe            Subscribe the value of a path
subscribeMultiple    Subscribe to updates of given paths
unsubscribe          Unsubscribe an existing subscription
updateMetaData       Update MetaData of a given path
updateVSSTree        Update VSS Tree Entry

```

This is an example showing how some of the commands can be used:

![try kuksa-client out](https://raw.githubusercontent.com/eclipse/kuksa.val/master/doc/pictures/testclient_basic.gif "test client usage")

## Syntax for specifying data in the command line interface

Values used as argument to for example `setValue` shall match the type given. Quotes (single and double) are
generally not needed, except in a few special cases. A few valid examples on setting float is shown below:

```
setValue Vehicle.Speed 43
setValue Vehicle.Speed "45"
setValue Vehicle.Speed '45.2'
```

For strings escaped quotes are needed if you want quotes to be sent to Server/Databroker, like if you want to store
`Almost "red"` as value. Alternatively you can use outer single quotes and inner double quotes.

*NOTE: KUKSA Server and Databroker currently handle (escaped) quotes in strings differently!*
*The behavior described below is in general correct for KUKSA Databroker, but result may be different if interacting with KUKSA Server!*
*For consistent behavior it is recommended not to include (escaped) quotes in strings, except when needed to separate values*

The two examples below are equal:

```
setValue Vehicle.Cabin.Light.InteractiveLightBar.Effect 'Almost \"red\"'
setValue Vehicle.Cabin.Light.InteractiveLightBar.Effect 'Almost "red"'
```

Alternatively you can use inner single quotes, but then the value will be represented by double quotes (`Almost "blue"`)
when stored anyhow.

```
setValue Vehicle.Cabin.Light.InteractiveLightBar.Effect "Almost 'blue'"
setValue Vehicle.Cabin.Light.InteractiveLightBar.Effect "Almost \'blue\'"
```

If not using outer quotes the inner quotes will be lost, the examples below are equal.
Leading/trailing spaces are ignored.

```
setValue Vehicle.Cabin.Light.InteractiveLightBar.Effect Almost 'green'
setValue Vehicle.Cabin.Light.InteractiveLightBar.Effect Almost green
setValue Vehicle.Cabin.Light.InteractiveLightBar.Effect 'Almost green'
setValue Vehicle.Cabin.Light.InteractiveLightBar.Effect "Almost green"
setValue Vehicle.Cabin.Light.InteractiveLightBar.Effect 'Almost green         '
```

It is possible to set array values. In general the value should be a valid JSON representation of the array.
For maximum compatibility for both KUKSA Server and KUKSA Databroker the following recommendations applies:

* Always use single quotes around the array value. For some cases, like if there is no blanks or comma in the value, it is not needed, but it is good practice.
* Always use double quotes around string values.
* Never use single quotes inside string values
* Double quotes inside string values are allowed but must be escaped (`\"`)

Some examples supported by both KUKSA databroker and KUKSA Server are shown below

Setting a string array in KUKSA Databroker with simple identifiers is not a problem.
Also not if they contain blanks

```
// Array with two string elements
setValue Vehicle.OBD.DTCList '["abc","def"]'
// Array with two int elements (Note no quotes)
setValue Vehicle.SomeInt '[123,456]'
// Array with two elements, "hello there" and "def"
setValue Vehicle.OBD.DTCList '["hello there","def"]'
// Array with doubl quotes in string value; hello "there"
setValue Vehicle.OBD.DTCList '["hello, \"there\"","def"]'
```

## Updating VSS Structure

Using the test client, it is also possible to update and extend the VSS data structure.
More details can be found [here](https://github.com/eclipse/kuksa.val/blob/master/doc/KUKSA.val_server/liveUpdateVSSTree.md).

**Note**: You can also use `setValue` to change the value of an array, but the value should not contains any non-quoted spaces. Consider the following examples:

```console
Test Client> setValue Vehicle.OBD.DTCList ["dtc1","dtc2"]
{
    "action": "set",
    "requestId": "f7b199ce-4d86-4759-8d9a-d6f8f935722d",
    "ts": "2022-03-22T17:19:34.1647965974Z"
}

Test Client> setValue Vehicle.OBD.DTCList '["dtc1", "dtc2"]'
{
    "action": "set",
    "requestId": "d4a19322-67d8-4fad-aa8a-2336404414be",
    "ts": "2022-03-22T17:19:44.1647965984Z"
}

Test Client> setValue Vehicle.OBD.DTCList ["dtc1", "dtc2"]
usage: setValue [-h] Path Value
setValue: error: unrecognized arguments: dtc2 ]
```
