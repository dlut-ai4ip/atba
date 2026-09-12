import { useEffect, useRef } from "react";

// If the scroll position falls within this distance (pixels) of the page bottom, it's considered
// "already back near the bottom," and auto-follow resumes — this is only used to judge "should we
// resume," not "should we stop" (the logic for stopping follow is in the onWheel/onKeyDown/
// onTouchMove comments below).
const STICKY_THRESHOLD_PX = 150;

// Whether the "bottom anchor" should auto-scroll along during streaming output/switching to a
// different step — a common chat/log-UI interaction pattern: follow the latest content by default (or
// the user would have to manually scroll to the bottom every time, which is annoying), but the moment
// the user actively scrolls up (wanting to look back at some piece of thinking or a retrieval result),
// stop interrupting them, until they scroll back near the bottom themselves and following resumes.
//
// **Hit this pitfall twice, worth recording**:
// The first version of follow() always used behavior:"smooth" regardless of context — during streaming
// output, content grows very fast, and follow() gets called on every delta; a smooth-scroll animation
// lasts a few hundred milliseconds, and while it's playing the browser keeps firing scroll events. The
// onScroll listener at the time recomputed "how far from the bottom" using the current (still growing)
// scrollHeight, and the result was usually still behind (the animation hadn't finished scrolling, and
// content had grown taller in the meantime), misjudging sticky as "the user scrolled away." Switching
// to behavior:"auto" for instant jumps during streaming fixed the animation's own lag.
//
// But the second version could still break sticky: even with an instant jump, "how fast content grows
// taller" could still outpace "the interval between two follow() calls" — e.g. one call aligns scrollY
// exactly to the bottom, and before the next delta arrives, the browser dispatches the scroll event for
// that call, at which point the distance really is 0; but if several deltas arrive within the same
// event-loop batch and only trigger one follow() call, the content could have grown by a hundred-plus
// pixels between two follow() calls, and the "distance from bottom" measured by the resulting scroll
// event would briefly exceed the threshold — a completely different cause from "the user actively
// scrolled up," yet misjudged the same way by the same "distance exceeds threshold → stop following"
// logic, and once misjudged there was no way back (once sticky becomes false, follow() stops
// scrolling, so the distance only grows further, with no chance to shrink back within the threshold on
// its own).
//
// The real fix: **only use real input-device gestures to judge "the user actively wants to leave the
// bottom"** — the mouse wheel scrolling up, arrow/page-up keys scrolling up, a touchscreen drag
// downward (content moving down = scrolling up a page). These events can't possibly be a side effect
// of the program calling scrollIntoView itself, so using them as the sole basis for "stop following"
// means no matter how fast content grows, it never gets misjudged. Scroll events (whether from the
// user or from us scrolling) are only used in the opposite direction — once the distance falls back
// within the threshold, following resumes; this direction has no "who triggered it" problem, whoever
// scrolled it back near the bottom counts.
export function useAutoScroll() {
  const bottomRef = useRef<HTMLDivElement>(null);
  const stickyRef = useRef(true);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, []);

  useEffect(() => {
    function onWheel(e: WheelEvent) {
      if (e.deltaY < 0) stickyRef.current = false;
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "ArrowUp" || e.key === "PageUp" || e.key === "Home") {
        stickyRef.current = false;
      }
    }
    let touchStartY: number | null = null;
    function onTouchStart(e: TouchEvent) {
      touchStartY = e.touches[0]?.clientY ?? null;
    }
    function onTouchMove(e: TouchEvent) {
      if (touchStartY == null) return;
      const y = e.touches[0]?.clientY;
      // The finger dragged down by more than a small margin of error — page content moves down along
      // with it, i.e. scrolling up a page.
      if (y != null && y > touchStartY + 10) stickyRef.current = false;
    }
    function onScroll() {
      const distanceFromBottom = document.documentElement.scrollHeight - (window.scrollY + window.innerHeight);
      if (distanceFromBottom < STICKY_THRESHOLD_PX) {
        stickyRef.current = true;
      }
    }
    window.addEventListener("wheel", onWheel, { passive: true });
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("touchstart", onTouchStart, { passive: true });
    window.addEventListener("touchmove", onTouchMove, { passive: true });
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("touchstart", onTouchStart);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("scroll", onScroll);
    };
  }, []);

  // The caller passes its own dependency array in its own useEffect (turns changing, the live
  // buffer's incremental text changing, etc.), calling follow() once per dependency change; whether it
  // actually scrolls is decided by the sticky state tracked above, not forced every time. Right after
  // the page mounts, when data first lands (e.g. navigating back to an already-completed node and
  // reading the persisted result), stickyRef still defaults to true (the user hasn't had a chance to
  // scroll yet), so this call takes the user straight to the final result — no need for a separate
  // piece of logic for "jump to the result when navigating back," it reuses the same judgment as
  // "streaming follow."
  //
  // The smooth parameter defaults to true (for "content has already settled, jump just this once"
  // scenarios, like landing on an already-completed node); the high-frequency calls during streaming
  // output should pass false, for the reasons in the pitfall notes above.
  function follow(smooth = true) {
    if (stickyRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "end" });
    }
  }

  return { bottomRef, follow };
}
