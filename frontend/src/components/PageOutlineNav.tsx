import { useEffect, useRef, useState } from "react";
import { useT } from "../i18n";
import type { OutlineItem } from "../lib/PageOutlineContext";

// The shape the user explicitly asked for from a screenshot: "collapsed most of the time, hover to
// reveal a quick-jump title list" — not a permanently layout-width-occupying sidebar (that was the
// first version's approach, taking up a full 22rem column, an eyesore even collapsed), but a small
// stack of short dashes (one per anchor) stuck to the viewport's right edge, expanding into a floating
// card with full title text only on hover. position:fixed sticks it to the viewport edge on its own,
// taking no part in .shell's flex layout and occupying no permanent width — a different mechanism from
// .shell-details-panel in AppShell.tsx (the permanent column ToolDetailsPanel uses) — AgentRunPage.tsx
// only renders this component when no ToolDetailsPanel is open, so the two don't compete for visual
// focus at the right edge.

// As the page scrolls down, an IntersectionObserver watches whether each anchor enters a narrow band
// near the top of the viewport, and whichever enters first gets marked as the "currently viewed
// section" highlight. rootMargin's "-15% 0px -70% 0px" means: only the narrow band from 15% to 30% down
// the viewport counts as the "hit zone," not the whole viewport — otherwise, scrolling just a little
// with most of the content still below the fold would already be judged "entered," making the
// highlight jump too eagerly and not match the user's intuitive sense of "which section am I actually
// looking at."
const OBSERVER_ROOT_MARGIN = "-15% 0px -70% 0px";

export function PageOutlineNav({ items }: { items: OutlineItem[] }) {
  const t = useT();
  const [activeId, setActiveId] = useState<string | null>(null);
  const idsKey = items.map((i) => i.id).join("|");
  const itemsRef = useRef(items);
  itemsRef.current = items;

  useEffect(() => {
    const targets = itemsRef.current
      .map((item) => document.getElementById(item.id))
      .filter((el): el is HTMLElement => el != null);
    if (targets.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        // A single callback may report intersection-state changes for several elements at once —
        // picking the one earliest in document order among those "currently judged intersecting" is
        // more stable than "whichever fires the callback last wins."
        const visible = entries.filter((e) => e.isIntersecting).map((e) => e.target as HTMLElement);
        if (visible.length === 0) return;
        const topMost = visible.reduce((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? a : b));
        setActiveId(topMost.id);
      },
      { rootMargin: OBSERVER_ROOT_MARGIN },
    );
    targets.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey]);

  function handleClick(id: string) {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  if (items.length === 0) return null;

  return (
    <div className="page-outline-fab">
      {/* Collapsed state — one short dash per anchor, a purely visual hint that "there's a jumpable
          section here," no text, taking up minimal space. Clicking a tick itself can also jump — no
          need to hover-expand first just to click, saving a step. */}
      <div className="page-outline-ticks" aria-hidden="true">
        {items.map((item) => (
          <span
            key={item.id}
            className={`page-outline-tick${activeId === item.id ? " page-outline-tick-active" : ""}`}
            onClick={() => handleClick(item.id)}
          />
        ))}
      </div>
      {/* Expanded state — fades in via pure CSS (:hover in App.css) when hovering over
          .page-outline-fab as a whole, no JS-managed hover state needed: simpler, and no flicker from
          mouseenter/mouseleave timing. */}
      <div className="page-outline-panel" role="navigation" aria-label={t("outline.title")}>
        <div className="page-outline-panel-title">{t("outline.title")}</div>
        <ul>
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className={`page-outline-link${activeId === item.id ? " page-outline-link-active" : ""}`}
                onClick={() => handleClick(item.id)}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
