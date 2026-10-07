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


class SceneNotes(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    episode: Episode
    scene: Scene
    notes: dict[str, RevisionNote]


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
            ):
                raise ValueError('修改意见文件中的归属与入口不一致')
            return data

    def save(self, project: Path, episode: str, scene: str, value: NoteInput) -> RevisionNote:
        with self.lock:
            data = self.read(project, episode, scene)
            note = RevisionNote(**value.model_dump(), updatedAt=datetime.now().astimezone().isoformat(timespec='seconds'))
            data.notes[f'{value.segment}/{value.stage}/{value.run}'] = note
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
            return note
