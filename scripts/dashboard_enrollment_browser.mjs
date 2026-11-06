/** Isolated component acceptance: synthetic account, intercepted writes, real React. */
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const directory = "dashboard-next/app/enrollment-ui-qa";
const marker = "// Owned temporary enrollment QA fixture.\n";
const base = "http://127.0.0.1:3005";
const output = "/tmp/dashboard-enrollment";
const env = Object.fromEntries(readFileSync(".codespaces/mcp-qa.env", "utf8").trim().split("\n").map(line => {
  const i = line.indexOf("="); return [line.slice(0, i), line.slice(i + 1)];
}));
assert.equal(env.SHOP_MCP_QA, "1"); assert.equal(env.SHOP_BETA_QA, "1");
for (const key of ["TOKEN", "BALE_BOT_TOKEN", "BALE_WALLET_PROVIDER_TOKEN", "TELEGRAM_FIAT_PROVIDER_TOKEN"]) assert.equal(env[key], "");

if (process.argv.includes("--cleanup")) {
  if (existsSync(directory)) {
    for (const file of ["page.tsx", "stage.tsx"]) assert(readFileSync(`${directory}/${file}`, "utf8").startsWith(marker));
    rmSync(directory, { recursive: true });
  }
  console.log("PASS removed owned temporary enrollment fixture");
} else if (process.argv.includes("--prepare")) {
  assert(!existsSync(directory)); mkdirSync(directory);
  writeFileSync(`${directory}/page.tsx`, marker + `import { notFound } from "next/navigation";
import { EnrollmentStage } from "./stage";
export default function Page() {
  if (process.env.SHOP_MCP_QA !== "1" || process.env.SHOP_BETA_QA !== "1") notFound();
  return <EnrollmentStage />;
}
`);
  writeFileSync(`${directory}/stage.tsx`, marker + `"use client";
import { useEffect, useRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import Link from "next/link";
import { Providers } from "@/components/providers";
import { ThemeToggle } from "@/components/blocks/theme-toggle";
import { AccountPanel } from "@/components/blocks/account-panel";
import type { AccountData } from "@/lib/account-control";
const account: AccountData = {
 username: "qa.synthetic", role: "superadmin", display_name: "", time_zone: "Asia/Tehran",
 mfa_enabled: false, mfa_required_by_role: true,
 password_policy: {min_length:14,require_upper:true,require_lower:true,require_digit:true,require_symbol:true},
 preferences: {language:"fa",calendar:"auto",notify_orders:true,notify_campaigns:true,notify_finance:true,notify_system:true},
 sessions:[],permissions:["account.manage_self"],events:[]
};
export function EnrollmentStage() {
 const host = useRef<HTMLDivElement>(null), root = useRef<Root | null>(null);
 useEffect(() => () => {const mounted = root.current; queueMicrotask(() => mounted?.unmount());}, []);
 function mount() {
  root.current?.unmount(); root.current = createRoot(host.current!);
  root.current.render(<Providers><p>Client Theme ready</p><ThemeToggle /></Providers>);
 }
 return <main className="mx-auto max-w-3xl space-y-6 px-4 py-8">
  <header className="flex items-center justify-between gap-3"><h1 className="text-2xl font-bold">حساب من</h1><ThemeToggle /></header>
  <AccountPanel initial={account} />
  <section className="space-y-3 border-t pt-4" aria-label="Synthetic QA controls">
   <button onClick={mount}>Mount fresh Theme provider</button><div ref={host} />
   <Link href="/login">Login navigation</Link>
  </section>
 </main>;
}
`);
  console.log("PASS prepared guarded synthetic enrollment fixture");
} else {
  mkdirSync(output, { recursive: true });
  const evidence = { status: "RUNNING", scope: "production AccountPanel and Providers; synthetic account; intercepted account writes; no real account proof", checks: [], errors: [], screenshots: [], real_mutations: 0 };
  const save = () => writeFileSync(output + "/evidence.json", JSON.stringify(evidence, null, 2));
  const check = (name, theme) => { evidence.checks.push({ name, theme, status: "PASS" }); save(); };
  async function capture(page, name) { await page.screenshot({ path: `${output}/${name}.png` }); evidence.screenshots.push(name + ".png"); save(); }
  let browser;
  try {
    const { chromium } = await import(pathToFileURL(process.env.WORKFLOW_PLAYWRIGHT_MODULE).href);
    browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] }); evidence.browser = browser.version();
    for (const theme of ["light", "dark"]) {
      const context = await browser.newContext({ viewport: { width: 390, height: 900 }, colorScheme: theme, reducedMotion: "reduce", serviceWorkers: "block" });
      await context.addInitScript(value => localStorage.setItem("theme", value), theme);
      let setup = false, confirmation = false;
      await context.route("**/*", async route => {
        const request = route.request(), url = new URL(request.url());
        if (url.origin !== base) return route.abort();
        if (url.pathname === "/api/auth/challenge") return route.fulfill({ contentType: "application/json", body: JSON.stringify({ ok: true, challenge: "C".repeat(43) }) });
        if (url.pathname.startsWith("/api/account/")) {
          assert.equal(request.method(), "POST"); assert.equal(request.headers()["x-shop-login-challenge"], "C".repeat(43));
          const body = request.postDataJSON();
          if (url.pathname === "/api/account/mfa-setup") {
            assert.equal(body.current_password, "SYNTHETIC-ONLY-password-123"); setup = true;
            return route.fulfill({ contentType: "application/json", body: JSON.stringify({ ok: true, secret: "SYNTHETIC-ONLY-NOT-A-REAL-TOTP-KEY", qr_data_uri: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=" }) });
          }
          if (url.pathname === "/api/account/mfa-confirm") {
            assert.equal(body.code, "123456"); confirmation = true;
            return route.fulfill({ contentType: "application/json", body: JSON.stringify({ ok: true, recovery_codes: ["SYNTHETIC-RECOVERY-ONLY"] }) });
          }
          evidence.real_mutations++; return route.abort();
        }
        if (!["GET", "HEAD"].includes(request.method())) { evidence.real_mutations++; return route.abort(); }
        if (url.pathname.startsWith("/api/")) return route.abort();
        return route.continue();
      });
      const page = await context.newPage(); page.setDefaultNavigationTimeout(60_000);
      page.on("pageerror", error => evidence.errors.push(error.message));
      page.on("console", message => { if (message.type() === "error") evidence.errors.push(message.text()); });
      await page.goto(base + "/enrollment-ui-qa");
      const toggle = page.getByRole("button", { name: "تغییر حالت روشن و تاریک", exact: true });
      await toggle.waitFor(); await toggle.click();
      await page.waitForFunction(value => document.documentElement.classList.contains(value), theme === "dark" ? "light" : "dark");
      await toggle.click(); await page.waitForFunction(value => document.documentElement.classList.contains(value), theme);
      assert.equal(await page.getByRole("button", { name: "ذخیره مشخصات", exact: true }).count(), 0);
      assert.equal(await page.locator('[name="new_password"]').count(), 0);
      for (const width of [1440, 768, 390, 320]) {
        await page.setViewportSize({ width, height: 900 });
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
        await capture(page, `enrollment-${theme}-${width}`);
      }
      check("initial hydration; theme switching; enrollment-only controls; RTL at four widths", theme);
      for (let attempt = 0; attempt < 2; attempt++) {
        await page.getByRole("button", { name: "Mount fresh Theme provider", exact: true }).click();
        await page.getByText("Client Theme ready", { exact: true }).waitFor();
        assert.equal(await page.getByRole("button", { name: "تغییر حالت روشن و تاریک", exact: true }).count(), 2);
      }
      check("fresh independent client roots remount without script or Performance errors", theme);
      await page.getByLabel("رمز فعلی", { exact: true }).fill("SYNTHETIC-ONLY-password-123");
      await page.getByRole("button", { name: "شروع فعال‌سازی MFA", exact: true }).click();
      await page.getByRole("img", { name: "QR Code فعال‌سازی احراز هویت دومرحله‌ای", exact: true }).waitFor(); assert(setup);
      await page.getByLabel("کد تأیید", { exact: true }).fill("123456");
      await page.getByRole("button", { name: "تأیید و فعال‌سازی", exact: true }).click();
      await page.getByText("SYNTHETIC-RECOVERY-ONLY", { exact: true }).waitFor(); assert(confirmation);
      await page.getByRole("button", { name: "پنهان کردن کدها", exact: true }).click();
      assert.equal(await page.getByText("SYNTHETIC-RECOVERY-ONLY", { exact: true }).count(), 0);
      check("synthetic setup/confirmation and recovery display use intercepted actions only", theme);
      await page.getByRole("link", { name: "Login navigation", exact: true }).click();
      await page.getByLabel("نام کاربری", { exact: true }).waitFor();
      check("App Router navigation remains usable after independent root mounts", theme);
      await context.close();
    }
    assert.equal(evidence.real_mutations, 0); assert.deepEqual(evidence.errors, []);
    evidence.status = "PASS"; console.log(`PASS enrollment/theme: ${evidence.checks.length} checks; ${evidence.screenshots.length} captures; zero real auth writes`);
  } catch (error) {
    evidence.status = "FAIL"; evidence.failure = { name: error.name, message: String(error.message).slice(0, 1500) };
    console.error(evidence.failure); process.exitCode = 1;
  } finally { if (browser) await browser.close(); evidence.browser_cleanup = "PASS"; save(); }
}
