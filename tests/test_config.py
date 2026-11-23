import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ysudoku import cli, llm, store
from ysudoku.config import apply_config, read_config
from ysudoku.service_limits import Limits


class ConfigurationTest(unittest.TestCase):
    def test_template_covers_every_setting_in_schema(self):
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "ysudoku/config_schema.json").read_text())
        options = {env_name for section in schema.values() for env_name, _ in section.values()}
        self.assertEqual(set(read_config(root / "docs/config.toml.example")), options)
        self.assertNotIn("SUDOKU_LLM_API_KEY", options)

    def test_toml_controls_runtime_and_cli_can_override_bind_address(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "YSUDOKU_HTTP_PORT": "8000",
            "YSUDOKU_STORE": "/old-store",
            "SUDOKU_LLM_API_KEY": "test-key",
        }), patch("ysudoku.server.run") as run:
            config = Path(tmp) / "test.toml"
            config.write_text("""
[server]
port = 5222
[llm]
enabled = false
daily_input_tokens = 321
[network]
trusted_proxies = ["127.0.0.1", "10.0.0.0/8"]
[storage]
store_dir = ""
max_mb = 250
""")
            self.assertEqual(cli.main(["--web", "--config", str(config), "--port", "5444"]), 0)
            run.assert_called_once_with("127.0.0.1", 5444)
            self.assertNotIn("YSUDOKU_STORE", os.environ)
            self.assertIsNone(llm.LLMConfig.from_env())
            self.assertEqual(Limits(tmp).input_limit, 321)

    def test_invalid_or_secret_fields_report_only_the_field(self):
        with TemporaryDirectory() as tmp:
            config = Path(tmp) / "bad.toml"
            config.write_text('[limits]\ndaily_solves_per_ip = "bad"\n')
            with self.assertRaisesRegex(ValueError, r"limits\.daily_solves_per_ip .*integer"):
                read_config(config)
            config.write_text('[llm]\napi_key = "secret-value"\n')
            with self.assertRaisesRegex(ValueError, r"^Unknown configuration key llm\.api_key$"):
                read_config(config)

    def test_web_overrides_are_ignored_when_disabled_and_preserved(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "YSUDOKU_STORE": tmp,
            "YSUDOKU_STORAGE_MAX_MB": "600",
            "YSUDOKU_ALLOW_STORAGE_SETTINGS": "1",
        }):
            store.save_settings(max_mb=700, max_frames=100)
            path = Path(tmp) / "settings.json"
            self.assertEqual(json.loads(path.read_text()), {"max_mb": 700})
            self.assertEqual(store.storage_info()["settings_overrides"], ["max_mb"])
            apply_config({"YSUDOKU_ALLOW_STORAGE_SETTINGS": "0"})
            self.assertEqual(store.load_settings()["max_mb"], 600)
            self.assertEqual(store.storage_info()["settings_overrides"], [])
            self.assertEqual(json.loads(path.read_text()), {"max_mb": 700})
            apply_config({"YSUDOKU_ALLOW_STORAGE_SETTINGS": "1"})
            self.assertEqual(store.load_settings()["max_mb"], 700)
            store.save_settings(max_mb=600)
            self.assertEqual(json.loads(path.read_text()), {})
