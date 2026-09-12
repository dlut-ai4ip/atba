// Parses pydantic-ai AgentRunResult.all_messages_json()'s real audit trail into a list of chat
// bubbles. This isn't made-up demo data — the tool_call/tool_return/thinking blocks are all content
// the model actually produced in that real call; this just converts pydantic-ai's message format into
// a shape the UI can render better. Unrecognized part types are dumped as-is, no information is
// dropped.

export type ChatEntry =
  | { kind: "user"; text: string }
  | { kind: "thinking"; text: string }
  | { kind: "text"; text: string }
  | { kind: "tool_call"; toolName: string; args: unknown; callId: string }
  | { kind: "tool_call_raw"; toolName: string; text: string }
  | { kind: "tool_return"; toolName: string; content: string; callId: string }
  | { kind: "retry"; text: string }
  | { kind: "raw"; text: string };

// tool_call_raw isn't produced by parseAuditTrail — it's what App.tsx wraps for display when
// consuming /api/step1/stream: a tool_call_delta that hasn't finished yet, still half-formed JSON
// text, wrapped as-is; that's a different thing from the tool_call parseAuditTrail produces after
// parsing a complete audit_trail (where args is already parsed into an object) — don't mix the two up.

function extractText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content.map((c) => (typeof c === "string" ? c : JSON.stringify(c, null, 2))).join("\n");
  }
  return content == null ? "" : JSON.stringify(content, null, 2);
}

export function parseAuditTrail(
  messages: Record<string, unknown>[] | null | undefined,
): ChatEntry[] {
  if (!messages) return [];
  const entries: ChatEntry[] = [];
  for (const msg of messages) {
    const parts = (msg.parts as Record<string, unknown>[] | undefined) ?? [];
    for (const part of parts) {
      const kind = part.part_kind as string | undefined;
      switch (kind) {
        case "system-prompt":
          // Not displayed: the content is the fixed system-prompt template, long and not information
          // about "what happened during this run."
          break;
        case "user-prompt":
          entries.push({ kind: "user", text: extractText(part.content) });
          break;
        case "thinking":
          entries.push({ kind: "thinking", text: extractText(part.content) });
          break;
        case "text":
          entries.push({ kind: "text", text: extractText(part.content) });
          break;
        case "tool-call": {
          let args: unknown = part.args;
          if (typeof args === "string") {
            try {
              args = JSON.parse(args);
            } catch {
              // Keep the raw string
            }
          }
          entries.push({
            kind: "tool_call",
            toolName: String(part.tool_name ?? "unknown_tool"),
            args,
            callId: String(part.tool_call_id ?? ""),
          });
          break;
        }
        case "tool-return":
          entries.push({
            kind: "tool_return",
            toolName: String(part.tool_name ?? "unknown_tool"),
            content: extractText(part.content),
            callId: String(part.tool_call_id ?? ""),
          });
          break;
        case "retry-prompt":
          entries.push({ kind: "retry", text: extractText(part.content) });
          break;
        default:
          entries.push({ kind: "raw", text: JSON.stringify(part, null, 2) });
      }
    }
  }
  return entries;
}
