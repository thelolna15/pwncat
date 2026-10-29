#!/usr/bin/env python3
import pytest

from pwncat.modules.linux.enumerate.system.uname import parse_kernel_revision


@pytest.mark.parametrize(
    "revision,expected",
    [
        # Standard Debian/Ubuntu style: W.X.Y-Z-arch
        ("5.10.0-19-amd64", (5, 10, 0, "19-amd64")),
        # Kali glues a non-numeric tag onto the patch number without "-"
        ("6.18.12+kali-amd64", (6, 18, 12, "+kali-amd64")),
        # No ABI suffix at all
        ("5.4.0", (5, 4, 0, "")),
        # No patch component at all
        ("6.1", (6, 1, 0, "")),
        # Non-numeric patch component
        ("5.4.x86", (5, 4, 0, "x86")),
        # 4-part W.X.Y.Z version (e.g. grsecurity-patched kernels)
        ("2.6.32.5-amd64", (2, 6, 32, "5-amd64")),
    ],
)
def test_parse_kernel_revision(revision, expected):
    assert parse_kernel_revision(revision) == expected
