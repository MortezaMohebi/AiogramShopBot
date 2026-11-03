import { expect, test } from "@playwright/test";

/** Geometric checks run at every configured breakpoint. Only the
 * authentication probe is limited to one desktop worker for Redis hygiene. */
test("Login never advertises a real administrator identity", async ({ page }) => {
  await page.goto("/login");

  // A visible label replaces placeholder examples. Browsers may still
  // autofill an account explicitly saved by the current person.
  const username = page.getByRole("textbox", { name: "نام کاربری" });
  await expect(username).toBeVisible();
  expect(await username.getAttribute("placeholder")).toBeNull();
  await expect(page.locator("main")).not.toContainText("shopadmin");
  await expect(page.locator("main")).not.toContainText("رمز اولیه");
});

test("Password reveal control does not collide with LTR input in RTL layout", async ({
  page,
}) => {
  await page.goto("/login");

  const passwordInput = page.locator("#password");
  const reveal = page.getByRole("button", { name: "نمایش رمز عبور" });

  await expect(passwordInput).toBeVisible();
  await expect(reveal).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(passwordInput).toHaveAttribute("dir", "ltr");
  await expect(passwordInput).toHaveAttribute("type", "password");

  const inputBox = await passwordInput.boundingBox();
  const buttonBox = await reveal.boundingBox();
  expect(inputBox).not.toBeNull();
  expect(buttonBox).not.toBeNull();
  if (!inputBox || !buttonBox) {
    throw new Error("Password field geometry is unavailable");
  }

  const leftPadding = await passwordInput.evaluate(
    (element) => Number.parseFloat(getComputedStyle(element).paddingLeft),
  );
  const remainingSpace = leftPadding - (buttonBox.x - inputBox.x + buttonBox.width);
  expect(
    remainingSpace,
    "LTR password text must start after the RTL reveal button, with a gap",
  ).toBeGreaterThanOrEqual(6);

  // Only a synthetic password is used; real staff credentials are not read.
  await passwordInput.fill("ExampleOnly-123!");
  await reveal.click();
  await expect(passwordInput).toHaveAttribute("type", "text");
  await expect(passwordInput).toHaveValue("ExampleOnly-123!");

  await page.getByRole("button", { name: "مخفی‌کردن رمز عبور" }).click();
  await expect(passwordInput).toHaveAttribute("type", "password");
  await expect(passwordInput).toHaveValue("ExampleOnly-123!");
});

test("Rejected credentials stay on the Persian login page", async ({ page }, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop-1440",
    "Only one real FastAPI login probe, to avoid Redis throttle collisions",
  );
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "ورود به داشبورد" }))
    .toBeVisible();

  // Random never-provisioned staff identity; no real admin credential used.
  const username = "invalid_smoke_" + Math.random().toString(36).slice(2, 12);
  await page.getByLabel("نام کاربری").fill(username);
  await page.locator("#password").fill("invalid-smoke-password");
  await page.getByRole("button", { name: /ورود امن/ }).click();

  const alert = page.getByRole("alert");
  await expect(alert).toContainText("نام کاربری یا رمز عبور صحیح نیست");
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
  await expect(page.getByRole("heading", { name: "ورود به داشبورد" }))
    .toBeVisible();
  await expect(page.locator("#password")).toHaveValue("");
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
  await page.locator("#password").fill("not-a-real-password");
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
