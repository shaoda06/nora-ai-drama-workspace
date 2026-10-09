export async function get<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error((await response.text()) || `读取失败（${response.status}）`);
  return response.json();
}
export const projectUrl = (name: string) => `/api/projects/${encodeURIComponent(name)}`;
export const styleUrl = (path: string) => `/api/krea2/files/${path.split('/').map(encodeURIComponent).join('/')}`;
export interface GenerationContext {
  scriptHtml: string; scriptUrl?: string; source?: string; issues: string[];
  shots: { id: string; duration: number | null; html: string }[];
  prompts: { english: string; chinese: string; englishUrl?: string; chineseUrl?: string };
  references: Record<'common' | 'segment', { name: string; label: string; kind: 'image' | 'video' | 'audio'; url?: string; missing?: boolean }[]>;
}
export interface SegmentVideo { key: string; url: string; run: string; stage: string; approved: boolean; candidateNumber: number; context: GenerationContext; fileRevision: string; deliveryStatus: string; taskStatus: string; checkedAt: string }
export interface FileItem { kind: string; name: string; title?: string; scenes?: string[]; script?: FileItem | null; storyboards?: Record<string, FileItem>; segments?: Record<string, { id: string; duration: number; scriptHtml: string; scriptUrl?: string; videos: SegmentVideo[] }[]>; key?: string; url?: string; children?: FileItem[]; files?: FileItem[]; summary?: string; category?: string; statusHtml?: string; approvalHtml?: string; sourceHtml?: string; duration?: string; media?: FileItem; doc?: Record<string, unknown>; prompts?: { english?: string; chinese?: string }; }
export interface Group { name: string; files: FileItem[] }
// Source records contain stage-specific fields; retain their original keys and text.
export type RecordData = Record<string, any>;

export function searchTree(items: FileItem[], search: string): FileItem[] {
  if (!search) return items;
  return items.flatMap(item => {
    if ((item.name + (item.summary || '')).toLowerCase().includes(search.toLowerCase())) return [item];
    const children = searchTree(item.children || item.files || [], search);
    return children.length ? [{ ...item, children, files: undefined }] : [];
  });
}
