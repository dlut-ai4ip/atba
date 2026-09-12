import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { CallRecord } from "../components/ToolCallEntry";

// The interaction design/tool_output_panel.png calls for: clicking a retrieval-type tool call
// (search_scopus/get_paper_abstract) no longer expands it in place, instead opening a persistent
// sidebar on the right of shell-main (see AppShell.tsx's detailsPanel slot). This Context does exactly
// one thing — remember "which call is currently selected," carrying it from ToolCallEntry.tsx (buried
// deep in Step3/4/5RunPage's scrolling content) all the way to AgentRunPage (where AppShell is
// rendered): rather than threading it down through props layer by layer (there are several layers
// between StepPanel/AppShell, and future steps 4/5 will also reuse the same panel, so adding a
// transient prop at every layer isn't worth it).
//
// selected stores a complete CallRecord snapshot, not just a callId — during streaming, the same
// callId keeps getting swapped for a new object via upsertToolCall (see useLiveTranscript.ts), and the
// panel needs to show "this call's latest state so far," so ToolCallEntry actively calls open() again
// with the new snapshot whenever its own call prop updates (see the useEffect in that component) — the
// Context itself isn't responsible for "chasing updates," only for "storing whatever it was last told."
interface DetailsPanelState {
  selected: CallRecord | null;
  open: (call: CallRecord) => void;
  close: () => void;
}

const DetailsPanelContext = createContext<DetailsPanelState | null>(null);

export function DetailsPanelProvider({ children }: { children: ReactNode }) {
  const [selected, setSelected] = useState<CallRecord | null>(null);
  const value = useMemo<DetailsPanelState>(
    () => ({
      selected,
      open: (call) => setSelected(call),
      close: () => setSelected(null),
    }),
    [selected],
  );
  return <DetailsPanelContext.Provider value={value}>{children}</DetailsPanelContext.Provider>;
}

export function useDetailsPanel(): DetailsPanelState {
  const ctx = useContext(DetailsPanelContext);
  if (!ctx) {
    throw new Error("useDetailsPanel must be used within a DetailsPanelProvider");
  }
  return ctx;
}
