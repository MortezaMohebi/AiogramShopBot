/** Validate a Store label without excluding Persian joining marks. */
export function normalizeStoreName(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.normalize("NFC");
  const name = normalized.trim();
  const length = [...name].length;
  const visible = normalized.replace(/[\u200c\u200d]/gu, "");
  if (length < 2 || length > 160 || !/\p{L}/u.test(name) ||
      /[\p{C}\p{Zl}\p{Zp}]/u.test(visible)) return null;
  return name;
}
