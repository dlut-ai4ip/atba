import ReactMarkdown from "react-markdown";

// The task text fed to the agent by the backend, and the text content the agent itself produces, are
// already in Markdown format (## headings, ordered/unordered lists, **bold**, etc. — see _task_text()
// in atba/step3.py); this used to be dropped straight into a <div> as plain text, so syntax markers
// like "##" and "1." displayed as literal characters, which read awkwardly. This uniformly renders
// them into real headings/lists/bold via react-markdown, styled by the .markdown-body rules in App.css
// (which follow the light/dark theme's CSS variables, not hardcoded colors).
export function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown>{text}</ReactMarkdown>
    </div>
  );
}
