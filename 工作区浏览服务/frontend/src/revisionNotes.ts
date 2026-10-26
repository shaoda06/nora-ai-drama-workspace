import { useEffect, useSyncExternalStore } from 'react';
import { get, projectUrl } from './api';

export interface NoteInput { roundNumber?: number | null; segment: string; stage: string; run: string; text: string; fileRevision: string }
export interface RevisionNote extends NoteInput { updatedAt: string }
export interface OverallNote { number: number; text: string; updatedAt: string }
export interface SavedSceneNotes { notes: Record<string, RevisionNote>; rounds: Record<string, OverallNote> }
interface Draft { value: NoteInput; status: 'waiting' | 'saving' | 'saved' | 'error'; error?: string }
interface SceneState extends SavedSceneNotes { drafts: Record<string, Draft>; loaded: boolean; loading: boolean; error: string }
const scenes = new Map<string, SceneState>();
const listeners = new Set<() => void>();
const timers = new Map<string, ReturnType<typeof setTimeout>>();
const saving = new Set<string>();
export const noteKey = (value: Pick<NoteInput, 'segment' | 'stage' | 'run' | 'roundNumber'>) => `${value.roundNumber != null ? `round/${value.roundNumber}/` : ''}${value.segment}/${value.stage}/${value.run}`;
export const sceneNotesUrl = (project: string, episode: string, scene: string) => `${projectUrl(project)}/revision-notes/${episode}/${scene}`;
function state(url: string): SceneState {
  if (!scenes.has(url)) scenes.set(url, { notes: {}, rounds: {}, drafts: {}, loaded: false, loading: false, error: '' });
  return scenes.get(url)!;
}
function publish(url: string, value: SceneState) {
  scenes.set(url, value);
  listeners.forEach(listener => listener());
}
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
export async function loadNotes(url: string, refresh = false) {
  const current = state(url);
  if ((!refresh && current.loaded) || current.loading) return;
  publish(url, { ...current, loading: true, error: '' });
  try {
    const data = await get<SavedSceneNotes>(url);
    const latest = state(url);
    publish(url, { ...latest, notes: data.notes, rounds: data.rounds, drafts: Object.fromEntries(Object.entries(latest.drafts).filter(([, draft]) => draft.status !== 'saved')), loaded: true, loading: false });
    return data;
  } catch (error) {
    publish(url, { ...state(url), loading: false, error: String(error) });
  }
}
export async function prepareNotesExport(url: string) {
  await Promise.all(Object.keys(state(url).drafts).map(key => saveNote(url, key)));
  if (Object.values(state(url).drafts).some(draft => draft.status !== 'saved')) throw new Error('分段意见尚未保存成功，请先重试保存。');
  const data = await loadNotes(url, true);
  if (!data) throw new Error(state(url).error || '意见正在读取，请稍后重试。');
  return data;
}
export async function saveNotesExport(url: string, changes: { notes: (NoteInput & { expectedText: string })[]; rounds: { number: number; text: string; expectedText: string }[] }) {
  const response = await fetch(url + '/export', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes) });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(typeof error.detail === 'string' ? error.detail : `保存失败（${response.status}）`);
  }
  const data: SavedSceneNotes = await response.json();
  const current = state(url);
  const drafts = { ...current.drafts };
  for (const value of changes.notes) {
    const key = noteKey(value);
    delete drafts[key];
  }
  publish(url, { ...current, ...data, drafts });
}
export function editNote(url: string, value: NoteInput) {
  const key = noteKey(value);
  const timerKey = url + '/' + key;
  clearTimeout(timers.get(timerKey));
  const current = state(url);
  publish(url, { ...current, drafts: { ...current.drafts, [key]: { value, status: 'waiting' } } });
  timers.set(timerKey, setTimeout(() => { void saveNote(url, key); }, 1000));
}
export async function saveNote(url: string, key: string) {
  const requestKey = url + '/' + key;
  clearTimeout(timers.get(requestKey));
  timers.delete(requestKey);
  const current = state(url);
  const draft = current.drafts[key];
  if (!draft || draft.status === 'saved' || saving.has(requestKey)) return;
  const value = draft.value;
  saving.add(requestKey);
  publish(url, { ...current, drafts: { ...current.drafts, [key]: { value, status: 'saving' } } });
  let succeeded = false;
  try {
    const response = await fetch(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });
    if (!response.ok) throw new Error((await response.text()) || `保存失败（${response.status}）`);
    const note: RevisionNote = await response.json();
    const latest = state(url);
    const unchanged = latest.drafts[key].value === value;
    publish(url, { ...latest, notes: { ...latest.notes, [key]: note }, drafts: { ...latest.drafts, [key]: { value: latest.drafts[key].value, status: unchanged ? 'saved' : 'waiting' } } });
    succeeded = true;
  } catch (error) {
    const latest = state(url);
    publish(url, { ...latest, drafts: { ...latest.drafts, [key]: { value: latest.drafts[key].value, status: 'error', error: String(error) } } });
  } finally {
    saving.delete(requestKey);
  }
  // A response for older text must never replace what the user typed meanwhile.
  if (succeeded && state(url).drafts[key].value !== value) void saveNote(url, key);
}
export function hasUnsavedNotes() {
  return [...scenes.values()].some(scene => Object.values(scene.drafts).some(draft => draft.status !== 'saved'));
}
window.addEventListener('beforeunload', event => {
  if (hasUnsavedNotes()) {
    event.preventDefault();
  }
});
export function useSceneNotes(project: string, episode: string, scene: string, enabled = true) {
  const url = sceneNotesUrl(project, episode, scene);
  const value = useSyncExternalStore(subscribe, () => state(url));
  useEffect(() => { if (enabled) void loadNotes(url); }, [url, enabled]);
  return { ...value, url };
}
