/** CAPTCHA settings shared between the server and the login form. */
export type CaptchaProvider =
  | "none"
  | "turnstile"
  | "recaptcha_v2"
  | "recaptcha_v3";

/** A misconfigured provider stays visible but can never bypass validation. */
export type PublicCaptchaConfig =
  | { provider: "none" }
  | { provider: "unavailable" }
  | {
      provider: Exclude<CaptchaProvider, "none">;
      siteKey: string;
    };
