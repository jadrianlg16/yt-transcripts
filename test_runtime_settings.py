import json
import os
import tempfile
import unittest

from core.runtime_settings import (
    load_mcp_settings,
    load_system_settings,
    update_mcp_settings,
    update_system_settings,
)


class RuntimeSettingsTests(unittest.TestCase):
    def test_mcp_settings_defaults_update_and_recover_from_corrupt_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "mcp_settings.json")

            defaults = load_mcp_settings(path)
            self.assertTrue(defaults["enabled"])

            updated = update_mcp_settings({"enabled": False}, path)
            self.assertFalse(updated["enabled"])
            self.assertIsNotNone(updated["updated_at"])
            self.assertEqual(load_mcp_settings(path), updated)

            with open(path, "w", encoding="utf-8") as file:
                file.write("{not-json")

            recovered = load_mcp_settings(path)
            self.assertTrue(recovered["enabled"])

    def test_system_settings_defaults_update_and_recover_from_non_object_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "system_settings.json")

            defaults = load_system_settings(path)
            self.assertFalse(defaults["ingestion_paused"])
            self.assertFalse(defaults["maintenance_mode"])

            updated = update_system_settings({
                "ingestion_paused": True,
                "maintenance_mode": True,
            }, path)
            self.assertTrue(updated["ingestion_paused"])
            self.assertTrue(updated["maintenance_mode"])
            self.assertIsNotNone(updated["updated_at"])

            with open(path, "w", encoding="utf-8") as file:
                json.dump(["bad"], file)

            recovered = load_system_settings(path)
            self.assertFalse(recovered["ingestion_paused"])
            self.assertFalse(recovered["maintenance_mode"])


if __name__ == "__main__":
    unittest.main()
