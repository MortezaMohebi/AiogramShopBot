import "server-only";

import type { CaptchaProvider, PublicCaptchaConfig } from "@/lib/captcha-types";
import type { CaptchaVerificationConfig } from "@/lib/captcha-verification";

const PROVIDERS: readonly CaptchaProvider[] = [
  "none", "turnstile", "recaptcha_v2", "recaptcha_v3",
];

/**
 * Read secret credentials only on the server, never from NEXT_PUBLIC_ values.
 *
 * An enabled provider with incomplete or invalid configuration fails closed.
 * The hostname is derived from the trusted public origin, not request headers.
 */
export function serverCaptchaConfig(): CaptchaVerificationConfig & {
  siteKey: string;
} {
  const rawProvider = (process.env.NEXT_ADMIN_CAPTCHA_PROVIDER ?? "none").trim();
  if (!PROVIDERS.some((item) => item === rawProvider)) {
    throw new Error("Invalid CAPTCHA provider configuration.");
  }
  const provider = rawProvider as CaptchaProvider;
  if (provider === "none") {
    return {
      provider,
      siteKey: "",
      secretKey: "",
      expectedHostname: "",
      minimumScore: 0.5,
    };
  }

  const siteKey = (process.env.NEXT_ADMIN_CAPTCHA_SITE_KEY ?? "").trim();
  const secretKey = (process.env.NEXT_ADMIN_CAPTCHA_SECRET_KEY ?? "").trim();
  const originValue = process.env.NEXT_ADMIN_PUBLIC_ORIGIN ?? "";
  const rawScore = process.env.NEXT_ADMIN_RECAPTCHA_V3_MIN_SCORE ?? "0.5";
  const minimumScore = Number(rawScore);

  let origin: URL;
  try {
    origin = new URL(originValue);
  } catch {
    throw new Error("CAPTCHA requires a trusted public HTTPS origin.");
  }

  if (
    origin.protocol !== "https:" ||
    originValue !== origin.origin ||
    origin.username !== "" ||
    origin.password !== "" ||
    origin.pathname !== "/" ||
    origin.search !== "" ||
    origin.hash !== "" ||
    !/^[A-Za-z0-9_-]{8,256}$/.test(siteKey) ||
    secretKey.length === 0 ||
    /\s/.test(secretKey) ||
    (provider === "recaptcha_v3" &&
      (!Number.isFinite(minimumScore) || minimumScore < 0 || minimumScore > 1))
  ) {
    throw new Error("CAPTCHA configuration is incomplete or invalid.");
  }

  return {
    provider,
    siteKey,
    secretKey,
    expectedHostname: origin.hostname,
    minimumScore: provider === "recaptcha_v3" ? minimumScore : 0.5,
  };
}

/** Expose the selected widget and public site key, never the secret. */
export function publicCaptchaConfig(): PublicCaptchaConfig {
  try {
    const { provider, siteKey } = serverCaptchaConfig();
    return provider === "none" ? { provider } : { provider, siteKey };
  } catch {
    // Render a helpful error instead of silently disabling protection.
    return { provider: "unavailable" };
  }
}
