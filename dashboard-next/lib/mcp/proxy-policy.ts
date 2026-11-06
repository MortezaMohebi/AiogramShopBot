/** Closed management targets; business approval remains exclusively in WPMCP. */
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export function mcpTarget(method: "GET" | "POST", path: readonly string[]): { target: string; query: readonly string[] } | null {
  if (method === "GET") {
    if (path.length === 0) return { target: "/mcp", query: ["page"] };
    if (path.length === 1 && path[0] === "history") return { target: "/mcp/history", query: ["page"] };
    if (path.length === 2 && uuid.test(path[1])) {
      if (path[0] === "pairings" || path[0] === "grants") return { target: "/mcp/" + path.join("/"), query: [] };
      if (path[0] === "owned-grants") return { target: "/account/mcp-grants/" + path[1], query: [] };
    }
  }
  if (method === "POST" && path.length === 3 && uuid.test(path[1])) {
    if (path[0] === "pairings" && path[2] === "confirm") return { target: "/mcp/" + path.join("/"), query: [] };
    if (path[0] === "owned-grants" && path[2] === "revoke") return { target: "/account/mcp-grants/" + path[1] + "/revoke", query: [] };
  }
  return null;
}
