/** Browser-side same-origin CSRF challenge shared by login and logout. */
export async function requestBrowserChallenge(): Promise<string> {
  const response = await fetch("/api/auth/challenge", {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(15_000),
  });

  if (
    !response.ok ||
    !(response.headers.get("content-type") ?? "").includes("application/json")
  ) {
    throw new Error("security_check_failed");
  }

  const result: unknown = await response.json();
  if (
    !result ||
    typeof result !== "object" ||
    !("challenge" in result) ||
    typeof result.challenge !== "string" ||
    !/^[A-Za-z0-9_-]{43}$/.test(result.challenge)
  ) {
    throw new Error("security_check_failed");
  }

  return result.challenge;
}
