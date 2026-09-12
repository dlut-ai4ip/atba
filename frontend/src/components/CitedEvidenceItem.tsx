import { useT } from "../i18n";
import type { CitedEvidence } from "../types";

// Originally a component private to Step3ResultSummary.tsx; step 4's theoretical deep retrieval
// (theoretical_grounding.key_findings) and step 5's interrogation retrieval verification reuse the
// same CitedEvidence structure, so it's factored out into its own file instead of writing the same
// JSX three times.
export function CitedEvidenceItem({ e }: { e: CitedEvidence }) {
  const t = useT();
  return (
    <li className="cited-evidence-item">
      <div className="cited-evidence-title">
        {e.title}
        {e.year ? `（${e.year}）` : ""}
      </div>
      <div className="cited-evidence-meta">
        {/* authors/source_title/doi can all be missing (especially authors — early testing found the
            agent sometimes didn't copy over the author field search_scopus had already returned); a
            join is used instead of hardcoding " · " before each segment, avoiding a lone leading
            separator when one segment is missing, which would read like the data is broken */}
        {[e.authors.length > 0 ? e.authors.join(", ") : null, e.source_title].filter(Boolean).join(" · ")}
        {e.doi ? (
          <>
            {(e.authors.length > 0 || e.source_title) && " · "}
            <a href={`https://doi.org/${e.doi}`} target="_blank" rel="noreferrer">
              {e.doi}
            </a>
          </>
        ) : null}
      </div>
      <p className="cited-evidence-snippet">
        <span className="cited-evidence-tag">{t("cited.rationale")}</span>
        {e.relevant_snippet}
      </p>
      {/* The raw abstract is collapsed by default — relevant_snippet already is the basis for the
          judgment; the full abstract is there for someone who wants to independently verify "was
          anything taken out of context," not something meant to be read every time */}
      {e.abstract && (
        <details className="cited-evidence-abstract-details">
          <summary>{t("cited.viewAbstract")}</summary>
          <p className="cited-evidence-abstract">{e.abstract}</p>
        </details>
      )}
    </li>
  );
}
