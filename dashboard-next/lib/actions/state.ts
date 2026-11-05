import type { ActionDescriptor, JsonSchema } from "./types.ts";

/** Keep nullable primitives inspectable without treating arbitrary objects as scalars. */
export function primitiveSchema(schema: JsonSchema): JsonSchema {
  return schema.anyOf?.find((item) => item.type !== "null") ?? schema;
}
/** Apply all visible Catalog filters together; Backend remains authorization authority. */
export function filterActions<T extends ActionDescriptor>(
  items: T[],
  filters: { q: string; category: string; effect: string; deprecated: string },
): T[] {
  const query = filters.q.trim().toLocaleLowerCase();
  return items.filter(
    (item) =>
      (!query ||
        `${item.key} ${item.name}`.toLocaleLowerCase().includes(query)) &&
      (!filters.category || filters.category === item.category) &&
      (!filters.effect || filters.effect === item.side_effect) &&
      (filters.deprecated === "all" ||
        item.deprecated === (filters.deprecated === "true")),
  );
}
/** Convert the generated safe dry-run form to typed scalar inputs, never identity context. */
export function parseActionInput(
  schema: JsonSchema,
  values: Record<string, string | boolean>,
): Record<string, unknown> {
  const fields = schema.properties ?? {};
  const output: Record<string, unknown> = {};
  for (const key of Object.keys(values)) {
    if (
      ["__proto__", "prototype", "constructor"].includes(key) ||
      !Object.hasOwn(fields, key)
    )
      throw new Error("action_invalid_input");
  }
  for (const [key, raw] of Object.entries(fields)) {
    const value = values[key];
    if (value === undefined || value === "") {
      if (schema.required?.includes(key))
        throw new Error("action_input_required");
      continue;
    }
    const field = primitiveSchema(raw);
    let typed: unknown = value;
    if (field.type === "integer" || field.type === "number") {
      const number =
        typeof value === "string" && value.trim() ? Number(value) : NaN;
      if (
        !Number.isFinite(number) ||
        (field.type === "integer" && !Number.isSafeInteger(number)) ||
        (field.minimum !== undefined && number < field.minimum) ||
        (field.maximum !== undefined && number > field.maximum)
      )
        throw new Error("action_invalid_input");
      typed = number;
    } else if (field.type === "boolean") {
      if (
        value !== true &&
        value !== false &&
        value !== "true" &&
        value !== "false"
      )
        throw new Error("action_invalid_input");
      typed = value === true || value === "true";
    } else if (field.type === "string") {
      if (
        typeof value !== "string" ||
        (field.minLength !== undefined && value.length < field.minLength) ||
        (field.maxLength !== undefined && value.length > field.maxLength)
      )
        throw new Error("action_invalid_input");
    } else throw new Error("action_unsupported_form");
    if (field.enum && !field.enum.includes(typed as string | number | boolean))
      throw new Error("action_invalid_input");
    output[key] = typed;
  }
  return output;
}
/** Restrict mapping choices to scalar types or an explicit product/order reference ID. */
export function mappingVariables<
  T extends { name: string; type: string; choices?: readonly string[] },
>(
  raw: JsonSchema,
  fieldName: string,
  variables: readonly T[],
  output = false,
  actionKey = "",
): T[] {
  const field = primitiveSchema(raw);
  return variables.filter((variable) => {
    if (variable.type.endsWith("_ref")) {
      const kind = variable.type.slice(0, -4);
      return (
        field.type === "integer" &&
        (fieldName === `${kind}_id` ||
          (output &&
            fieldName === "id" &&
            kind === "product" &&
            actionKey === "catalog.get_product"))
      );
    }
    if (variable.type === "integer")
      return field.type === "integer" || field.type === "number";
    if (variable.type === "boolean") return field.type === "boolean";
    if (["string", "enum", "date", "datetime"].includes(variable.type)) {
      if (field.type !== "string") return false;
      if (output && ["date", "datetime"].includes(variable.type))
        return (
          field.format === (variable.type === "date" ? "date" : "date-time")
        );
      if (output && variable.type === "enum")
        return (
          !!field.enum &&
          field.enum.every(
            (choice) =>
              typeof choice === "string" &&
              (variable.choices ?? []).includes(choice),
          )
        );
      if (!output && field.enum)
        return (
          variable.type === "enum" &&
          (variable.choices ?? []).every((choice) =>
            field.enum!.includes(choice),
          )
        );
      return true;
    }
    return false;
  });
}
export const sideEffectLabels: Record<ActionDescriptor["side_effect"], string> =
  {
    none: "بدون اثر جانبی",
    read_only: "فقط خواندن",
    reversible: "قابل بازگردانی",
    business_mutation: "تغییر دادهٔ کسب‌وکار",
    external_mutation: "اثر در سرویس بیرونی",
    irreversible: "برگشت‌ناپذیر",
  };
/** Explain only known reasons; never render an arbitrary server exception as product copy. */
export function actionReason(code: string): string {
  return (
    (
      {
        action_bot_required: "برای بررسی دسترسی، یک ربات انتخاب کنید.",
        action_bot_unavailable: "ربات فعال و آمادهٔ استفاده نیست.",
        action_store_unavailable: "فروشگاه فعال نیست.",
        action_cart_disabled: "سبد خرید این ربات غیرفعال است.",
        action_service_unavailable: "Adapter واقعی این Action هنوز آماده نیست.",
        action_return_policy_unavailable:
          "سیاست واقعی تشخیص مرجوعی هنوز آماده نیست.",
        action_platform_unavailable:
          "این Action در پیام‌رسان انتخاب‌شده پشتیبانی نمی‌شود.",
        action_rate_limited:
          "تعداد بررسی‌ها به حد مجاز رسیده است؛ کمی بعد دوباره امتحان کنید.",
        action_invalid_input: "ورودی‌های Action را بررسی کنید.",
        action_input_required: "ورودی الزامی را تکمیل کنید.",
        action_product_unavailable: "محصول برای این ربات قابل دسترسی نیست.",
        permission_denied: "برای این بررسی دسترسی کافی ندارید.",
        session_expired: "نشست شما پایان یافته است؛ دوباره وارد شوید.",
      } as Record<string, string>
    )[code] ?? "بررسی Action انجام نشد؛ دوباره تلاش کنید."
  );
}
