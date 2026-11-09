import { expect, test } from "@playwright/test";

const storageState = process.env.LAB_RECORDS_STORAGE_STATE;
test.use({ storageState });

test.beforeEach(async ({ page }) => {
  if (storageState) return;
  const password = process.env.LAB_ADMIN_PASSWORD;
  if (!password) throw new Error("Lab admin credentials are required.");
  await page.goto("/login", { waitUntil: "networkidle" });
  await page.getByLabel("نام کاربری").fill("labadmin");
  await page.getByLabel("رمز عبور").fill(password);
  await page.getByRole("button", { name: "ادامه", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard(?:\?|$)/);
});

test("customer filters and named views survive navigation", async ({ page }) => {
  await page.goto("/customers", { waitUntil: "networkidle" });
  const bar = page.getByRole("search", { name: "جست‌وجوی فهرست" });
  const menu = bar.getByText("فیلترها و نماها", { exact: true });
  await expect(bar.getByRole("heading", { name: "فیلترها", exact: true })).toBeHidden();
  await menu.click();
  await bar.getByLabel("رضایت تبلیغاتی").selectOption("yes");
  await bar.getByRole("button", { name: "اعمال فیلترها" }).click();
  await expect(page).toHaveURL(/consent=yes/);
  await page.waitForLoadState("networkidle");
  await expect(bar.getByRole("link", { name: "حذف فیلتر رضایت تبلیغاتی" })).toBeVisible();

  await menu.click();
  await bar.getByLabel("نام نما").fill("مشترکان آزمایشی");
  await bar.getByRole("button", { name: "ذخیرهٔ نمای فعلی" }).click();
  await expect(bar.getByRole("button", { name: "مشترکان آزمایشی", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(bar.getByRole("heading", { name: "علاقه‌مندی‌ها", exact: true })).toBeHidden();
  await bar.getByRole("link", { name: "حذف فیلتر رضایت تبلیغاتی" }).click();
  await expect(page).toHaveURL(/\/customers$/);
  await menu.click();
  await bar.getByRole("button", { name: "مشترکان آزمایشی", exact: true }).click();
  await expect(page).toHaveURL(/consent=yes/);
  await expect(bar.getByRole("heading", { name: "علاقه‌مندی‌ها", exact: true })).toBeHidden();
});

test("advanced search groups real model data from the shared menu", async ({ page }) => {
  await page.goto("/data-models/products", { waitUntil: "networkidle" });
  await page.getByText("فیلترها و نماها", { exact: true }).click();
  await expect(page.getByRole("heading", { name: "فیلترها", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "گروه‌بندی", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "علاقه‌مندی‌ها", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "گروه‌بندی", exact: true }).click();
  await expect(page.getByRole("heading", { name: "نتیجهٔ گروه‌بندی", exact: true })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "تعداد", exact: true })).toBeVisible();
});

test("product search uses the same bar and preserves its query", async ({ page }) => {
  await page.goto("/products", { waitUntil: "networkidle" });
  const search = page.getByRole("searchbox", { name: "نام یا کد کالا" });
  await search.fill("QA");
  await search.press("Enter");
  await expect(page).toHaveURL(/search=QA/);
  await expect(search).toHaveValue("QA");
});
