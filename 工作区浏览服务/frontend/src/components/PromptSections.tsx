import './PromptSections.css';

export function PromptSections({ text }: { text: string }) {
  const headings = [...text.matchAll(/^(subject_definitions|summary|retention_analysis|detailed_description|overall_soundscape|non_diegetic_music):[ \t]*/gm)];
  if (!headings.length) return <pre className="segment-prompt-text">{text}</pre>;
  const introduction = text.slice(0, headings[0].index).trim();
  return <div className="prompt-sections">
    {introduction && <pre className="segment-prompt-text">{introduction}</pre>}
    {headings.map((heading, index) => <details className="prompt-section" key={index}>
      <summary><code>{heading[1]}</code></summary>
      <pre>{text.slice(heading.index! + heading[0].length, headings[index + 1]?.index ?? text.length).trim()}</pre>
    </details>)}
  </div>;
}
