/** Browser-side same-origin CSRF challenge shared by login and logout. */
export async function requestBrowserChallenge(): Promise<string> {
  const response = await fetch("/api/auth/challenge", {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(15_000),
  });

  // Distinguish an actual security failure from a down/overloaded server.
  if (!response.ok) {
    throw new Error(
      response.status >= 500 ? "service_unavailable" : "security_check_failed",
    );
  }
  if (!(response.headers.get("content-type") ?? "").includes("application/json")) {
    throw new Error("network_unavailable");
  }

  let result: unknown;
  try {
    result = await response.json();
  } catch {
    throw new Error("service_unavailable");
  }

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
