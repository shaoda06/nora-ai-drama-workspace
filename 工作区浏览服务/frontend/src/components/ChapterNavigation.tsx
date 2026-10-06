import { useId, useMemo, useState } from 'react';

export type ChapterHeading = { id: string; text: string; level: number };
type Chapter = ChapterHeading & { children: Chapter[] };

export function ChapterNavigation({ headings, onNavigate }: { headings: ChapterHeading[]; onNavigate: (id: string) => void }) {
  const [open, setOpen] = useState(true);
  const chapters = useMemo(() => {
    const roots: Chapter[] = [];
    const parents: Chapter[] = [];
    for (const heading of headings) {
      const chapter: Chapter = { ...heading, children: [] };
      while (parents.length && parents[parents.length - 1].level >= heading.level) parents.pop();
      (parents.length ? parents[parents.length - 1].children : roots).push(chapter);
      parents.push(chapter);
    }
    return roots;
  }, [headings]);
  return chapters.length ? <details className="chapters" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>章节导航</summary>
    {open && <nav aria-label="章节导航"><ChapterList chapters={chapters} onNavigate={onNavigate} /></nav>}
  </details> : null;
}

function ChapterList({ chapters, onNavigate }: { chapters: Chapter[]; onNavigate: (id: string) => void }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const prefix = useId();
  return <ul className="chapter-list">{chapters.map((chapter, index) => {
    const open = expanded === chapter.id;
    const childrenId = `${prefix}-${index}`;
    return <li key={chapter.id}>
      <div className="chapter-row">
        <button className="link chapter-link" onClick={() => onNavigate(chapter.id)}>{chapter.text}</button>
        {chapter.children.length > 0 && <button className="link chapter-toggle" aria-label={`${open ? '收起' : '展开'}章节：${chapter.text}`} aria-expanded={open} aria-controls={childrenId} onClick={() => setExpanded(open ? null : chapter.id)}>{open ? '收起 ▴' : '展开 ▾'}</button>}
      </div>
      {open && chapter.children.length > 0 && <div id={childrenId}><ChapterList chapters={chapter.children} onNavigate={onNavigate} /></div>}
    </li>;
  })}</ul>;
}
