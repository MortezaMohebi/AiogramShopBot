import { expect, test } from "@playwright/test";

const storageState = process.env.LAB_RECORDS_STORAGE_STATE;
test.use({ storageState, hasTouch: true });

test.beforeEach(async ({ page }) => {
  if (storageState) return;
  const password = process.env.LAB_ADMIN_PASSWORD;
  if (!password) throw new Error("Lab admin credentials are required.");
  await page.goto("/login");
  await page.getByLabel("نام کاربری").fill("labadmin");
  await page.getByLabel("رمز عبور").fill(password);
  await page.getByRole("button", { name: "ادامه", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard(?:\?|$)/);
});

test("customer opens by clicking any non-control cell, without a detail column", async ({ page }) => {
  await page.goto("/customers");
  const table = page.getByRole("table");
  const row = table.locator("tbody tr").first();
  await expect(row).toBeVisible();
  await expect(table.getByRole("columnheader", { name: "پرونده", exact: true })).toHaveCount(0);
  const link = row.getByRole("link");
  const detail = await link.getAttribute("href");
  expect(detail).toMatch(/^\/customers\/\d+$/);
  const status = row.getByRole("cell").nth(2);
  if (page.viewportSize()?.width === 320) await status.tap();
  else await status.click();
  await expect(page).toHaveURL(new URL(detail!, page.url()).href);
  await expect(page.getByRole("link", { name: "بازگشت به مشتریان" })).toBeVisible();
});

test("the real record link works with the keyboard", async ({ page }) => {
  await page.goto("/customers");
  const row = page.getByRole("table").locator("tbody tr").first();
  const link = row.getByRole("link");
  const detail = await link.getAttribute("href");
  await expect(row).not.toHaveAttribute("role", "link");
  await expect(row).not.toHaveAttribute("tabindex", /.+/);
  await link.focus();
  await expect(link).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new URL(detail!, page.url()).href);
});

test("product row selection and opening the record are independent", async ({ page }) => {
  await page.goto("/products");
  const table = page.getByRole("table");
  const row = table.locator("tbody tr").first();
  await expect(row).toBeVisible();
  await expect(table.getByRole("columnheader", { name: "عملیات", exact: true })).toHaveCount(0);
  const checkbox = row.getByRole("checkbox");
  await checkbox.check();
  await expect(checkbox).toBeChecked();
  await expect(page).toHaveURL(/\/products(?:\?|$)/);
  const detail = await row.getByRole("link").getAttribute("href");
  expect(detail).toMatch(/^\/products\/\d+\/edit$/);
  await row.getByRole("cell").nth(3).click();
  await expect(page).toHaveURL(new URL(detail!, page.url()).href);
});

test("record metadata remains selectable", async ({ page }) => {
  await page.goto("/customers");
  const status = page.getByRole("table").locator("tbody tr").first().getByRole("cell").nth(2);
  await expect(status).toBeVisible();
  await status.evaluate(cell => {
    const selection = window.getSelection()!;
    selection.selectAllChildren(cell);
    cell.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await expect(page).toHaveURL(/\/customers(?:\?|$)/);
  expect(await page.evaluate(() => window.getSelection()?.toString())).toBeTruthy();
});

test("a staff access card opens from its role text", async ({ page }) => {
  await page.goto("/staff");
  const section = page.getByRole("region", { name: "دسترسی کاربران به فروشگاه‌ها" });
  const card = section.locator("[data-record-area]").first();
  const detail = await card.getByRole("link").getAttribute("href");
  expect(detail).toMatch(/^\/staff\/\d+\/stores$/);
  await card.locator("span.text-muted-foreground").click();
  await expect(page).toHaveURL(new URL(detail!, page.url()).href);
  await expect(page.getByRole("link", { name: "بازگشت به کارکنان" })).toBeVisible();
});
