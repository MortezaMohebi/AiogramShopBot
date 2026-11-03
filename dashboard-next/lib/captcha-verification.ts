import type { CaptchaProvider } from "./captcha-types";

/** Pure verification policy; injectable transport makes offline tests reliable. */
export interface CaptchaVerificationConfig {
  provider: CaptchaProvider;
  secretKey: string;
  expectedHostname: string;
  minimumScore: number;
}

export type CaptchaVerdict =
  | "ok"
  | "required"
  | "rejected"
  | "unavailable";

const TURNSTILE_VERIFY_URL =
  "https://challenges.cloudflare.com/turnstile/v0/siteverify";
const RECAPTCHA_VERIFY_URL =
  "https://www.google.com/recaptcha/api/siteverify";

/**
 * Verify a single-use login token with its real provider, server-side only.
 *
 * Never trust the browser's indication of success. A timeout, malformed API
 * response, mismatched hostname/action, or provider outage fails closed.
 */
export async function verifyCaptchaToken(
  config: CaptchaVerificationConfig,
  token: unknown,
  send: typeof fetch = fetch,
): Promise<CaptchaVerdict> {
  if (config.provider === "none") return "ok";

  if (!config.secretKey || !config.expectedHostname) return "unavailable";
  if (typeof token !== "string" || token.length === 0) return "required";

  const maxLength = config.provider === "turnstile" ? 2048 : 4096;
  if (token.length > maxLength || token !== token.trim()) return "rejected";

  // Both services accept URL-encoded POST bodies; no credential reaches the
  // browser, and remoteip is deliberately omitted (proxy headers are untrusted).
  const body = new URLSearchParams({
    secret: config.secretKey,
    response: token,
  });
  const endpoint = config.provider === "turnstile"
    ? TURNSTILE_VERIFY_URL
    : RECAPTCHA_VERIFY_URL;

  try {
    const response = await send(endpoint, {
      method: "POST",
      body,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(8_000),
    });
    if (!response.ok) return "unavailable";

    const decoded: unknown = await response.json();
    if (!decoded || typeof decoded !== "object" || Array.isArray(decoded)) {
      return "unavailable";
    }
    const result = decoded as Record<string, unknown>;
    if (typeof result.success !== "boolean") return "unavailable";
    if (!result.success) return "rejected";
    if (result.hostname !== config.expectedHostname) return "rejected";

    // Turnstile widgets and reCAPTCHA v3 both bind to the login action.
    if (
      (config.provider === "turnstile" ||
        config.provider === "recaptcha_v3") &&
      result.action !== "login"
    ) {
      return "rejected";
    }

    if (
      config.provider === "recaptcha_v3" &&
      (typeof result.score !== "number" ||
        !Number.isFinite(result.score) ||
        result.score < config.minimumScore ||
        result.score > 1)
    ) {
      return "rejected";
    }
    return "ok";
  } catch {
    // Network and JSON parsing errors must never become bypasses.
    return "unavailable";
  }
}
