"""User revision notes, kept separately from execution and approval records."""
from datetime import datetime
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


Episode = Annotated[str, Field(pattern=r'^EP[0-9]{3,}$')]
Scene = Annotated[str, Field(pattern=r'^C[0-9]{3,}$')]


class NoteInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    segment: Annotated[str, Field(pattern=r'^P[0-9]{3,}$')]
    stage: Literal['一采', '二采', '后处理']
    run: Annotated[str, Field(pattern=r'^R[0-9]{3,}$')]
    text: Annotated[str, Field(max_length=20000)]
    fileRevision: Annotated[str, Field(min_length=1, max_length=128)]


class RevisionNote(NoteInput):
    updatedAt: str


class OverallNote(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    number: Annotated[int, Field(ge=1)]
    text: Annotated[str, Field(max_length=20000)]
    updatedAt: str


class NoteChange(NoteInput):
    expectedText: Annotated[str, Field(max_length=20000)]


class OverallChange(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    number: Annotated[int, Field(ge=1)]
    text: Annotated[str, Field(max_length=20000)]
    expectedText: Annotated[str, Field(max_length=20000)]


class ExportChanges(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    notes: list[NoteChange]
    rounds: list[OverallChange]


class NotesChangedError(ValueError):
    pass


class SceneNotes(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    episode: Episode
    scene: Scene
    notes: dict[str, RevisionNote]
    rounds: dict[str, OverallNote] = Field(default_factory=dict)


class RevisionNotes:
    def __init__(self):
        self.lock = RLock()

    def path(self, project: Path, episode: str, scene: str) -> Path:
        # EP/C are validated by the HTTP boundary; also contain symlinked parents.
        directory = project / '09-剧集制作' / episode
        if not directory.is_dir():
            raise FileNotFoundError('剧集不存在')
        target = (directory / '其他资料' / '工作稿' / f'{episode}-{scene}-视频修改意见.json').resolve()
        if not target.is_relative_to(project.resolve()):
            raise ValueError('修改意见路径超出项目目录')
        return target

    def read(self, project: Path, episode: str, scene: str) -> SceneNotes:
        with self.lock:
            target = self.path(project, episode, scene)
            if not target.exists():
                return SceneNotes(episode=episode, scene=scene, notes={})
            data = SceneNotes.model_validate_json(target.read_text('utf-8'))
            if data.episode != episode or data.scene != scene or any(
                key != f'{note.segment}/{note.stage}/{note.run}' for key, note in data.notes.items()
            ) or any(key != str(note.number) for key, note in data.rounds.items()):
                raise ValueError('修改意见文件中的归属与入口不一致')
            return data

    def save(self, project: Path, episode: str, scene: str, value: NoteInput) -> RevisionNote:
        with self.lock:
            data = self.read(project, episode, scene)
            note = RevisionNote(**value.model_dump(), updatedAt=datetime.now().astimezone().isoformat(timespec='seconds'))
            data.notes[f'{value.segment}/{value.stage}/{value.run}'] = note
            self.write(project, episode, scene, data)
            return note

    def save_export(self, project: Path, episode: str, scene: str, changes: ExportChanges) -> SceneNotes:
        from backend.parsers.scene_rounds import rounds
        with self.lock:
            data = self.read(project, episode, scene)
            for value in changes.notes:
                old = data.notes.get(f'{value.segment}/{value.stage}/{value.run}')
                if (old.text if old else '') != value.expectedText:
                    raise NotesChangedError('分段意见已在其他位置更新，请保留当前输入，重新读取后核对。')
            for value in changes.rounds:
                rounds.referenced_round(project, f'{episode}-{scene}', value.number)
                old = data.rounds.get(str(value.number))
                if (old.text if old else '') != value.expectedText:
                    raise NotesChangedError('整场意见已在其他位置更新，请保留当前输入，重新读取后核对。')
            updated = datetime.now().astimezone().isoformat(timespec='seconds')
            for value in changes.notes:
                key = f'{value.segment}/{value.stage}/{value.run}'
                fields = value.model_dump(exclude={'expectedText'})
                if key in data.notes:
                    fields['fileRevision'] = data.notes[key].fileRevision
                data.notes[key] = RevisionNote(**fields, updatedAt=updated)
            for value in changes.rounds:
                data.rounds[str(value.number)] = OverallNote(number=value.number, text=value.text, updatedAt=updated)
            if changes.notes or changes.rounds:
                self.write(project, episode, scene, data)
            return data

    def write(self, project: Path, episode: str, scene: str, data: SceneNotes):
        target = self.path(project, episode, scene)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, prefix='.revision-notes-', suffix='.tmp', delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(json.dumps(data.model_dump(), ensure_ascii=False, indent=2) + '\n')
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
