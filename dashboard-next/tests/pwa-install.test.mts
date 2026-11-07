import assert from "node:assert/strict";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import manifest from "../app/manifest.ts";
import { GET as serveWorker } from "../app/sw.js/route.ts";
import { installSuggestion, mobileInstallPlatform } from "../lib/pwa-install.ts";

test("manifest installs the same private origin in a standalone window", () => {
  const app = manifest();
  assert.deepEqual(
    { id: app.id, scope: app.scope, start: app.start_url, display: app.display },
    { id: "/", scope: "/", start: "/", display: "standalone" },
  );
  assert.ok(app.icons?.some((icon) => icon.sizes === "192x192" && icon.type === "image/png"));
  assert.ok(app.icons?.some((icon) => icon.sizes === "512x512" && icon.type === "image/png"));
  assert.ok(app.icons?.some((icon) => icon.purpose === "maskable"));
  assert.ok(app.icons?.every((icon) => icon.src.startsWith("/") && !icon.src.startsWith("//")));
});

test("service worker cannot intercept or cache authenticated dashboard requests", async () => {
  const response = serveWorker();
  assert.match(response.headers.get("cache-control") ?? "", /no-store/);
  assert.match(response.headers.get("content-security-policy") ?? "", /connect-src 'none'/);
  assert.match(response.headers.get("content-type") ?? "", /application\/javascript/);
  const events: string[] = [];
  runInNewContext(await response.text(), {
    self: { addEventListener(name: string) { events.push(name); } },
  });
  assert.deepEqual(events.sort(), ["activate", "install"]);
});

test("install help is mobile-only, respects standalone and requires a native Android prompt", () => {
  const android = mobileInstallPlatform("Mozilla Android Mobile", "Linux arm", 5);
  const iphone = mobileInstallPlatform("Mozilla iPhone Safari", "iPhone", 5);
  const ipadDesktopMode = mobileInstallPlatform("Mozilla Macintosh Safari", "MacIntel", 5);
  const desktop = mobileInstallPlatform("Mozilla Macintosh Chrome", "MacIntel", 0);
  assert.equal(ipadDesktopMode, "ios");
  assert.equal(installSuggestion(android, false, false, true), "android");
  assert.equal(installSuggestion(android, false, false, false), null);
  assert.equal(installSuggestion(iphone, false, false, false), "ios");
  assert.equal(installSuggestion(iphone, true, false, false), null);
  assert.equal(installSuggestion(iphone, false, true, false), null);
  assert.equal(installSuggestion(desktop, false, false, true), null);
});
