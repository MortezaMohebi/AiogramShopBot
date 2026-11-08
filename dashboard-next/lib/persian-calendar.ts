const dateLabel = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  timeZone: "UTC", year: "numeric", month: "long", day: "numeric",
});

/** Parse a Gregorian civil form date without applying the server's timezone. */
export function parseCalendarDate(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000-")) return null;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && formatCalendarDate(date) === value ? date : null;
}

export function formatCalendarDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** Normalize an explicit ISO timestamp for the date picker without mutating the stored value. */
export function utcPickerValue(value: string): string {
  const raw = value.trim();
  if (!parseCalendarDate(raw.slice(0, 10)) || !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)) return "";
  const instant = new Date(raw);
  if (!Number.isFinite(instant.getTime())) return "";
  const result = instant.toISOString();
  return parseCalendarDate(result.slice(0, 10)) ? result : "";
}

export function persianDateLabel(date: Date): string {
  return dateLabel.format(date);
}
