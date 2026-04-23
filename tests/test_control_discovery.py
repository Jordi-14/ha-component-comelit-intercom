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

CONTROL_TYPE_ACTUATOR = CONTROL_DISCOVERY.CONTROL_TYPE_ACTUATOR
CONTROL_TYPE_OPENDOOR = CONTROL_DISCOVERY.CONTROL_TYPE_OPENDOOR
control_identity = CONTROL_DISCOVERY.control_identity
extract_controls_from_vip = CONTROL_DISCOVERY.extract_controls_from_vip


class ExtractControlsFromVipTests(unittest.TestCase):
    """Verify that controls are discovered from the expected address books."""

    def test_preserves_actuator_metadata(self) -> None:
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
                        "module-index": 255,
                        "output-index": 1,
                    }
                ],
                "additional-actuator": [
                    {
                        "enabled": True,
                        "apt-address": "SBIO0255",
                        "module-index": 255,
                        "output-index": 1,
                    }
                ],
            }
        }

        controls = extract_controls_from_vip(vip_config)

        self.assertEqual(len(controls), 2)
        self.assertIn(
            {
                "control-type": CONTROL_TYPE_OPENDOOR,
                "name": "Entrance lock",
                "apt-address": "SB100001",
                "output-index": 1,
                "secure-mode": False,
            },
            controls,
        )
        self.assertIn(
            {
                "control-type": CONTROL_TYPE_ACTUATOR,
                "name": "Secondary relay",
                "apt-address": "SBIO0255",
                "module-index": 255,
                "output-index": 1,
                "enabled": True,
            },
            controls,
        )

    def test_merges_additional_actuator_data_when_primary_entry_is_incomplete(self) -> None:
        vip_config = {
            "user-parameters": {
                "actuator-address-book": [
                    {
                        "name": "Garage relay",
                        "apt-address": "SBIO0255",
                    }
                ],
                "additional-actuator": [
                    {
                        "enabled": True,
                        "apt-address": "SBIO0255",
                        "module-index": 255,
                        "output-index": 1,
                    }
                ],
            }
        }

        controls = extract_controls_from_vip(vip_config)

        self.assertEqual(
            controls,
            [
                {
                    "control-type": CONTROL_TYPE_ACTUATOR,
                    "name": "Garage relay",
                    "apt-address": "SBIO0255",
                    "module-index": 255,
                    "output-index": 1,
                    "enabled": True,
                }
            ],
        )

    def test_matches_additional_actuators_by_address_when_lists_are_misaligned(self) -> None:
        vip_config = {
            "user-parameters": {
                "actuator-address-book": [
                    {
                        "name": "Garage relay",
                        "apt-address": "SBIO0255",
                    },
                    {
                        "name": "Gate relay",
                        "apt-address": "SBIO0256",
                    },
                ],
                "additional-actuator": [
                    {
                        "enabled": True,
                        "apt-address": "SBIO0256",
                        "module-index": 256,
                        "output-index": 2,
                    },
                    {
                        "enabled": True,
                        "apt-address": "SBIO0255",
                        "module-index": 255,
                        "output-index": 1,
                    },
                ],
            }
        }

        controls = extract_controls_from_vip(vip_config)

        self.assertEqual(
            controls,
            [
                {
                    "control-type": CONTROL_TYPE_ACTUATOR,
                    "name": "Garage relay",
                    "apt-address": "SBIO0255",
                    "module-index": 255,
                    "output-index": 1,
                    "enabled": True,
                },
                {
                    "control-type": CONTROL_TYPE_ACTUATOR,
                    "name": "Gate relay",
                    "apt-address": "SBIO0256",
                    "module-index": 256,
                    "output-index": 2,
                    "enabled": True,
                },
            ],
        )

    def test_control_identity_distinguishes_door_and_actuator_entries(self) -> None:
        door = {
            "control-type": CONTROL_TYPE_OPENDOOR,
            "name": "Entrance lock",
            "apt-address": "SB100001",
            "output-index": 1,
        }
        actuator = {
            "control-type": CONTROL_TYPE_ACTUATOR,
            "name": "Entrance lock",
            "apt-address": "SB100001",
            "output-index": 1,
            "module-index": 255,
        }

        self.assertNotEqual(control_identity(door), control_identity(actuator))


if __name__ == "__main__":
    unittest.main()
