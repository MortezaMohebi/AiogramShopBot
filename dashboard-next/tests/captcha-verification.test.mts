import assert from "node:assert/strict";
import { test } from "node:test";
import {
  type CaptchaVerificationConfig,
  verifyCaptchaToken,
} from "../lib/captcha-verification.ts";

const settings: CaptchaVerificationConfig = {
  provider: "turnstile",
  secretKey: "private-test-secret",
  expectedHostname: "admin.example.com",
  minimumScore: 0.5,
};

/** Mock only the provider request; never contact live CAPTCHA services. */
function providerReply(value: unknown, status = 200): typeof fetch {
  return async () => new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

test("disabled mode preserves the original login flow", async () => {
  const unavailableNetwork: typeof fetch = async () => {
    throw new Error("The provider must not be called in none mode.");
  };
  assert.equal(
    await verifyCaptchaToken(
      { ...settings, provider: "none" },
      undefined,
      unavailableNetwork,
    ),
    "ok",
  );
});

test("enabled providers require a nonempty bounded token", async () => {
  const neverCalled: typeof fetch = async () => {
    throw new Error("Invalid tokens must not be transmitted.");
  };
  assert.equal(await verifyCaptchaToken(settings, null, neverCalled), "required");
  assert.equal(await verifyCaptchaToken(settings, "", neverCalled), "required");
  assert.equal(
    await verifyCaptchaToken(settings, "a".repeat(2049), neverCalled),
    "rejected",
  );
  assert.equal(
    await verifyCaptchaToken(settings, " token ", neverCalled),
    "rejected",
  );
});

test("Turnstile uses the official POST endpoint and binds host/action", async () => {
  let called = 0;
  const mock: typeof fetch = async (url, init) => {
    called += 1;
    assert.equal(url, "https://challenges.cloudflare.com/turnstile/v0/siteverify");
    assert.equal(init?.method, "POST");
    assert.equal(init?.cache, "no-store");
    assert.equal(init?.redirect, "error");
    assert.ok(init?.body instanceof URLSearchParams);
    assert.equal(init.body.get("secret"), settings.secretKey);
    assert.equal(init.body.get("response"), "some-token");
    assert.equal(init.body.has("remoteip"), false);
    return new Response(JSON.stringify({
      success: true, hostname: "admin.example.com", action: "login",
    }), { status: 200 });
  };
  assert.equal(await verifyCaptchaToken(settings, "some-token", mock), "ok");
  assert.equal(called, 1);
});

test("Turnstile replay, wrong hostname or action are rejected", async () => {
  for (const reply of [
    { success: false, "error-codes": ["timeout-or-duplicate"] },
    { success: true, hostname: "attacker.example", action: "login" },
    { success: true, hostname: "admin.example.com", action: "register" },
  ]) {
    assert.equal(
      await verifyCaptchaToken(settings, "some-token", providerReply(reply)),
      "rejected",
    );
  }
});

test("Google v2 checks hostname and does not require a v3 action", async () => {
  const v2 = { ...settings, provider: "recaptcha_v2" as const };
  const mock: typeof fetch = async (url, init) => {
    assert.equal(url, "https://www.google.com/recaptcha/api/siteverify");
    assert.ok(init?.body instanceof URLSearchParams);
    return new Response(JSON.stringify({
      success: true,
      hostname: "admin.example.com",
    }), { status: 200 });
  };
  assert.equal(await verifyCaptchaToken(v2, "v2-token", mock), "ok");
});

test("Google v3 requires matching action and minimum score", async () => {
  const v3 = { ...settings, provider: "recaptcha_v3" as const, minimumScore: 0.7 };
  const passing = {
    success: true, hostname: "admin.example.com", action: "login", score: 0.7,
  };
  assert.equal(
    await verifyCaptchaToken(v3, "v3-token", providerReply(passing)),
    "ok",
  );
  for (const reply of [
    { ...passing, score: 0.69 },
    { ...passing, score: undefined },
    { ...passing, score: 2 },
    { ...passing, action: "other" },
    { ...passing, hostname: "other.example.com" },
  ]) {
    assert.equal(
      await verifyCaptchaToken(v3, "v3-token", providerReply(reply)),
      "rejected",
    );
  }
});

test("outages, malformed replies and missing server keys fail closed", async () => {
  const offline: typeof fetch = async () => {
    throw new Error("offline");
  };
  assert.equal(await verifyCaptchaToken(settings, "token", offline), "unavailable");
  assert.equal(
    await verifyCaptchaToken(settings, "token", providerReply({}, 500)),
    "unavailable",
  );
  assert.equal(
    await verifyCaptchaToken(settings, "token", providerReply({ message: "hi" })),
    "unavailable",
  );
  assert.equal(
    await verifyCaptchaToken({ ...settings, secretKey: "" }, "token", offline),
    "unavailable",
  );
});
