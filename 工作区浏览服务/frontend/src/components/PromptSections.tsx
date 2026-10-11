import './PromptSections.css';

const chineseTitles: Record<string, string> = {
  subject_definitions: '主体定义',
  summary: '概述',
  retention_analysis: '保留分析',
  detailed_description: '详细描述',
  overall_soundscape: '整体声景',
  non_diegetic_music: '画外配乐',
};

export function PromptSections({ text, language }: { text: string; language: string }) {
  const headings = [...text.matchAll(/^(subject_definitions|summary|retention_analysis|detailed_description|overall_soundscape|non_diegetic_music):[ \t]*/gm)];
  if (!headings.length) return <pre className="segment-prompt-text">{text}</pre>;
  const introduction = text.slice(0, headings[0].index).trim();
  return <div className="prompt-sections">
    {introduction && <pre className="segment-prompt-text">{introduction}</pre>}
    {headings.map((heading, index) => <details className="prompt-section" key={index}>
      <summary><code>{heading[1]}</code>{language === 'zh' && ` - ${chineseTitles[heading[1]]}`}</summary>
      <pre>{text.slice(heading.index! + heading[0].length, headings[index + 1]?.index ?? text.length).trim()}</pre>
    </details>)}
  </div>;
}
