import { expect, test } from "@playwright/test";

/** Exercise the real Persian dashboard under a disposable HTTPS origin. */
test("Login UI uses RTL Persian at the requested viewport", async ({
  page,
}, testInfo) => {
  await page.goto("/login");

  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.locator("html")).toHaveAttribute("lang", "fa");
  await expect(
    page.getByRole("heading", { name: "ورود به داشبورد" }),
  ).toBeVisible();
  await expect(page.getByLabel("نام کاربری")).toBeVisible();

  // Store a deliberately unauthenticated screenshot as visual baseline.
  await page.screenshot({
    path: testInfo.outputPath("login-rtl.png"),
    fullPage: true,
  });
});

test("Real staff login, dashboard, media and dark mode", async ({
  page,
}, testInfo) => {
  // One login attempt per suite minimizes Redis throttle collisions.
  test.skip(testInfo.project.name !== "desktop-1440");

  const password = process.env.LAB_ADMIN_PASSWORD;
  if (!password) throw new Error("Lab admin password was not configured");

  // Keep the theme deterministic regardless of the runner's OS setting.
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/login");
  await page.getByLabel("نام کاربری").fill("labadmin");
  await page.getByLabel("رمز عبور").fill(password);
  await page.getByRole("button", { name: /ورود امن/ }).click();

  await expect(page).toHaveURL(/\/dashboard(?:\?|$)/);
  await expect(
    page.getByRole("heading", { name: "نمای کلی فروشگاه" }),
  ).toBeVisible();

  const toggle = page.getByRole("button", {
    name: "تغییر حالت روشن و تاریک",
  });
  await expect(toggle).toBeEnabled();
  await toggle.click();
  await expect(page.locator("html")).toHaveClass(/dark/);

  await page.goto("/media");
  await expect(
    page.getByRole("heading", { name: "رسانه‌های فروشگاه" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("authenticated-media-dark.png"),
    fullPage: true,
  });
});

test("A viewer cannot access the finance console", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1440");

  const password = process.env.LAB_VIEWER_PASSWORD;
  if (!password) throw new Error("Lab viewer password was not configured");

  await page.goto("/login");
  await page.getByLabel("نام کاربری").fill("labviewer");
  await page.getByLabel("رمز عبور").fill(password);
  await page.getByRole("button", { name: /ورود امن/ }).click();
  await expect(page).toHaveURL(/\/dashboard(?:\?|$)/);

  // The authoritative FastAPI role check is independent of sidebar links.
  const response = await page.goto("/finance");
  expect(response?.status()).toBe(404);
  await expect(
    page.getByRole("heading", { name: "امور مالی" }),
  ).toHaveCount(0);
});
