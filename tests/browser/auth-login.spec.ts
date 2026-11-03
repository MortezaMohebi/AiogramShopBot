import { expect, test } from "@playwright/test";

/** Keep these authentication tests on the isolated lab and desktop project. */
test.beforeEach(async ({}, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop-1440",
    "One login per suite avoids unnecessary Redis throttle increments",
  );
});

test("Rejected credentials stay on the Persian login page", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "ورود به داشبورد" }))
    .toBeVisible();

  // Random never-provisioned staff identity; no real admin credential used.
  const username = "invalid_smoke_" + Math.random().toString(36).slice(2, 12);
  await page.getByLabel("نام کاربری").fill(username);
  await page.getByLabel("رمز عبور").fill("invalid-smoke-password");
  await page.getByRole("button", { name: /ورود امن/ }).click();

  const alert = page.getByRole("alert");
  await expect(alert).toContainText("نام کاربری یا رمز عبور صحیح نیست");
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
  await expect(page.getByRole("heading", { name: "ورود به داشبورد" }))
    .toBeVisible();
  await expect(page.getByLabel("رمز عبور")).toHaveValue("");
});

test("POST without CSRF challenge gives a JSON error, not Forbidden HTML", async ({
  request,
}) => {
  const response = await request.post("/api/auth/login", {
    data: { username: "smoke_user", password: "wrong-password" },
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "Sec-Fetch-Site": "same-origin",
      Origin: "null",
    },
  });

  expect(response.status()).toBe(403);
  expect(response.headers()["content-type"]).toContain("application/json");
  expect(await response.json()).toMatchObject({
    ok: false,
    code: "security_check_failed",
  });
});

test("Unavailable auth endpoint shows an inline recoverable error", async ({
  page,
}) => {
  await page.route("**/api/auth/challenge", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ ok: false, code: "service_unavailable" }),
    }),
  );

  await page.goto("/login");
  await page.getByLabel("نام کاربری").fill("exampleadmin");
  await page.getByLabel("رمز عبور").fill("not-a-real-password");
  await page.getByRole("button", { name: /ورود امن/ }).click();

  await expect(page.getByRole("alert"))
    .toContainText("سرویس ورود در دسترس نیست");
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
});

test("Opening the API directly redirects to the login page", async ({
  page,
}) => {
  await page.goto("/api/auth/login");
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
  await expect(page.getByRole("heading", { name: "ورود به داشبورد" }))
    .toBeVisible();
});
