import { useEffect, useSyncExternalStore } from 'react';
import { get, projectUrl } from './api';

export interface NoteInput { segment: string; stage: string; run: string; text: string; fileRevision: string }
export interface RevisionNote extends NoteInput { updatedAt: string }
interface Draft { value: NoteInput; status: 'waiting' | 'saving' | 'saved' | 'error'; error?: string }
interface SceneState { notes: Record<string, RevisionNote>; drafts: Record<string, Draft>; loaded: boolean; loading: boolean; error: string }
const scenes = new Map<string, SceneState>();
const listeners = new Set<() => void>();
const timers = new Map<string, ReturnType<typeof setTimeout>>();
const saving = new Set<string>();
export const noteKey = (value: Pick<NoteInput, 'segment' | 'stage' | 'run'>) => `${value.segment}/${value.stage}/${value.run}`;
export const sceneNotesUrl = (project: string, episode: string, scene: string) => `${projectUrl(project)}/revision-notes/${episode}/${scene}`;
function state(url: string): SceneState {
  if (!scenes.has(url)) scenes.set(url, { notes: {}, drafts: {}, loaded: false, loading: false, error: '' });
  return scenes.get(url)!;
}
function publish(url: string, value: SceneState) {
  scenes.set(url, value);
  listeners.forEach(listener => listener());
}
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
export async function loadNotes(url: string) {
  const current = state(url);
  if (current.loaded || current.loading) return;
  publish(url, { ...current, loading: true, error: '' });
  try {
    const data = await get<{ notes: Record<string, RevisionNote> }>(url);
    publish(url, { ...state(url), notes: data.notes, loaded: true, loading: false });
  } catch (error) {
    publish(url, { ...state(url), loading: false, error: String(error) });
  }
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
export function useSceneNotes(project: string, episode: string, scene: string) {
  const url = sceneNotesUrl(project, episode, scene);
  const value = useSyncExternalStore(subscribe, () => state(url));
  useEffect(() => { void loadNotes(url); }, [url]);
  return { ...value, url };
}
