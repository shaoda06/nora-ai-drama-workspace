"""Episode-round feedback is saved together; legacy scene files stay at their paths."""
from datetime import datetime
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from backend.parsers.scene_rounds import load_episode_rounds, rounds
from backend.services.revision_notes import (
    Episode, Scene, NoteChange, RevisionNote, OverallChange, OverallNote,
    SceneNotes, RevisionNotes, ExportChanges, NotesChangedError,
)


class CombinationInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    scenes: Annotated[dict[Scene, Annotated[int, Field(ge=1)]], Field(min_length=1)]
    text: Annotated[str, Field(max_length=20000)]

    def key(self) -> str:
        return '|'.join(f'{scene}:{self.scenes[scene]}' for scene in sorted(self.scenes, key=lambda value: int(value[1:])))


class CombinationNote(CombinationInput):
    updatedAt: str


class CombinationChange(CombinationInput):
    expectedText: Annotated[str, Field(max_length=20000)]


class EpisodeNotesFile(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    episode: Episode
    notes: dict[Scene, dict[str, RevisionNote]] = Field(default_factory=dict)
    rounds: dict[str, OverallNote] = Field(default_factory=dict)
    combinations: dict[str, CombinationNote] = Field(default_factory=dict)


class EpisodeNotes(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    episode: Episode
    scenes: dict[Scene, SceneNotes] = Field(default_factory=dict)
    rounds: dict[str, OverallNote] = Field(default_factory=dict)
    combinations: dict[str, CombinationNote] = Field(default_factory=dict)


class SceneNoteChange(NoteChange):
    scene: Scene


class EpisodeExportChanges(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    notes: list[SceneNoteChange]
    rounds: list[OverallChange]
    combination: CombinationChange | None = None


class EpisodeRevisionNotes:
    def __init__(self, notes: RevisionNotes):
        self.notes = notes

    def path(self, project: Path, episode: str) -> Path:
        directory = project / '09-剧集制作' / episode
        if not directory.is_dir():
            raise FileNotFoundError('剧集不存在')
        target = (directory / '其他资料/工作稿' / f'{episode}-视频修改意见.json').resolve()
        if not target.is_relative_to(project.resolve()):
            raise ValueError('修改意见路径超出项目目录')
        return target

    def registered(self, project: Path, episode: str) -> set[int]:
        def read(key):
            path = project / key
            return path.read_text('utf-8-sig') if path.exists() else None
        return {item['number'] for item in load_episode_rounds(episode, read)}

    def read_file(self, project: Path, episode: str) -> EpisodeNotesFile:
        target = self.path(project, episode)
        data = EpisodeNotesFile.model_validate_json(target.read_text('utf-8')) if target.exists() else EpisodeNotesFile(episode=episode)
        if data.episode != episode or any(key != str(item.number) for key, item in data.rounds.items()) or any(
            key != note.key() for notes in data.notes.values() for key, note in notes.items()
        ) or any(key != note.key() for key, note in data.combinations.items()):
            raise ValueError('整集修改意见文件中的归属与入口不一致')
        return data

    def read_scene(self, project: Path, episode: str, scene: str) -> SceneNotes:
        with self.notes.lock:
            saved = self.read_file(project, episode)
            result = self.notes.read(project, episode, scene)
            result.notes.update(saved.notes.get(scene, {}))
            return result

    def read(self, project: Path, episode: str) -> EpisodeNotes:
        with self.notes.lock:
            saved = self.read_file(project, episode)
            scenes = set(saved.notes)
            for path in self.path(project, episode).parent.glob(f'{episode}-C*-视频修改意见.json'):
                scene = path.name[len(episode) + 1:].split('-')[0]
                if re.fullmatch(r'C[0-9]{3,}', scene):
                    scenes.add(scene)
            merged = {}
            for scene in sorted(scenes):
                value = self.notes.read(project, episode, scene)
                value.notes.update(saved.notes.get(scene, {}))
                merged[scene] = value
            return EpisodeNotes(episode=episode, rounds=saved.rounds, scenes=merged, combinations=saved.combinations)

    def save_note(self, project: Path, episode: str, scene: str, value: NoteChange) -> RevisionNote:
        with self.notes.lock:
            if value.roundNumber not in self.registered(project, episode):
                return self.notes.save(project, episode, scene, value)
            rounds.referenced_round(project, f'{episode}-{scene}', value.roundNumber)
            saved = self.read_file(project, episode)
            old = self.read_scene(project, episode, scene).notes.get(value.key())
            if (old.text if old else '') != value.expectedText:
                raise NotesChangedError('分段意见已在其他页面更新，请保留本页文字，核对最新意见后再保存。')
            note = RevisionNote(**value.model_dump(exclude={'expectedText'}), updatedAt=datetime.now().astimezone().isoformat(timespec='seconds'))
            saved.notes.setdefault(scene, {})[value.key()] = note
            self.write(project, episode, saved)
            return note

    def save(self, project: Path, episode: str, changes: EpisodeExportChanges) -> EpisodeNotes:
        with self.notes.lock:
            saved = self.read_file(project, episode)
            data = self.read(project, episode)
            registered = self.registered(project, episode)
            # Validate every original, then replace one episode file for all edits.
            for value in changes.notes:
                if value.roundNumber not in registered:
                    raise ValueError('场次历史意见在本场编辑区修改；整集导出只整理真实整集轮次的意见')
                rounds.referenced_round(project, f'{episode}-{value.scene}', value.roundNumber)
                old = data.scenes.get(value.scene)
                note = old.notes.get(value.key()) if old else None
                if (note.text if note else '') != value.expectedText:
                    raise NotesChangedError(f'{value.scene}分段意见已在其他位置更新，请保留当前输入，重新读取后核对。')
            for value in changes.rounds:
                if value.number not in registered:
                    raise ValueError('本轮汇总意见必须关联已登记的整集修改轮次')
                old = saved.rounds.get(str(value.number))
                if (old.text if old else '') != value.expectedText:
                    raise NotesChangedError('本轮汇总意见已在其他位置更新，请保留当前输入，重新读取后核对。')
            combination = changes.combination
            if combination is not None:
                for scene, number in combination.scenes.items():
                    rounds.referenced_round(project, f'{episode}-{scene}', number)
                old = saved.combinations.get(combination.key())
                if (old.text if old else '') != combination.expectedText:
                    raise NotesChangedError('本轮汇总意见已在其他位置更新，请保留当前输入，重新读取后核对。')
            updated = datetime.now().astimezone().isoformat(timespec='seconds')
            for value in changes.notes:
                old = data.scenes.get(value.scene)
                note = old.notes.get(value.key()) if old else None
                fields = value.model_dump(exclude={'scene', 'expectedText'})
                if note:
                    fields['fileRevision'] = note.fileRevision
                saved.notes.setdefault(value.scene, {})[value.key()] = RevisionNote(**fields, updatedAt=updated)
            for value in changes.rounds:
                saved.rounds[str(value.number)] = OverallNote(number=value.number, text=value.text, updatedAt=updated)
            if combination is not None:
                saved.combinations[combination.key()] = CombinationNote(scenes=combination.scenes, text=combination.text, updatedAt=updated)
            if changes.notes or changes.rounds or combination is not None:
                self.write(project, episode, saved)
            return self.read(project, episode)

    def save_scene_export(self, project: Path, episode: str, scene: str, changes: ExportChanges) -> SceneNotes:
        with self.notes.lock:
            registered = self.registered(project, episode)
            if any(item.number in registered for item in changes.rounds):
                raise ValueError('整集轮次只填写一份本轮汇总意见，请在对应整集的意见导出中整理')
            if any(item.roundNumber in registered for item in changes.notes):
                if changes.rounds or any(item.roundNumber not in registered for item in changes.notes):
                    raise ValueError('请分别保存整集轮次意见与场次历史意见，不将两种文件混为一次保存')
                self.save(project, episode, EpisodeExportChanges(
                    notes=[SceneNoteChange(scene=scene, **item.model_dump()) for item in changes.notes], rounds=[]))
                return self.read_scene(project, episode, scene)
            return self.notes.save_export(project, episode, scene, changes)

    def write(self, project: Path, episode: str, data: EpisodeNotesFile):
        target = self.path(project, episode)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, prefix='.episode-revision-notes-', suffix='.tmp', delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(json.dumps(data.model_dump(), ensure_ascii=False, indent=2) + '\n')
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
