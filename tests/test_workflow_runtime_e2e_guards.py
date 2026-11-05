"""Exercise Runtime acceptance safety guards before any application imports."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_ENV = {
    "SHOP_TEST_LAB": "1",
    "SHOP_BETA_QA": "1",
    "CODESPACE_FRESH_SCHEMA": "true",
    "POSTGRES_DB": "shop_codespace",
    "POSTGRES_USER": "shop_codespace",
    "DB_HOST": "postgres",
    "WEBHOOK_HOST": "https://disabled.invalid",
    "NEXT_ADMIN_BRIDGE_ENABLED": "true",
    "NEXT_ADMIN_BRIDGE_SECRET": "synthetic-test-bridge-key-" + "a" * 40,
    "JWT_SECRET_KEY": "synthetic-test-session-key-" + "b" * 40,
    "SHOP_CAMPAIGN_DISPATCH_ENABLED": "false",
    "SHOP_BROADCAST_WORKER_ENABLED": "false",
    "BALE_BROADCAST_PAID_ENABLED": "false",
    "TELEGRAM_STARS_REFUNDS_ENABLED": "false",
    "TELEGRAM_STARS_CHECKOUT_ENABLED": "false",
    "TELEGRAM_FIAT_CHECKOUT_ENABLED": "false",
    "BALE_WALLET_CHECKOUT_ENABLED": "false",
    "CRYPTO_FORWARDING_MODE": "false",
    "SHOP_WALLET_MAX_ADMIN_ADJUSTMENT_IRR": "0",
    "BALE_BROADCAST_PREPARE_CHAT_ID": "0",
    "SHOP_WORKFLOW_QA": "1",
    "SHOP_ACTION_QA": "1",
    "SHOP_RUNTIME_QA": "1",
    "SHOP_WORKFLOW_RUNTIME_ENABLED": "true",
    "SHOP_WORKFLOW_RUNTIME_KILL_SWITCH": "false",
}

# This import sentinel makes a rejected environment test fail if the runner
# touches a provider factory, DB model, SDK, or HTTP client before its guards.
PROBE = """
import importlib.abc
import runpy
import sys

class RejectApplicationImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {
            'config', 'db', 'models', 'services', 'channels', 'dashboard',
            'httpx', 'aiogram', 'fastapi', 'sqlalchemy',
        }:
            raise AssertionError('unsafe_pre_guard_import:' + fullname)
        return None

sys.meta_path.insert(0, RejectApplicationImports())
try:
    runpy.run_module('scripts.workflow_runtime_e2e', run_name='__main__')
except RuntimeError as error:
    print('GUARDED:' + str(error))
else:
    raise AssertionError('unsafe_environment_not_rejected')
"""


class RuntimeAcceptanceGuardTests(unittest.TestCase):
    """Run the actual executable under deliberately unsafe process environments."""

    def assert_guarded(self, changes=None, *, optimized=False):
        """Start a clean process and require rejection before protected imports."""
        environment = {
            **BASE_ENV,
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(ROOT),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        for name, value in (changes or {}).items():
            if value is None:
                environment.pop(name, None)
            else:
                environment[name] = value
        command = [sys.executable]
        if optimized:
            command.append("-O")
        result = subprocess.run(
            [*command, "-c", PROBE],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("GUARDED:", result.stdout)
        self.assertNotIn("unsafe_pre_guard_import", result.stderr)

    def test_exact_runtime_qa_flag_is_required(self):
        """Reject missing, permissive and noncanonical Runtime QA flag values."""
        for value in (None, "", "0", "true", "TRUE", "2"):
            with self.subTest(value=value):
                self.assert_guarded({"SHOP_RUNTIME_QA": value})

    def test_optimized_python_is_refused(self):
        """Assertions cannot disappear silently from the acceptance executable."""
        self.assert_guarded(optimized=True)

    def test_named_postgresql_stack_is_required(self):
        """Reject otherwise-safe labs with the wrong global or isolated-stack flags."""
        for changes in (
            {"SHOP_BETA_QA": "0"},
            {"SHOP_WORKFLOW_RUNTIME_ENABLED": "false"},
            {"SHOP_WORKFLOW_RUNTIME_ENABLED": "TRUE"},
            {"SHOP_WORKFLOW_RUNTIME_KILL_SWITCH": "true"},
            {"POSTGRES_DB": "production"},
            {"POSTGRES_USER": "production"},
            {"DB_HOST": "database.example.org"},
            {"CODESPACE_FRESH_SCHEMA": "false"},
        ):
            with self.subTest(changes=changes):
                self.assert_guarded(changes)

    def test_provider_credentials_are_refused(self):
        """Reject any real credential even when every lab/runtime flag is correct."""
        for name in (
            "TOKEN",
            "BALE_BOT_TOKEN",
            "BALE_WALLET_PROVIDER_TOKEN",
            "TELEGRAM_FIAT_PROVIDER_TOKEN",
            "TELEGRAM_WORKER_SECRET",
            "BALE_WEBHOOK_SECRET",
            "KRYPTO_EXPRESS_API_KEY",
        ):
            with self.subTest(name=name):
                self.assert_guarded({name: "synthetic-but-forbidden-credential"})

    def test_real_receivers_and_side_effect_workers_remain_disabled(self):
        """Reject opt-in to any process capable of dispatching outside this runner."""
        for name in (
            "SHOP_CAMPAIGN_DISPATCH_ENABLED",
            "SHOP_BROADCAST_WORKER_ENABLED",
            "BALE_BROADCAST_PAID_ENABLED",
            "TELEGRAM_STARS_REFUNDS_ENABLED",
            "TELEGRAM_STARS_CHECKOUT_ENABLED",
            "TELEGRAM_FIAT_CHECKOUT_ENABLED",
            "BALE_WALLET_CHECKOUT_ENABLED",
            "SHOP_BROADCAST_REGISTRY_ENABLED",
            "MULTIBOT_V2_RUNTIME_ENABLED",
            "SHOP_DIGITAL_DELIVERY_ENABLED",
            "SHOP_CUSTOMER_NOTIFICATIONS_ENABLED",
            "SHOP_RELAY_POOL_ENABLED",
        ):
            with self.subTest(name=name):
                self.assert_guarded({name: "true"})


if __name__ == "__main__":
    unittest.main()
