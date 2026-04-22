"""Tests for Comelit control discovery helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "comelit_intercom"
    / "control_discovery.py"
)
SPEC = importlib.util.spec_from_file_location("control_discovery", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
CONTROL_DISCOVERY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTROL_DISCOVERY)

extract_controls_from_vip = CONTROL_DISCOVERY.extract_controls_from_vip


class ExtractControlsFromVipTests(unittest.TestCase):
    """Verify that controls are discovered from multiple address books."""

    def test_merges_actuator_rows_split_across_multiple_lists(self) -> None:
        vip_config = {
            "user-parameters": {
                "opendoor-address-book": [
                    {
                        "name": "Entrance lock",
                        "apt-address": "SB100001",
                        "output-index": 1,
                    }
                ],
                "actuator-address-book": [
                    {
                        "name": "Secondary relay",
                        "apt-address": "SBIO0255",
                    }
                ],
                "additional-actuator-address-book": [
                    {
                        "apt-address": "SBIO0255",
                        "output-index": 255,
                    }
                ],
            }
        }

        controls = extract_controls_from_vip(vip_config)

        self.assertEqual(len(controls), 2)
        self.assertIn(
            {
                "name": "Entrance lock",
                "apt-address": "SB100001",
                "output-index": 1,
            },
            controls,
        )
        self.assertIn(
            {
                "name": "Secondary relay",
                "apt-address": "SBIO0255",
                "output-index": 255,
            },
            controls,
        )

    def test_deduplicates_controls_with_same_address_and_output(self) -> None:
        vip_config = {
            "user-parameters": {
                "opendoor-address-book": [
                    {
                        "name": "Entrance lock",
                        "apt-address": "SB100001",
                        "output-index": 1,
                    }
                ],
                "actuator-address-book": [
                    {
                        "name": "Secondary relay",
                        "apt-address": "SBIO0255",
                        "output-index": 255,
                    }
                ],
                "additional-actuator-address-book": [
                    {
                        "name": "Secondary relay",
                        "apt-address": "SBIO0255",
                        "output-index": 255,
                    }
                ],
            }
        }

        controls = extract_controls_from_vip(vip_config)

        self.assertEqual(len(controls), 2)

    def test_falls_back_to_actuator_address_suffix_for_output_index(self) -> None:
        vip_config = {
            "user-parameters": {
                "actuator-address-book": [
                    {
                        "name": "Garage relay",
                        "apt-address": "SBIO0255",
                    }
                ]
            }
        }

        controls = extract_controls_from_vip(vip_config)

        self.assertEqual(
            controls,
            [
                {
                    "name": "Garage relay",
                    "apt-address": "SBIO0255",
                    "output-index": 255,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
