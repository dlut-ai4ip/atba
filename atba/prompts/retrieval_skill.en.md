## Retrieval Skill: How to Use the `search_scopus` and `get_paper_abstract` Tools Well

You have two tools:
- `search_scopus(query, max_results)` — give it a Scopus concept query and it automatically adds the
  UTD24 journal-range restriction and returns real results (a paper list + total hit count). **You must
  decide for yourself what to search, how many rounds to run, and when you have searched enough** — a
  single tool call is not enough. This is the most important part of this skill: search is a process you
  drive by judging results and adjusting, not "generate one query and stop."
- `get_paper_abstract(doi)` — the paper list `search_scopus` returns does not itself carry
  abstracts (a Scopus API limitation); to read a paper's full abstract, look it up by its `doi` (not
  `scopus_id`) with this tool, which internally tries Semantic Scholar then OpenAlex. **Only call it for papers you have decided to cite** (i.e. ones going into the final
  `cited_evidence`) — most search results only serve to judge "is this query on target," and the papers
  you actually end up citing are usually just a few; fetching an abstract for every hit wastes quota.
  Conversely, **before deciding to cite a paper, you must fetch its abstract first** — don't judge
  whether a paper supports/contradicts a conclusion from the title alone; a title rarely reveals which
  specific mechanism the paper actually covers.

### Scopus query syntax

- `TITLE-ABS-KEY()`: searches title, abstract, and keywords together (most common, broadest coverage —
  default to this)
- `TITLE()` / `ABS()` / `KEY()`: title / abstract / keywords only
- `AUTH()`: author name; `PUBYEAR`: publication year; `DOCTYPE()`: document type (ar=article, re=review)
- Boolean operators `AND`/`OR`/`AND NOT`, parentheses for grouping, quotes for phrases, `*` for wildcards
- Write only the concept part — **do not construct the journal-range restriction yourself** (the
  EXACTSRCTITLE-based UTD24 filter is added automatically by the tool)
- If what you're searching for is originally in Chinese, translate it into standard English academic
  terminology in your own understanding first, then build the query — Scopus indexes mostly
  English-language literature

### Don't stack too many ANDs — recall first, narrow later

A real case we actually hit (run `4b637242b0d24fa097444362d23ffb66`): 6 consecutive searches on the
same direction, and the first 5 came back at zero or near-zero hits, all for the same reason — the
query ANDed 3-4 independent concept clusters together, e.g.:

- `entrepreneur* AND narrative* AND investor* AND (decept* OR fraud OR ...)` — 0 hits
- `entrepreneur* AND (fraud OR deception) AND (narrative OR storytelling OR story OR account)` — 0 hits

Once `AND` was cut down to just 1-2 concept clusters, the same underlying concepts started hitting
right away:
- `"entrepreneurial storytelling" OR "entrepreneurial narrative" OR "cultural entrepreneurship"` —
  26 hits
- `entrepreneur* AND storytell* AND (fraud OR deception OR fabricat* OR "false narrative")` — 1 hit

**Why**: `TITLE-ABS-KEY()` only searches a small span of text — title, abstract, and keywords. The
odds that a single paper's abstract literally mentions 3-4 independent concept clusters at once
(even with synonyms ORed within each cluster) are inherently low — most papers foreground only one or
two of your concepts. More `AND`s means exponentially fewer hits; this is a query **structure**
problem, not evidence the literature doesn't exist.

**What to actually do**:
- **Keep the number of independent `AND`-joined concept clusters per query to at most 2, rarely 3**
  (not counting the journal filter, which the tool adds automatically) — beyond 3 `AND`-joined
  clusters, you'll very likely get zero hits no matter how you tweak the synonyms.
- **When a level "misses," your first instinct should be to drop one `AND` cluster (loosen the
  structure), not keep the same `AND` structure and just swap synonyms** — rewording fixes "bad
  phrasing this one time"; cutting an `AND` fixes "the structure was too picky to begin with." These
  are different problems. Several rewrite-retries that keep the same number of `AND` clusters and only
  change wording will likely all fail the same way (exactly what happened in the case above: 4
  consecutive rewrites kept the same AND structure before someone finally thought to loosen it).
- When you want to express several concepts at once, prefer **ORing synonyms within the same `AND`
  cluster** to raise the hit rate for one concept, rather than adding a new `AND` cluster to "pin it
  down precisely" — the latter is a precision mindset; this step needs recall. Judging exactly which
  part of the mechanism a paper covers is your job after you've read it, not something the query
  string should be filtering for.

### Three-level degrading search protocol (core strategy — follow it strictly)

For each mechanism/proposition you need to check, try the following levels in order — **every hit must
be labeled with which level it was found at**; a hit at "the broad disciplinary level" is explicitly
less credible than a hit at "the exact-mechanism level," and the two must never be conflated:

1. **Exact-mechanism match**: phrase the query as close as possible to the specific mechanism wording
   (e.g. something specific enough to map directly onto one particular part).
2. **If it misses, or hits are too few/clearly irrelevant, drop to the theory-family level**: switch to
   the broader theoretical tradition/construct family this direction belongs to.
3. **If the theory-family level still misses, drop to the broad disciplinary level**: the whole
   direction's broad literature, no longer requiring an exact match to the specific mechanism.

**Rewrite-and-retry rule**: keyword/semantic search is sensitive to wording — **before declaring any
level a "miss," you must first rephrase the query and search once more**, to rule out "a false negative
purely from bad phrasing this one time" — you may not drop to the next level just because the first
attempt at a level came back empty. **A rewrite is not just swapping synonyms** — if the previous query
ANDed 3+ concept clusters, your first choice for the rewrite should be dropping one `AND` cluster
(loosen the structure, see above), not keeping the same `AND` structure and changing a few words; only
reach for synonym swaps once the `AND` structure is already lean (1-2 clusters). In other words, each of
the three levels may take up to two searches (original phrasing + one rewrite).

**When all levels and their rewrites are exhausted with no hit**: report honestly that this is "not
covered by retrieval" — **this is not a failure**, it is a legitimate conclusion; attach every query you
actually tried and its hit count as evidence that you genuinely searched and came up empty.

**If a hit already fully explains what you're checking**: report that honestly — do not keep searching
to "prove there's something here," and do not selectively ignore that literature.

### After each search, ask yourself

- Does this result's volume and relevance mean I should keep dropping levels, or can I stop here?
- If results are zero or few: is it a wording problem (rewrite and retry) or does this level genuinely
  have nothing (drop a level)?
- If results are plentiful but none quite on point: is the query too broad (tighten it), or does this
  direction genuinely have a lot of literature that never touches the specific point you're checking
  (which is itself a "hit but the mechanism isn't covered" signal)?

**Audit requirement**: when you finish, you must be able to state **every** query you actually used with
`search_scopus` (including rewrite-retry versions) — not just the last successful one; the complete trail
is an audit requirement, not optional.
