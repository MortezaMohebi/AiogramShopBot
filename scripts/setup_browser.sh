#!/usr/bin/env bash
# Prepare the pinned browser tests, including the Linux libraries Chromium needs.
# This does not log in, run mutations, read bot credentials or start any service.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/tests/browser"

for tool in npm npx node; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf 'Missing prerequisite: %s\n' "$tool" >&2
        exit 1
    fi
done

# Use the repository's browser-test version rather than a global Playwright.
if [[ -f package-lock.json ]]; then
    npm ci --no-audit --no-fund
else
    npm install --no-audit --no-fund
fi

# Downloading Chromium alone is insufficient on the minimal Codespaces image.
# Playwright may request sudo to install its documented Linux dependencies.
npx --no-install playwright install --with-deps chromium

# Exercise the installed browser; never claim readiness from installation alone.
node --input-type=module <<'JS'
import { chromium } from "@playwright/test";
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  await page.setContent('<html lang="fa" dir="rtl"><body>آزمون مرورگر</body></html>');
  if (await page.locator('html').getAttribute('dir') !== 'rtl') {
    throw new Error('Browser readiness check failed.');
  }
} finally {
  await browser.close();
}
console.log('Chromium launched successfully. No application credentials were used.');
JS
