import { expect, test } from "@playwright/test";

const storageState = process.env.LAB_RECORDS_STORAGE_STATE;
const rootId = process.env.LAB_CATEGORY_ROOT_ID;
const childId = process.env.LAB_CATEGORY_CHILD_ID;
test.use({ storageState, hasTouch: true });

test("category parents are selectable, discardable and persisted", async ({ page }) => {
  test.skip(!storageState || !rootId || !childId, "Requires disposable category fixtures.");
  await page.goto("/categories", { waitUntil: "networkidle" });
  const root = page.locator(`tr[data-order-row="${rootId}"]`);
  const child = page.locator(`tr[data-order-row="${childId}"]`);
  const rootName = await root.locator("[data-record-trigger]").innerText();
  const childName = await child.locator("[data-record-trigger]").innerText();
  const editor = page.locator(`#category-draft-${childId}`);
  const selectedParent = editor.locator('input[name="parent_id"]');
  const openChild = async () => {
    const status = child.getByRole("cell").nth(1);
    if (page.viewportSize()?.width === 320) await status.tap();
    else await status.click();
    await expect(editor).toBeVisible();
  };
  await openChild();
  await expect(selectedParent).toHaveValue(rootId!);
  await editor.getByRole("button", { name: "برداشتن والد" }).click();
  await editor.getByRole("button", { name: "لغو تغییرات" }).click();
  await openChild();
  await expect(selectedParent).toHaveValue(rootId!);
  await editor.getByRole("button", { name: "برداشتن والد" }).click();
  await editor.getByRole("button", { name: "ذخیرهٔ تغییرات" }).click();
  await expect(editor).toHaveCount(0);
  await page.reload({ waitUntil: "networkidle" });
  await openChild();
  await expect(selectedParent).toHaveValue("");
  await editor.getByRole("button", { name: "بدون والد", exact: true }).click();
  const options = editor.getByRole("listbox");
  await expect(options.getByRole("option", { name: rootName, exact: true })).toBeVisible();
  await expect(options.getByRole("option", { name: childName, exact: true })).toHaveCount(0);
  await options.getByRole("option", { name: rootName, exact: true }).click();
  await editor.getByRole("button", { name: "ذخیرهٔ تغییرات" }).click();
  await expect(editor).toHaveCount(0);
  await page.reload({ waitUntil: "networkidle" });
  await openChild();
  await expect(selectedParent).toHaveValue(rootId!);
});
