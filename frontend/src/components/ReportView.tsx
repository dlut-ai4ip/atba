import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { MermaidDiagram } from "./MermaidDiagram";
import { usePageOutline } from "../lib/PageOutlineContext";

// The two possible heading texts per step 6's "citation format" convention (see the "citation format"
// section of atba/prompts/step6.zh.md/.en.md) — which language the report itself is in is decided by
// the lang parameter at generation time, which doesn't necessarily match the current interface
// language setting (if the user has since switched the UI language), so both are recognized, without
// relying on the current UI's useT().
const REFERENCES_HEADINGS = ["参考文献", "References"];

// Citations are clickable, jumping to the reference list — an in-text citation is a Markdown link
// `[(Author, Year)](#ref-N)`, where N is which entry the model believes this reference is in the
// "References" list (see the "citation format" section in the prompts). But **this component doesn't
// trust the model's own N**: an LLM occasionally miscounts (the backend's
// atba/step6.py's _dangling_ref_targets only does the coarse check of "is N out of range," it can't
// verify "does N actually correspond to that paper") — what genuinely decides where clicking #ref-N
// jumps to is this effect reassigning ids based on the reference list's actual rendered order in the
// DOM (first entry = ref-1, second = ref-2, ...), independent of whatever number text the model wrote
// in front of each list entry itself. This way, even if the model writes a wrong/duplicate number in
// front of some list entry, as long as the list's own **order** isn't scrambled (far less likely than
// a single digit being mistyped), the jump-to-click still lands accurately — and even in the worst
// case where both the model's internal numbering and order are scrambled, the worst outcome is landing
// on the wrong entry in the list, not jumping to a position that doesn't exist on the page at all (that
// case is blocked by backend validation, which triggers a retry).
function assignReferenceIds(root: HTMLElement) {
  const headings = Array.from(root.querySelectorAll("h2"));
  // Matches heading text by "contains" rather than "the whole line equals exactly" — hit a real
  // pitfall once: the model's actual output often carries a section number in the heading, e.g.
  // "5. 参考文献" (mimicking the "### 5. 参考文献" style the prompt itself uses to describe the
  // report structure); matching the exact string "参考文献" would never match because of the extra
  // "5. " prefix, causing this function to simply never find the references heading and silently do
  // nothing — the user clicks a citation link and nothing happens, looking like the feature is
  // completely broken (the backend's atba/step6.py's _find_references_heading hit the exact same
  // pitfall, fixed the same way).
  const refsHeading = headings.find((h) =>
    REFERENCES_HEADINGS.some((label) => h.textContent?.includes(label)),
  );
  if (!refsHeading) return;

  // The reference list is the first ordered list after this heading and before the next level-2
  // heading or divider — not assumed to be the heading's immediate next sibling, since the model
  // occasionally inserts a sentence of explanation between the heading and the list.
  let el: Element | null = refsHeading.nextElementSibling;
  let list: HTMLOListElement | null = null;
  while (el && el.tagName !== "H2" && el.tagName !== "HR") {
    if (el.tagName === "OL") {
      list = el as HTMLOListElement;
      break;
    }
    el = el.nextElementSibling;
  }
  if (!list) return;

  Array.from(list.children).forEach((li, i) => {
    if (li.tagName === "LI") li.id = `ref-${i + 1}`;
  });
}

// The on-page navigation (PageOutlineNav.tsx, per user feedback "the output is pretty long, can a
// jump-to nav be added") — step 6's report is itself a final document with a genuine heading
// structure (unlike the other steps: their "headings" are mostly text that happens to come along with
// the prompt template and can't be used directly as page structure, see how the other Step*RunPage's
// in AgentRunPage.tsx handle it — each manually lists a fixed set of section ids), so here the
// rendered h2 headings can just be scanned directly for nav items, no need to hand-maintain a list.
// Reuses the same h2 list assignReferenceIds already obtained in one DOM query — "report-heading-N"
// (an index) is used instead of a slug generated from the heading text: heading text could in
// principle repeat (the model occasionally reuses wording across sections), and the index is the only
// id source guaranteed not to collide.
function buildOutlineFromHeadings(root: HTMLElement): { id: string; label: string }[] {
  const headings = Array.from(root.querySelectorAll("h2"));
  return headings.map((h, i) => {
    h.id = `report-heading-${i}`;
    return { id: h.id, label: h.textContent ?? "" };
  });
}

// Clicking a citation link — instead of the browser's native "instant jump" (href="#ref-N"'s default
// behavior), this is manually taken over to do a smooth scroll + a brief highlight flash at the
// landing spot, consistent with the same interaction-polish requirement recorded in
// useAutoScroll.ts's "navigating back to a node needs a transition"; block:"center" (not "start") is
// deliberate too — a reference entry is usually short, and centering it makes it easier to spot at a
// glance than pinning it to the top edge of the viewport, and more clearly associates it with "I just
// got jumped here."
function handleCitationClick(e: React.MouseEvent<HTMLAnchorElement>, href: string) {
  const id = href.slice(1);
  const target = document.getElementById(id);
  if (!target) return; // Shouldn't happen in principle (assignReferenceIds already assigns an id to every entry), a defensive fallback
  e.preventDefault();
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.classList.add("citation-target-flash");
  window.setTimeout(() => target.classList.remove("citation-target-flash"), 1500);
}

// The dedicated rendering component for step 6's theoretical contribution report — different from
// Markdown.tsx (used for the scattered short text bubbles in a transcript) in that: (1) it needs to
// recognize ```mermaid code blocks and hand them to MermaidDiagram to render as a diagram, instead of
// displaying the raw Mermaid source text as-is; (2) the report is a long document, using its own
// .report-body container for layout (heading hierarchy, tables, dividers etc. are more complete here
// than in .markdown-body), not reusing the transcript bubbles' compact styling; (3) it attaches
// remark-gfm — the appendix's "candidate theory comparison table" uses standard GFM pipe-table syntax,
// and react-markdown by default runs plain commonmark, which doesn't recognize table syntax (the pipe
// characters would just be spat out as plain text) — this was a real pitfall hit in testing; (4)
// citations are clickable, jumping to the reference list — see the comments on assignReferenceIds/
// handleCitationClick above.
export function ReportView({ markdown }: { markdown: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { setItems: setOutlineItems } = usePageOutline();

  // Whenever markdown changes (a streaming append/switching to a different report), ids are
  // reassigned and the nav items are rescanned — during streaming, the "References" section only
  // appears once the report is written all the way to the end, so every earlier render's call to
  // assignReferenceIds returns early for not finding the heading, without erroring or causing a
  // performance problem (it's just a few DOM queries); the nav items, meanwhile, grow as new h2
  // headings appear while the report is generated, the list growing along with it rather than
  // appearing for the first time only once generation finishes.
  useEffect(() => {
    if (containerRef.current) {
      assignReferenceIds(containerRef.current);
      setOutlineItems(buildOutlineFromHeadings(containerRef.current));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [markdown]);

  return (
    <div className="report-body" ref={containerRef}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code(props) {
            const { className, children, ...rest } = props;
            // react-markdown v10 no longer passes an inline property to distinguish inline code — but
            // an inline code span was never going to carry a language-xxx class to begin with (only a
            // fenced code block with three backticks + a language tag gets one), so checking the
            // language-mermaid class alone is already reliable enough to identify "this is a mermaid
            // code block."
            const isMermaidBlock = /language-mermaid\b/.test(className || "");
            if (isMermaidBlock) {
              return <MermaidDiagram code={String(children).replace(/\n$/, "")} />;
            }
            return (
              <code className={className} {...rest}>
                {children}
              </code>
            );
          },
          a(props) {
            const { href, children, ...rest } = props;
            const isCitation = typeof href === "string" && href.startsWith("#ref-");
            if (isCitation) {
              return (
                <a href={href} className="citation-link" onClick={(e) => handleCitationClick(e, href)} {...rest}>
                  {children}
                </a>
              );
            }
            // Other links appearing in the report body (e.g. a DOI a reference entry carries) — open
            // in a new tab, not replacing the report currently being read on the current page.
            return (
              <a href={href} target="_blank" rel="noreferrer" {...rest}>
                {children}
              </a>
            );
          },
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
