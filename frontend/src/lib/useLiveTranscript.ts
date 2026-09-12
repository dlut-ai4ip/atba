import { useState } from "react";
import type { CallRecord } from "../components/ToolCallEntry";

// A segment where "thinking" and "tool calls" during streaming alternate in the real order they
// arrived — the same spirit as the final ChatEntry produced by parseAuditTrail(): don't sort them into
// two separate buckets, "all the thinking in one place, all the calls in another" (that would break up
// the real alternating order of "thinking → call → thinking → call ..."; user feedback was "the
// thinking process and the tool display got separated, that doesn't match the timeline" — the final
// version was always correctly alternating in audit_trail's order, but streaming didn't match that,
// which this fills in).
export type LiveSegment =
  | { kind: "thinking"; key: number; text: string }
  | { kind: "tool_call"; key: number; call: CallRecord };

// Manages "the real alternating order in which thinking and tool calls have appeared so far in this
// streaming call" — thinking_delta is appended to "the last segment, if it's also thinking" (
// consecutive thinking deltas merge into one segment, not one segment per character); tool_call_delta/
// tool_result/tool_result_retry update whichever segment with that call_id already exists, in place
// (regardless of where it currently sits in the array — a call might not get its result until after
// some thinking has happened, in which case the segment to update is the one where it originally
// appeared, not the end of the array); a new segment is only opened at the end the first time a given
// call_id is seen.
export function useLiveTranscript() {
  const [segments, setSegments] = useState<LiveSegment[]>([]);

  function reset() {
    setSegments([]);
  }

  function pushThinking(deltaText: string) {
    setSegments((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.kind === "thinking") {
        const next = prev.slice(0, -1);
        next.push({ ...last, text: last.text + deltaText });
        return next;
      }
      return [...prev, { kind: "thinking", key: prev.length, text: deltaText }];
    });
  }

  // updater receives "the CallRecord that already exists for this call_id (null the first time it
  // appears)" and returns the new CallRecord — the same pattern as React's functional setState, so the
  // caller doesn't have to separately handle "inserting a new segment" versus "updating an existing
  // one."
  function upsertToolCall(callId: string, updater: (existing: CallRecord | null) => CallRecord) {
    setSegments((prev) => {
      const idx = prev.findIndex((s) => s.kind === "tool_call" && s.call.callId === callId);
      if (idx === -1) {
        return [...prev, { kind: "tool_call", key: prev.length, call: updater(null) }];
      }
      const next = [...prev];
      const existing = next[idx] as Extract<LiveSegment, { kind: "tool_call" }>;
      next[idx] = { ...existing, call: updater(existing.call) };
      return next;
    });
  }

  return { segments, reset, pushThinking, upsertToolCall };
}
