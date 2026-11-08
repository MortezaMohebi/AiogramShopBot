import { expect, test } from "@playwright/test";

/** Retired deployment-global controls never become a public mutation path. */
test("Retired connection endpoints return not found", async ({ request }) => {
  for (const path of [
    "/api/admin/bot-connections",
    "/api/admin/bot-connections/mode-request",
    "/api/admin/telegram-transport/stage",
  ]) {
    const response = await request.post(path, {
      headers: { "Content-Type": "application/json" },
      data: { mode: "polling" },
    });
    expect(response.status()).toBe(404);
  }
});
