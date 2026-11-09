"use server";

import { saveDraftMutation } from "@/lib/draft-mutation";

/** Modify only future merchant-funded referral rewards; never wallet balances. */
export async function saveReferralPolicy(form: FormData) {
  const percent = String(form.get("percent") ?? "0").trim();
  const minimum = String(form.get("min_order_irr") ?? "0").trim();
  const maximum = String(form.get("max_bonus_irr") ?? "0").trim();
  if (![percent, minimum, maximum].every((value) => /^\d{1,12}$/.test(value))) {
    return { ok: false, code: "validation" } as const;
  }
  return saveDraftMutation("/referral-policy", "PATCH", {
    is_enabled: form.has("is_enabled"),
    percent: Number(percent),
    min_order_irr: Number(minimum),
    max_bonus_irr: Number(maximum),
  }, "/settings");
}

/** Persist the installation name and accent chosen by the administrator. */
export async function savePwaAppearance(form: FormData) {
  const name = String(form.get("name") ?? "").trim();
  const shortName = String(form.get("short_name") ?? "").trim();
  const color = String(form.get("theme_color") ?? "");
  const version = String(form.get("version") ?? "");
  if (name.length < 2 || name.length > 80 || shortName.length < 2 || shortName.length > 24
    || !/^#[0-9a-fA-F]{6}$/.test(color) || !/^\d{1,9}$/.test(version)) {
    return { ok: false, code: "validation" } as const;
  }
  return saveDraftMutation("/pwa-settings", "PATCH", {
    name, short_name: shortName, theme_color: color, expected_version: Number(version),
  }, "/settings", "/manifest.webmanifest");
}
