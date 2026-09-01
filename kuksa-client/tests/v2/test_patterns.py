# /********************************************************************************
# * Copyright (c) 2026 Contributors to the Eclipse Foundation
# *
# * SPDX-License-Identifier: Apache-2.0
# ********************************************************************************/

import pytest

from kuksa_client.v2 import patterns


@pytest.mark.parametrize(
    "pattern, path, expected",
    [
        ("", "Vehicle.Speed", True),
        ("Vehicle", "Vehicle.Speed", True),
        ("Vehicle", "Vehicle.Cabin.Sunroof.Position", True),
        ("Vehicle.Speed", "Vehicle.Speed", True),
        ("Vehicle.Speed", "Vehicle.SpeedX", False),
        ("Vehicle.Cabin.Sunroof", "Vehicle.Cabin.Sunroof.Position", True),
        ("Vehicle.Cabin.Sunroof.**", "Vehicle.Cabin.Sunroof.Position", True),
        ("Vehicle.Cabin.Sunroof.**", "Vehicle.Cabin.Sunroof.Shade.Switch", True),
        ("Vehicle.Cabin.Sunroof.*", "Vehicle.Cabin.Sunroof.Position", True),
        ("Vehicle.Cabin.Sunroof.*", "Vehicle.Cabin.Sunroof.Shade.Position", False),
        ("Vehicle.Cabin.Sunroof.*.Position", "Vehicle.Cabin.Sunroof.Shade.Position", True),
        ("**.Sunroof.*.Position", "Vehicle.Cabin.Sunroof.Shade.Position", True),
        ("*.*.*.*.Position", "Vehicle.Cabin.Sunroof.Shade.Position", True),
        ("Vehicle.Cabin.Sunroof.**.Position", "Vehicle.Cabin.Sunroof.Position", True),
        ("Vehicle.Cabin.Sunroof.**.Position", "Vehicle.Cabin.Sunroof.Shade.Position", True),
        ("**.Sunroof", "Vehicle.Cabin.Sunroof.Position", False),
        ("*.Sunroof", "Vehicle.Cabin.Sunroof.Position", False),
        ("Sunroof", "Vehicle.Cabin.Sunroof.Position", False),
        ("**.Sunroof.**", "Vehicle.Cabin.Sunroof.Shade.Switch", True),
    ],
)
def test_matches(pattern, path, expected):
    assert patterns.matches(pattern, path) == expected


@pytest.mark.parametrize(
    "pattern, prefix",
    [
        ("", ""),
        ("Vehicle", "Vehicle"),
        ("Vehicle.Speed", "Vehicle.Speed"),
        ("Vehicle.*.Position", "Vehicle"),
        ("Vehicle.Cabin.Sunroof.**", "Vehicle.Cabin.Sunroof"),
        ("**.TyrePressure", ""),
        ("*.Sunroof", ""),
    ],
)
def test_literal_prefix(pattern, prefix):
    assert patterns.literal_prefix(pattern) == prefix


def test_double_star_with_consecutive_star_unsupported():
    with pytest.raises(ValueError):
        patterns.matches("**.*.*.*.Position", "Vehicle.Cabin.Door.Position")
