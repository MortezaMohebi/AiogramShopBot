import { expect, test } from "@playwright/test";

/**
 * Exercise the live Next.js settings write through FastAPI/PostgreSQL.
 *
 * Run only against the disposable lab with explicitly configured credentials.
 * Never mutate a live Codespaces store to verify a browser change.
 */
test("Saving shop settings persists across a fresh page load", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop-1440",
    "One lab administrator interaction is sufficient.",
  );
  test.skip(
    !process.env.LAB_ADMIN_PASSWORD ||
      !process.env.LAB_BROWSER_BASE_URL?.includes("localhost"),
    "Requires the disposable localhost lab, never a live store.",
  );

  await page.goto("/login");
  await page.getByLabel("نام کاربری").fill("labadmin");
  await page.locator("#password").fill(process.env.LAB_ADMIN_PASSWORD!);
  await page.getByRole("button", { name: /ورود/ }).click();
  await expect(page).toHaveURL(/\/dashboard/);

  await page.goto("/settings");
  const name = page.getByRole("textbox", { name: "نام فروشگاه" });
  const original = await name.inputValue();
  const edited = "آزمایش ذخیره تنظیمات";
  try {
    await name.fill(edited);
    await page.getByRole("button", { name: "ذخیره تنظیمات" }).click();
    await expect(page.getByRole("status")).toContainText("ذخیره شد");
    await page.reload();
    await expect(name).toHaveValue(edited);
  } finally {
    await page.goto("/settings");
    await name.fill(original);
    await page.getByRole("button", { name: "ذخیره تنظیمات" }).click();
    await expect(page.getByRole("status")).toContainText("ذخیره شد");
  }
});

test("Anonymous settings mutation is rejected with structured JSON", async ({
  request,
}) => {
  const response = await request.post("/api/admin/shop-settings", {
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    data: { brand_name: "cannot-write" },
  });
  expect([401, 403]).toContain(response.status());
  expect(response.headers()["content-type"]).toContain("application/json");
  const result = await response.json();
  expect(result).toMatchObject({ ok: false });
});
