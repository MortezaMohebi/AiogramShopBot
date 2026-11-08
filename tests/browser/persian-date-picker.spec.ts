import { AxeBuilder } from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { signIn } from "./lab-auth.js";

test.use({ timezoneId: "Asia/Tehran" });

test("audit dates use the Persian calendar and survive submission and paging", async ({ page }, testInfo) => {
  await page.emulateMedia({ colorScheme: testInfo.project.name === "mobile-320" ? "dark" : "light" });
  await signIn(page, "labadmin", process.env.LAB_ADMIN_PASSWORD!);
  await page.goto("/audit?since=2025-03-20&page=2");
  await page.getByRole("link", { name: "قبلی", exact: true }).click();
  await expect(page).toHaveURL((url) => url.searchParams.get("since") === "2025-03-20");

  const start = page.getByRole("button", { name: /^از تاریخ/ });
  await expect(start).toContainText("اسفند", { timeout: 4000 });
  // Click the empty end of the field, away from its text.
  await start.scrollIntoViewIfNeeded();
  const field = await start.boundingBox();
  await start.click({ position: { x: field!.width / 2, y: field!.height / 2 } });
  const calendar = page.getByRole("dialog", { name: "از تاریخ" });
  await expect(calendar).toBeVisible();
  const panel = await calendar.boundingBox();
  expect(Math.min(
    Math.abs(panel!.y - field!.y - field!.height),
    Math.abs(field!.y - panel!.y - panel!.height),
  )).toBeLessThanOrEqual(12);
  await expect(calendar.getByRole("button", { name: /۱۴۰۳ اسفند ۳۰/ })).toBeFocused();
  const box = await calendar.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  const colors = await calendar.evaluate((element) => ({
    actual: getComputedStyle(element).backgroundColor,
    dark: document.documentElement.classList.contains("dark"),
  }));
  expect(colors).toEqual(testInfo.project.name === "mobile-320"
    ? { actual: "rgb(23, 31, 41)", dark: true }
    : { actual: "rgb(255, 255, 255)", dark: false });
  const results = await new AxeBuilder({ page }).include('[role="dialog"]')
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(results.violations).toEqual([]);

  await page.keyboard.press("ArrowLeft");
  await expect(calendar.getByRole("button", { name: /۱۴۰۴ فروردین ۱(?![۰-۹])/ })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(start).toBeFocused();
  await expect(start).toContainText("اسفند");
  await start.click();
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("Enter");
  await expect(start).toContainText("فروردین");
  await page.getByRole("button", { name: "اعمال فیلترها" }).click();
  await expect(page).toHaveURL((url) => url.searchParams.get("since") === "2025-03-21");

  await start.click();
  await calendar.getByRole("button", { name: "انتخاب ماه", exact: true }).click();
  await expect(calendar.getByRole("group", { name: "ماه‌ها" })).toBeVisible();
  await calendar.getByRole("button", { name: "انتخاب سال", exact: true }).click();
  await calendar.getByRole("button", { name: "۱۴۰۵", exact: true }).click();
  await calendar.getByRole("button", { name: "آبان", exact: true }).click();
  await calendar.getByRole("button", { name: /۱۴۰۵ آبان ۱۷(?![۰-۹])/ }).click();
  await expect(page.locator('input[name="since"]')).toHaveValue("2026-11-08");

  const end = page.getByRole("button", { name: /^تا تاریخ/ });
  await end.click();
  const endCalendar = page.getByRole("dialog", { name: "تا تاریخ" });
  await endCalendar.getByRole("button", { name: "امروز", exact: true }).click();
  await expect(end).toBeFocused();
  await page.getByRole("button", { name: "پاک‌کردن تاریخ: تا تاریخ", exact: true }).click();
  await expect(end).toContainText("انتخاب تاریخ");
  await expect(end).toBeFocused();

  await page.goto("/coupons");
  const create = page.locator("form").filter({ has: page.getByRole("button", { name: "ایجاد کد تخفیف" }) });
  const edit = page.locator("details").filter({ hasText: "LABTEST10" });
  await edit.locator("summary").click();
  const expiry = edit.getByRole("button", { name: /^تاریخ انقضا/ });
  await expiry.click();
  await page.getByRole("dialog", { name: "تاریخ انقضا (UTC)", exact: true })
    .getByRole("button", { name: "امروز", exact: true }).click();
  await expect(edit.locator('input[name="expires_at"]')).toHaveValue(/^\d{4}-\d{2}-\d{2}$/);
  await expect(create.locator('input[name="expires_at"]')).toHaveValue("");
});

test("customer expiry wheels wrap at midnight and move in hourly and five-minute steps", async ({ page }) => {
  await signIn(page, "labsales", process.env.LAB_SALES_PASSWORD!);
  await page.goto("/customers");
  await page.getByRole("link", { name: "مشاهده و ویرایش" }).first().click();
  // Midnight in Tehran is on the preceding UTC civil day.
  await page.clock.setFixedTime(new Date("2026-11-07T20:30:00Z"));
  const expiry = page.getByRole("button", { name: /^انقضا/ });
  await expect(expiry).toBeVisible({ timeout: 4000 });
  await expiry.click();
  const calendar = page.getByRole("dialog", { name: "انقضا (اختیاری)" });
  await expect(calendar).toBeVisible();
  await expect(calendar.getByText(/منطقهٔ زمانی/)).toHaveCount(0);
  await calendar.getByRole("button", { name: "امروز", exact: true }).click();
  await expect(calendar.getByRole("button", { name: "انصراف", exact: true })).toHaveCount(0);
  const hour = calendar.getByRole("spinbutton", { name: "ساعت", exact: true });
  const minute = calendar.getByRole("spinbutton", { name: "دقیقه", exact: true });
  await expect(hour).toHaveText("۰۰");
  await expect(minute).toHaveText("۰۰");
  await expect(calendar.getByRole("button", { name: "دقیقه ۵۵", exact: true })).toBeVisible();
  await expect(calendar.getByRole("button", { name: "دقیقه ۰۵", exact: true })).toBeVisible();
  await calendar.getByRole("button", { name: "دقیقه ۵۵", exact: true }).click();
  await expect(minute).toHaveText("۵۵");
  await expect(minute).toBeFocused();
  await minute.press("ArrowUp");
  await expect(minute).toHaveText("۰۰");
  await hour.press("ArrowUp");
  await minute.press("ArrowUp");
  await expect(hour).toHaveText("۰۱");
  await expect(minute).toHaveText("۰۵");
  const confirm = calendar.getByRole("button", { name: "تأیید", exact: true });
  await confirm.click();
  await expect(calendar).toBeHidden();
  await expect(expiry).toBeFocused();
  const value = await expiry.evaluate((button) => new FormData(button.closest("form")!).get("until"));
  expect(value).toBe("2026-11-07T21:35:00.000Z");
});

test("advanced order filters use the calendar and clock directly", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1440", "The calendar layout is covered at all widths above.");
  await signIn(page, "labsales", process.env.LAB_SALES_PASSWORD!);
  await page.goto("/data-models/orders");
  await page.getByRole("combobox", { name: "فیلد", exact: true }).selectOption("created_at");
  const picker = page.getByRole("button", { name: /^تاریخ و زمان/ });
  await expect(picker).toBeVisible({ timeout: 4000 });
  await expect(page.getByText(/ورود دقیق تاریخ و زمان/)).toHaveCount(0);
  await page.clock.setFixedTime(new Date("2026-11-08T08:34:00Z"));
  await picker.click();
  const calendar = page.getByRole("dialog", { name: "تاریخ و زمان", exact: true });
  await calendar.getByRole("button", { name: "امروز", exact: true }).click();
  await calendar.getByRole("button", { name: "تأیید", exact: true }).click();
  await expect(picker).toContainText("۱۲:۰۴");
  await page.getByRole("button", { name: "افزودن فیلتر" }).click();
  await expect(page.getByRole("button", { name: "حذف فیلتر تاریخ ایجاد" })).toBeVisible();
});
