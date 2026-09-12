import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

// User feedback was "the output is pretty long, can a jump-to navigation be added in the blank space
// on the left or right of the page" (the screenshot was of step 4, but steps 3/5 are just as long) —
// this Context only handles "which jumpable anchors exist on the current step's page," carrying it
// from a Step*RunPage buried deep in StepPanel (which genuinely knows which sections it rendered) all
// the way to AgentRunPage (where AppShell is rendered and what goes in the right-hand column is
// decided) — reusing exactly the same "Context instead of threading props layer by layer" reasoning as
// DetailsPanelContext.tsx: there are several layers of AppShell/StepCard in between, and each
// Step*RunPage's sections are different, so they can't be hardcoded uniformly at the AppShell layer.
//
// items changes along with the currently rendered content — each Step*RunPage calls setItems again in
// its own useEffect whenever its turns/live state changes (e.g. step 4 receiving a new revision round
// and the candidate set changing means the anchors need to change too), it isn't computed once on
// mount and left unchanged.
//
// The right-hand column is shared — in AgentRunPage.tsx, when ToolDetailsPanel (the details popup that
// appears after clicking a retrieval call) is open, the outline nav yields to it; when nothing is
// selected, the outline nav is the default content. The two don't conflict semantically: the outline
// nav is "assistance while browsing," the details panel is "actively looking something up after
// clicking a call" — the same patch of screen space serves different purposes at different moments, no
// need to squeeze out a separate column just for the outline nav (a wide screen would get too crowded
// with four columns, and a narrow screen wouldn't fit it at all).
export interface OutlineItem {
  id: string;
  label: string;
}

interface PageOutlineState {
  items: OutlineItem[];
  setItems: (items: OutlineItem[]) => void;
}

const PageOutlineContext = createContext<PageOutlineState | null>(null);

export function PageOutlineProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<OutlineItem[]>([]);
  const value = useMemo<PageOutlineState>(() => ({ items, setItems }), [items]);
  return <PageOutlineContext.Provider value={value}>{children}</PageOutlineContext.Provider>;
}

export function usePageOutline(): PageOutlineState {
  const ctx = useContext(PageOutlineContext);
  if (!ctx) {
    throw new Error("usePageOutline must be used within a PageOutlineProvider");
  }
  return ctx;
}
