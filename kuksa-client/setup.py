# /********************************************************************************
# * Copyright (c) 2023 Contributors to the Eclipse Foundation
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
import setuptools
import os
import shutil

try:
    from setuptools.command import build
except ImportError:
    from distutils.command import build  # pylint: disable=deprecated-module
from setuptools.command import build_py
from setuptools.command import sdist
from setuptools.command.develop import develop as _develop

# this needs to be adapted once the submodules name or structure changes
PROTO_PATH = os.path.abspath("../submodules/kuksa-databroker/proto")


class BuildPackageProtos(setuptools.Command):
    def run(self):
        self.run_command('build_pb2')
        return super().run()


class BuildPackageProtosCommand(setuptools.Command):
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        from grpc_tools import command  # pylint: disable=import-outside-toplevel

        command.build_package_protos(".", strict_mode=True)


class BuildCommand(BuildPackageProtos, build.build):
    ...


class BuildPyCommand(BuildPackageProtos, build_py.build_py):  # pylint: disable=too-many-ancestors
    ...


class SDistCommand(BuildPackageProtos, sdist.sdist):
    ...


class DevelopCommand(BuildPackageProtos, _develop):
    def run(self):
        for root, dirs, files in os.walk(PROTO_PATH):
            for directory in dirs:
                # Create an __init__.py file in each subdirectory
                init_file = os.path.join(root, directory, "__init__.py")
                with open(init_file, "w") as file:
                    file.write("# This file marks the directory as a Python module")
        shutil.copytree(PROTO_PATH, os.getcwd(), dirs_exist_ok=True)
        self.run_command("build_pb2")
        super().run()


setuptools.setup(
    cmdclass={
        "build": BuildCommand,
        "build_pb2": BuildPackageProtosCommand,
        "build_py": BuildPyCommand,  # Used for editable installs but also for building wheels
        "sdist": SDistCommand,
        "develop": DevelopCommand,  # Also handle editable installs
    }
)
