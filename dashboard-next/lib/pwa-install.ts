export type MobileInstallPlatform = "android" | "ios";

export function mobileInstallPlatform(
  userAgent: string, platform: string, touchPoints: number,
): MobileInstallPlatform | null {
  // iPad Safari can ask for desktop pages and report a Macintosh user agent.
  if (/iPhone|iPad|iPod/i.test(userAgent) || (platform === "MacIntel" && touchPoints > 1)) {
    return "ios";
  }
  return /Android/i.test(userAgent) ? "android" : null;
}

export function installSuggestion(
  platform: MobileInstallPlatform | null, dismissed: boolean, standalone: boolean,
  hasNativePrompt: boolean,
): MobileInstallPlatform | null {
  if (dismissed || standalone) return null;
  if (platform === "android" && !hasNativePrompt) return null;
  return platform;
}
