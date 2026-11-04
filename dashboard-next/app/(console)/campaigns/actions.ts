"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { adminFetch } from "@/lib/bridge";

function text(form: FormData, key: string): string {
  return String(form.get(key) ?? "").trim();
}

/** Create a draft; no recipient ever receives a message at this stage. */
export async function createCampaign(form: FormData) {
  const target = text(form, "target");
  const legacy = target.match(/^legacy:(all|telegram|bale)$/);
  if (!legacy && !/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(target)) {
    redirect("/campaigns?error=create");
  }
  let failed = false;
  try {
    await adminFetch("/campaigns", "POST", {
      title: text(form, "title"),
      text: text(form, "text"),
      // The API revalidates the current Store and live bot state. An explicit
      // Registry target's audience never widens to other bots or platforms.
      bot_id: legacy ? null : target,
      audience: legacy ? legacy[1] : "all",
    });
  } catch {
    failed = true;
  }
  if (failed) redirect("/campaigns?error=create");
  revalidatePath("/campaigns");
  redirect("/campaigns?saved=1");
}

/** Never start a paid campaign without matching explicit operator confirmation. */
export async function changeCampaign(form: FormData) {
  const id = text(form, "id");
  const action = text(form, "action");
  const baleMode = text(form, "bale_mode") || "standard";
  const confirmed = text(form, "confirmation");
  const codes: Record<string, string> = {
    approve: "APPROVE_CAMPAIGN",
    pause: "PAUSE_CAMPAIGN",
    resume: "RESUME_CAMPAIGN",
    cancel: "CANCEL_CAMPAIGN",
    start: baleMode === "business" ? "START_PAID_BALE" : "START_CAMPAIGN",
  };
  if (!/^\d+$/.test(id) || !codes[action] || confirmed !== codes[action]) {
    redirect("/campaigns?error=confirmation");
  }

  let failed = false;
  try {
    if (action === "start") {
      await adminFetch(`/campaigns/${id}/start`, "POST", {
        bale_mode: baleMode,
        approved_paid_calls: Number(text(form, "approved_paid_calls") || "0"),
      });
    } else {
      await adminFetch(`/campaigns/${id}/${action}`, "POST", {});
    }
  } catch {
    failed = true;
  }
  if (failed) redirect("/campaigns?error=operation");
  revalidatePath("/campaigns");
  revalidatePath("/dashboard");
  redirect("/campaigns?saved=1");
}

/** Close one uncertain delivery with evidence; never requeue it. */
export async function reconcileDelivery(form: FormData) {
  const id = text(form, "campaign_id");
  const delivery = text(form, "delivery_id");
  if (
    !/^\d+$/.test(id) || !/^\d+$/.test(delivery) ||
    text(form, "confirmation") !== "RECONCILE_DELIVERY"
  ) {
    redirect("/campaigns?error=confirmation");
  }
  let failed = false;
  try {
    await adminFetch(`/campaigns/${id}/reconcile`, "POST", {
      delivery_id: Number(delivery),
      resolution: text(form, "resolution"),
      evidence: text(form, "evidence"),
    });
  } catch {
    failed = true;
  }
  if (failed) redirect(`/campaigns/${id}?error=1`);
  revalidatePath(`/campaigns/${id}`);
  redirect(`/campaigns/${id}?saved=1`);
}


/** Allow attachment removal only while the campaign remains a draft. */
export async function deleteCampaignMedia(form: FormData) {
  const campaignId = text(form, "campaign_id");
  const mediaId = text(form, "media_id");
  if (
    !/^[1-9]\d*$/.test(campaignId) ||
    !/^[1-9]\d*$/.test(mediaId) ||
    text(form, "confirmation") !== "DELETE_DRAFT_ATTACHMENT"
  ) {
    redirect("/campaigns?error=confirmation");
  }
  let failed = false;
  try {
    await adminFetch(`/campaigns/${campaignId}/media/${mediaId}`, "DELETE");
  } catch {
    failed = true;
  }
  if (failed) redirect(`/campaigns/${campaignId}?error=media`);
  revalidatePath(`/campaigns/${campaignId}`);
  revalidatePath("/campaigns");
  redirect(`/campaigns/${campaignId}?saved=1`);
}


/** Prepare Bale media file IDs only in a configured private seed chat.

No campaign deliveries, paid Business calls or worker wake-ups occur here.
The external operation requires explicit operator confirmation.
*/
export async function prepareBaleMedia(form: FormData) {
  const id = text(form, "campaign_id");
  if (
    !/^[1-9]\d*$/.test(id) ||
    text(form, "confirmation") !== "PREPARE_BALE_MEDIA"
  ) {
    redirect("/campaigns?error=confirmation");
  }
  let failed = false;
  try {
    await adminFetch(`/broadcast/prepare/${id}`, "POST", {
      confirmation: "PREPARE_BALE_MEDIA",
    });
  } catch {
    failed = true;
  }
  if (failed) redirect(`/campaigns/${id}?error=prepare`);
  revalidatePath(`/campaigns/${id}`);
  redirect(`/campaigns/${id}?saved=prepared`);
}
