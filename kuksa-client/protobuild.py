# /********************************************************************************
# * Copyright (c) 2025 Contributors to the Eclipse Foundation
# *
# * See the NOTICE file(s) distributed with this work for additional
# * information regarding copyright ownership.
# *
# * This program and the accompanying materials are made available under the
# * terms of the Apache License 2.0 which is available at
# * http://www.apache.org/licenses/LICENSE-2.0
# *
# * SPDX-License-Identifier: Apache-2.0
# ********************************************************************************/

from grpc_tools import command

# Helper to compile all protos in cwd


def main():
    print("Compiling protobuf files...")
    command.build_package_protos(".", strict_mode=True)


if __name__ == "__main__":
    main()
