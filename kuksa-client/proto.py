# /********************************************************************************
# * Copyright (c) 2024 Contributors to the Eclipse Foundation
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

import shutil
import os

# this needs to be adapted once the submodules name or structure changes
PROTO_PATH = os.path.abspath("../submodules/kuksa-proto/proto/")


def main():
    for root, dirs, files in os.walk(PROTO_PATH):
        for directory in dirs:
            # Create an __init__.py file in each subdirectory
            init_file = os.path.join(root, directory, "__init__.py")
            with open(init_file, "w") as file:
                file.write("# This file marks the directory as a Python module")
    shutil.copytree(PROTO_PATH, os.getcwd(), dirs_exist_ok=True)


if __name__ == "__main__":
    main()
