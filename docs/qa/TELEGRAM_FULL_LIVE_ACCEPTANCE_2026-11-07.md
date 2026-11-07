# Telegram live QA — 2026-11-07

Scope: one connected QA bot in the Codespace, synthetic products, address, shipping and coupon. No live charge, refund, balance adjustment or broadcast was performed.

## Evidence

| Scenario | Result | Observation |
| --- | --- | --- |
| Telegram /start and main menu | PASS | Cart appeared after enabling the bot commerce policy. |
| Product visibility | PASS | Published, explicitly allowed QA products appeared; hidden and denied fixtures remained configured separately. |
| Physical product and cart | PASS | Add to cart, quantity 1 to 2, and IRR total of 500,000 were visible in Telegram Web. |
| Missing checkout details | PASS | Review required address and shipping method. |
| Synthetic address and shipping | PASS | The test-only address and zero-IRR QA shipping method were displayed in the cart. |
| Coupon | PASS | QA10NOV07 applied 10% to the 500,000-IRR cart, resulting in a 450,000-IRR review total. |
| Missing Store sales terms | PASS | Review was blocked before creating an order. |
| Policy form proof regression | PASS | 14 focused Python tests passed in the Codespace, including invalid proof and bot onboarding guards. |
| Unpaid pending-review order | BLOCKED | Store terms form required fresh password and MFA; the secure prompt was stopped before credential submission. |
| Full Python suite after latest fixes | NOT VERIFIED | A full run was started, but its final log was not observed before the Codespace stopped. |

## Fixes on this branch

- A fresh explicit password and MFA proof on a bot commerce or Store/Bot checkout policy form can reach the endpoint verifier even after the earlier session step-up expires. Session validation, role, Store scope and the endpoint's own fresh proof remain mandatory. Destructive bot actions keep their prior step-up requirement.
- First Store/Bot commerce and checkout policy rows initialize revision zero before incrementing, preventing a null revision on their first save.
- Regression coverage exercises successful and rejected explicit proof and first Store policy saves.

## Remaining live step

The QA-only Store terms were prepared in the dashboard but not saved. Keep checkout in manual approval mode, save the synthetic no-payment/no-delivery terms through the secure form, then submit at most one unpaid test order and verify its pending-review status in the dashboard. Do not start a payment or fulfillment.

The Codespace was observed stopped after the secure prompt was cancelled. Restart it only when resuming this live test, rebuild the app from the latest Draft branch, and rerun the full Python suite and browser checks. No credential or MFA value belongs in this report.
