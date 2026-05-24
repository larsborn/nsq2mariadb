#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path

# Add the tools/ directory to sys.path so we can import release.py without
# turning it into an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from release import bump_version, format_version  # noqa: E402


class TestBumpVersion(unittest.TestCase):
    def test_patch(self):
        self.assertEqual(bump_version((0, 1, 2), "patch"), (0, 1, 3))
        self.assertEqual(bump_version((1, 2, 9), "patch"), (1, 2, 10))

    def test_minor_resets_patch(self):
        self.assertEqual(bump_version((0, 1, 2), "minor"), (0, 2, 0))
        self.assertEqual(bump_version((1, 5, 17), "minor"), (1, 6, 0))

    def test_major_resets_minor_and_patch(self):
        self.assertEqual(bump_version((0, 1, 2), "major"), (1, 0, 0))
        self.assertEqual(bump_version((3, 7, 99), "major"), (4, 0, 0))

    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            bump_version((0, 1, 2), "patchh")


class TestFormatVersion(unittest.TestCase):
    def test_three_components(self):
        self.assertEqual(format_version((0, 1, 2)), "0.1.2")
        self.assertEqual(format_version((10, 20, 30)), "10.20.30")


if __name__ == "__main__":
    unittest.main()
