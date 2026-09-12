import { useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { BORROWING_PATTERN_LABEL_KEY, CandidateCard } from "./CandidateCard";
import { useT } from "../i18n";
import type { CandidateTheory, PairwiseComparison } from "../types";

// A "flowith-like card canvas" view (a requirement the user raised after seeing a flowith screenshot,
// see the conversation record) — the user explicitly required that connecting lines must label the
// real pairwise comparison win/loss relationship (pairwise_comparisons), not just decoratively group
// by mechanism_borrowing_pattern, so every edge here corresponds directly to one PairwiseComparison
// record, and the edge's label is the winner (or "=" for a tie) — not a visual effect drawn out of
// thin air.
//
// Layout — the candidate count is usually 3-5, and pairwise comparisons form close to a complete
// graph (C(n,2) edges); a force-directed/auto-layout library would instead make node positions
// different on every refresh with edges crossing everywhere; the simplest static layout is used
// instead, "arrange in a circle by rank order" — node position depends only on rank, so the canvas
// looks the same every time for the same run, and edges naturally radiate outward rather than
// scattering.
//
// Edge endpoints — a genuine floating edge (with the line's endpoint landing precisely on the card's
// border) needs computing the intersection of a node's rectangle with a line; a shortcut is taken here
// using a react-flow feature instead: edges render below nodes by default (lower z-index), so forcing
// both the source and target Handles to sit exactly at the node's center (an inline style overriding
// react-flow's default edge-position for Handles) makes the edge start drawing from the node's center,
// but it's visually covered by the opaque node card on top, making it look like "the line connects to
// the card's edge" without actually computing the intersection point.
//
// Hover highlights rather than hide/filter — the user never asked to "reduce visual complexity," only
// that "the connecting lines be meaningful"; with this few candidates (3-5), showing everything isn't
// a hairball, and hover highlighting is an aid for the specific need of "who has this candidate been
// compared against," not a forced filter meant to handle a larger scale of data.
//
// Clicking a node — reuses CandidateCard to render the full detail (in a popover), rather than
// rewriting the field display a second time, guaranteeing the candidate detail content seen in the
// list view and the canvas view matches verbatim, see the top-of-file comment in CandidateCard.tsx.

const CANVAS_HEIGHT = 560;
// Fixed node dimensions — passed directly to react-flow's Node.width/height (v12 supports using these
// two fields for initial layout before measuring), avoiding both the initial flicker of "laid out at
// zero size first, then jumping once the real size is measured" and giving the centering algorithm
// below a definite width/height to work with. NODE_HEIGHT is an estimate (the actual card height
// varies slightly depending on whether a candidate is selected/has a tied tag; the circular layout
// only needs to be visually roughly centered, not pixel-perfectly aligned with the real rendered
// height).
const NODE_WIDTH = 220;
const NODE_HEIGHT = 210;
// The radius — an earlier bug treated position as the node's center (react-flow's position is actually
// the top-left corner), causing four 220px-wide cards to end up almost entirely stacked on top of each
// other (user feedback: "they're all piled together"). Now the center point on the circle is computed
// first, then half the width/height is subtracted to convert to the top-left coordinate react-flow
// expects (see the nodes useMemo below), and the radius was enlarged accordingly to guarantee enough
// gap between every pair of 3-5 candidate cards so they don't overlap.
const RADIUS = 300;

interface CandidateNodeData {
  candidate: CandidateTheory;
  rank: number | null;
  isSelected: boolean;
  isTied: boolean;
  hovered: boolean;
  dimmed: boolean;
  [key: string]: unknown;
}

function truncate(text: string, max: number): string {
  const trimmed = text.trim();
  return trimmed.length > max ? `${trimmed.slice(0, max)}…` : trimmed;
}

// A hidden Handle forced to the center — see the "center-handle edge-endpoint trick" in the top-of-file
// comment. One source and one target is enough; a node might be both the start and end of an edge
// across different comparisons, and react-flow requires a connectable handle at each end.
const CENTER_HANDLE_STYLE: React.CSSProperties = {
  position: "absolute",
  top: "50%",
  left: "50%",
  transform: "translate(-50%, -50%)",
  opacity: 0,
  pointerEvents: "none",
};

function CandidateNode({ data }: NodeProps & { data: CandidateNodeData }) {
  const t = useT();
  const { candidate, rank, isSelected, isTied, hovered, dimmed } = data;
  const v = candidate.virtue_scores;
  return (
    <div
      className={`candidate-node${isSelected ? " candidate-node-selected" : ""}${hovered ? " candidate-node-hovered" : ""}${dimmed ? " candidate-node-dimmed" : ""}`}
    >
      <Handle type="target" position={Position.Top} style={CENTER_HANDLE_STYLE} />
      <Handle type="source" position={Position.Bottom} style={CENTER_HANDLE_STYLE} />
      <div className="candidate-node-header">
        {rank !== null && <span className="candidate-rank">#{rank}</span>}
        <span className="candidate-name">{candidate.candidate_name}</span>
      </div>
      <div className="candidate-node-tags">
        {isSelected && <span className="candidate-tag candidate-tag-selected">{t("result4.tagSelected")}</span>}
        {isTied && <span className="candidate-tag candidate-tag-tied">{t("result4.tagTied")}</span>}
        {candidate.is_baseline && <span className="candidate-tag candidate-tag-baseline">{t("result4.tagBaseline")}</span>}
        <span className="assumption-type-badge candidate-node-badge">
          {t(BORROWING_PATTERN_LABEL_KEY[candidate.mechanism_borrowing_pattern] ?? candidate.mechanism_borrowing_pattern)}
        </span>
      </div>
      {/* Four-virtue scoring — per the user's request to "put the virtue scores on every card": canvas
          card space is tight, so only the numeric badges are shown (not the graph_based_rationale
          reasoning text itself, which is left for the full CandidateCard in the detail popover),
          laid out in a 2x2 grid so it stays tidy regardless of Chinese/English label length, instead of
          leaving line-wrapping to flex-wrap's whims. */}
      <div className="candidate-node-virtues">
        <span className="virtue-score">{t("result4.consilience")} {v.consilience}</span>
        <span className="virtue-score">{t("result4.coherence")} {v.coherence}</span>
        <span className="virtue-score">{t("result4.parsimony")} {v.parsimony}</span>
        <span className="virtue-score">{t("result4.precision")} {v.precision}</span>
      </div>
      <p className="candidate-node-excerpt">{truncate(candidate.explanation_of_phenomenon, 90)}</p>
    </div>
  );
}

const NODE_TYPES = { candidateNode: CandidateNode };

export function CandidateCanvas({
  candidates,
  rankedNames,
  selectedName,
  tiedNames,
  comparisons,
}: {
  candidates: CandidateTheory[];
  rankedNames: string[];
  selectedName: string;
  tiedNames: string[];
  comparisons: PairwiseComparison[];
}) {
  const t = useT();
  const [hoveredName, setHoveredName] = useState<string | null>(null);
  const [openName, setOpenName] = useState<string | null>(null);

  // While the detail popover is open: (1) Esc closes it — the popover's content is long (the full
  // candidate card, often needing several screens of scrolling to read fully, see
  // .candidate-detail-scroll's scroll area below), and keyboard users don't want to reach for the
  // close button in the corner every time; (2) locks scrolling on the page behind it — the popover is
  // a position:fixed overlay covering the viewport, but the overlay itself doesn't intercept the
  // wheel, so scrolling with the mouse over the overlay's empty space (not over the card) would scroll
  // the page behind it, misaligning the card and background content jarringly — locking it matches the
  // common popover expectation that "the background freezes while the popover is open" better. Both
  // only take effect while openName has a value, and must be restored on close/unmount, so this side
  // effect never leaks past the popover closing.
  useEffect(() => {
    if (!openName) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpenName(null);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [openName]);

  const rankOf = (name: string) => {
    const i = rankedNames.indexOf(name);
    return i === -1 ? null : i + 1;
  };

  // Arranged in a circle by rank order — see the top-of-file comment; a candidate whose rank can't be
  // found (shouldn't happen in principle, this is a fallback) sorts to the end, with original order as
  // the secondary sort key for ties, guaranteeing the same data always renders at the same angles.
  const ordered = useMemo(() => {
    const originalOrder = new Map(candidates.map((c, i) => [c.candidate_name, i]));
    return [...candidates].sort((a, b) => {
      const ra = rankOf(a.candidate_name) ?? 99;
      const rb = rankOf(b.candidate_name) ?? 99;
      if (ra !== rb) return ra - rb;
      return (originalOrder.get(a.candidate_name) ?? 0) - (originalOrder.get(b.candidate_name) ?? 0);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidates, rankedNames]);

  const nodes: Node[] = useMemo(() => {
    const n = ordered.length;
    return ordered.map((c, i) => {
      // Starts at the 12 o'clock position and goes clockwise, matching the intuition that "#1 belongs
      // at the top"
      const angle = (2 * Math.PI * i) / Math.max(n, 1) - Math.PI / 2;
      const isHovered = hoveredName === c.candidate_name;
      const isDimmed = hoveredName !== null && !isHovered && !involvesHovered(comparisons, hoveredName, c.candidate_name);
      return {
        id: c.candidate_name,
        type: "candidateNode",
        // The center point on the circle (RADIUS*cos, RADIUS*sin) minus half the width/height,
        // converted to the top-left coordinate react-flow expects — previously the point on the
        // circle was used directly as the top-left corner, meaning every card's top-left corner
        // hugged the circle while the card body itself skewed toward the center, so four 220px-wide
        // cards ended up almost entirely piled at the center — that was the real cause of "piled
        // together."
        position: {
          x: RADIUS * Math.cos(angle) - NODE_WIDTH / 2,
          y: RADIUS * Math.sin(angle) - NODE_HEIGHT / 2,
        },
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        data: {
          candidate: c,
          rank: rankOf(c.candidate_name),
          isSelected: c.candidate_name === selectedName,
          isTied: tiedNames.includes(c.candidate_name),
          hovered: isHovered,
          dimmed: isDimmed,
        } satisfies CandidateNodeData,
        draggable: false,
        connectable: false,
      };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ordered, hoveredName, selectedName, tiedNames, comparisons]);

  // Edges no longer carry a text label — per user feedback that the canvas text was too crowded (4
  // candidates already means 6 edges, and stacking a candidate name or "=" in the middle of each
  // already-dense edge made the text unreadably cramped). No information about who won is lost:
  // hover highlighting already shows "who this candidate has been compared against," and the specific
  // win/loss result is spelled out entry-by-entry in the "pairwise comparison judgments" section
  // expanded below — the canvas itself is only responsible for letting someone see at a glance "which
  // candidates have a comparison relationship," the topology, not for also displaying each edge's
  // specific conclusion.
  const edges: Edge[] = useMemo(
    () =>
      comparisons.map((c, i) => {
        const touchesHovered = hoveredName !== null && (c.candidate_a === hoveredName || c.candidate_b === hoveredName);
        const dimmed = hoveredName !== null && !touchesHovered;
        return {
          id: `cmp-${i}`,
          source: c.candidate_a,
          target: c.candidate_b,
          className: `candidate-edge${touchesHovered ? " candidate-edge-hovered" : ""}${dimmed ? " candidate-edge-dimmed" : ""}`,
        };
      }),
    [comparisons, hoveredName],
  );

  const openCandidate = openName ? candidates.find((c) => c.candidate_name === openName) ?? null : null;

  if (candidates.length === 0) return null;

  return (
    <div className="candidate-canvas-wrap">
      <p className="note candidate-canvas-hint">{t("result4.canvasHint")}</p>
      <div className="candidate-canvas" style={{ height: CANVAS_HEIGHT }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          fitView
          fitViewOptions={{ padding: 0.25 }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={true}
          // panOnScroll is not enabled — per user feedback that "it disappears after a while": with
          // panOnScroll on, as long as the mouse is hovering over the canvas, a user trying to scroll
          // the normal page with the mouse wheel would have that scroll swallowed by react-flow as
          // "pan the canvas content," quietly panning the candidate nodes out of the canvas's visible
          // area — looking like it "disappeared on its own after a while," when it was really just
          // dragged out of view. Dragging the canvas background (panOnDrag is on by default) still
          // works when panning is actually wanted.
          //
          // Zoom — the user asked for "the wheel should zoom," but directly copying react-flow's
          // default of "a bare wheel = zoom" would reintroduce the exact problem described in the
          // comment above (hovering over the canvas wanting to scroll the page, only to have it
          // swallowed as a zoom). The same compromise as Google Maps/Figma is used: the wheel only
          // zooms while Ctrl is held (a trackpad two-finger pinch's wheel event on Mac also carries
          // ctrlKey, equivalent to "zoom"); a bare wheel passes through to the page's normal scroll as
          // usual. This isn't a prop combination react-flow specifically documents, it was confirmed
          // by reading @xyflow/system's source (createZoomOnScrollHandler): zoomOnScroll=true attaches
          // the zoom wheel listener; preventScrolling=false makes it return early without calling
          // preventDefault whenever ctrl isn't held, so the wheel event bubbles to the page unchanged;
          // only while ctrl is held does it actually invoke d3's zoom and block the default scroll.
          zoomOnScroll
          preventScrolling={false}
          proOptions={{ hideAttribution: true }}
          onNodeMouseEnter={(_, node) => setHoveredName(node.id)}
          onNodeMouseLeave={() => setHoveredName(null)}
          onNodeClick={(_, node) => setOpenName(node.id)}
        >
          <Background gap={24} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>

      {openCandidate && (
        <div className="candidate-detail-overlay" role="dialog" aria-modal="true" onClick={() => setOpenName(null)}>
          {/* The header (close button) is split into its own flex block, separate from the scrollable
              body below — previously the close button was absolutely positioned inside the same
              scroll container as the whole popover (including the body); the candidate detail content
              is very long, with the scroll area's real height over 5x the viewport, so scrolling down
              a few screens would carry the close button out of view with no way to find it. Now the
              header holding the close button doesn't scroll at all; only
              .candidate-detail-scroll below it scrolls, so the close button stays put no matter how
              far down you scroll. */}
          <div className="candidate-detail-overlay-inner" onClick={(e) => e.stopPropagation()}>
            <div className="candidate-detail-header">
              <button type="button" className="candidate-detail-close" onClick={() => setOpenName(null)} aria-label={t("result4.closeDetail")}>
                ×
              </button>
            </div>
            <div className="candidate-detail-scroll">
              <ol className="candidate-cards candidate-cards-overlay">
                <CandidateCard
                  candidate={openCandidate}
                  rank={rankOf(openCandidate.candidate_name)}
                  isSelected={openCandidate.candidate_name === selectedName}
                  isTied={tiedNames.includes(openCandidate.candidate_name)}
                />
              </ol>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function involvesHovered(comparisons: PairwiseComparison[], hoveredName: string, otherName: string): boolean {
  if (hoveredName === otherName) return true;
  return comparisons.some(
    (c) =>
      (c.candidate_a === hoveredName && c.candidate_b === otherName) ||
      (c.candidate_b === hoveredName && c.candidate_a === otherName),
  );
}
