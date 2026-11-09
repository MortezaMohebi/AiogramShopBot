import { expect, test } from "@playwright/test";

test.use({ hasTouch: true });

test("the RTL header menu opens from the right on compact screens", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-320");
  const password = process.env.LAB_VIEWER_PASSWORD;
  if (!password) throw new Error("Lab viewer credentials are required.");

  await page.goto("/login");
  await page.getByLabel("نام کاربری").fill("labviewer");
  await page.getByLabel("رمز عبور", { exact: true }).fill(password);
  await page.getByRole("button", { name: "ادامه", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard(?:\?|$)/);

  const header = page.getByRole("banner");
  const menu = header.getByRole("button", { name: "منو", exact: true });
  const drawer = page.getByRole("dialog", { name: "منوی مدیریت" });
  const store = header.getByRole("button", { name: "انتخاب یک یا چند فروشگاه فعال" });
  const account = header.getByRole("link", { name: "بازکردن پروفایل و امنیت حساب" });
  const theme = header.getByRole("button", { name: "تغییر حالت روشن و تاریک" });
  await expect(theme).toBeEnabled();
  await store.locator("span").first().evaluate((label) => {
    label.textContent = "فروشگاه آزمایشی با یک نام بسیار طولانی برای بررسی سربرگ موبایل";
  });

  for (const width of [320, 390, 870]) {
    await page.setViewportSize({ width, height: 800 });
    await expect(menu).toBeVisible();
    await expect(page.getByRole("button", { name: "بازکردن منوی مدیریت" })).toHaveCount(0);
    const buttonBox = (await menu.boundingBox())!;
    const headerBox = (await header.boundingBox())!;
    expect(headerBox.x + headerBox.width - buttonBox.x - buttonBox.width).toBeLessThanOrEqual(32);
    expect(buttonBox.height).toBeGreaterThanOrEqual(44);
    const [storeBox, accountBox, themeBox] = await Promise.all(
      [store, account, theme].map((control) => control.boundingBox()),
    );
    expect(buttonBox.x).toBeGreaterThanOrEqual(storeBox!.x + storeBox!.width);
    expect(storeBox!.x).toBeGreaterThanOrEqual(accountBox!.x + accountBox!.width);
    expect(accountBox!.x).toBeGreaterThanOrEqual(themeBox!.x + themeBox!.width);
    expect(themeBox!.x).toBeGreaterThanOrEqual(headerBox.x);

    await menu.tap();
    await expect(drawer).toBeVisible();
    await expect(menu).toHaveAttribute("aria-expanded", "true");
    await expect.poll(async () => {
      const box = (await drawer.boundingBox())!;
      return Math.round(box.x + box.width);
    }).toBe(width);
    await expect(drawer.getByRole("link", { name: "نمای کلی" })).toHaveAttribute("aria-current", "page");
    await expect(drawer.getByRole("link", { name: "ربات‌ها" })).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await expect(menu).toBeFocused();
  }

  await menu.tap();
  await drawer.getByRole("link", { name: "گزارش‌ها" }).tap();
  await expect(page).toHaveURL(/\/reports(?:\?|$)/);
  await expect(drawer).toBeHidden();
  await menu.tap();
  await expect(drawer.getByRole("link", { name: "گزارش‌ها" })).toHaveAttribute("aria-current", "page");

  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(drawer).toBeHidden();
  await expect(menu).toBeHidden();
  await expect(page.getByRole("complementary", { name: "ناوبری اصلی فروشگاه" })).toBeVisible();
});
