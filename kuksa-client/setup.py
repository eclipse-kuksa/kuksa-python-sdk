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

try:
    from setuptools.command import build
except ImportError:
    from distutils.command import build  # pylint: disable=deprecated-module
from setuptools.command import build_py
from setuptools.command import sdist
from setuptools.command.develop import develop as _develop


class BuildGenerateProtos(setuptools.Command):
    def run(self):
        self.run_command('generate_proto')
        return super().run()


class GenerateProtosCommand(setuptools.Command):
    """Command to run proto.py script."""
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        import subprocess  # pylint: disable=import-outside-toplevel

        subprocess.call(['python', 'proto.py'])


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


class BuildCommand(BuildGenerateProtos, BuildPackageProtos, build.build):
    ...


class BuildPyCommand(BuildGenerateProtos, BuildPackageProtos, build_py.build_py):  # pylint: disable=too-many-ancestors
    ...


class SDistCommand(BuildGenerateProtos, BuildPackageProtos, sdist.sdist):
    ...


class DevelopCommand(BuildGenerateProtos, BuildPackageProtos, _develop):

    def run(self):
        self.run_command("build_pb2")
        super().run()


setuptools.setup(
    cmdclass={
        "generate_proto": GenerateProtosCommand,
        "build": BuildCommand,
        "build_pb2": BuildPackageProtosCommand,
        "build_py": BuildPyCommand,  # Used for editable installs but also for building wheels
        "sdist": SDistCommand,
        "develop": DevelopCommand,  # Also handle editable installs
    }
)
