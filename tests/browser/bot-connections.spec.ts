import { expect, test } from "@playwright/test";

/** The lab uses real FastAPI/PostgreSQL but no external Telegram/Bale tokens. */
test("Connection settings show actual modes without leaking bot credentials", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1440");
  test.skip(
    !process.env.LAB_ADMIN_PASSWORD ||
      !process.env.LAB_BROWSER_BASE_URL?.includes("localhost"),
    "Only run with a disposable localhost lab administrator.",
  );

  await page.goto("/login");
  await page.getByLabel("نام کاربری").fill("labadmin");
  await page.locator("#password").fill(process.env.LAB_ADMIN_PASSWORD!);
  await page.getByRole("button", { name: /ورود/ }).click();
  await expect(page).toHaveURL(/\/dashboard/);

  await page.goto("/bot-connections");
  await expect(page.getByRole("heading", { name: "تنظیمات اتصال ربات‌ها" }))
    .toBeVisible();
  await expect(page.getByText("روش ثبت‌شده:").first()).toBeVisible();
  await expect(page.getByRole("combobox", { name: "روش موردنظر" }))
    .toHaveValue("webhook");
  await expect(page.locator('option[value="polling"]'))
    .toHaveText("getUpdates — Long Polling");
  await expect(page.getByText("مسیر Webhook بله (Secret مخفی)"))
    .toHaveCount(0);
  await expect(page.getByRole("button", { name: "ثبت پیشنهاد تغییر" }))
    .toBeVisible();
});

test("Anonymous mode stage is rejected", async ({ request }) => {
  const response = await request.post(
    "/api/admin/bot-connections/mode-request",
    {
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      data: { mode: "polling", confirmation: "STAGE_TELEGRAM_MODE" },
    },
  );
  expect([401, 403]).toContain(response.status());
  expect(response.headers()["content-type"]).toContain("application/json");
  expect(await response.json()).toMatchObject({ ok: false });
});
