"""Prompt routes keep file operations off the event loop."""
from contextlib import contextmanager
from collections.abc import Callable
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.services.prompts import MARKDOWN, PromptError, PromptLibrary


class SavePrompt(BaseModel):
    category: str = ''
    title: str
    body: str
    source: str | None = None
    revision: str | None = None


class CategoryInput(BaseModel):
    parent: str = ''
    name: str
    source: str = ''
    revision: str = ''


class ExistingInput(BaseModel):
    path: str
    revision: str


class RestoreInput(BaseModel):
    id: str
    revision: str
    category: str
    title: str


class TrashInput(BaseModel):
    id: str
    revision: str


class PreviewInput(BaseModel):
    body: str


@contextmanager
def errors():
    try:
        yield
    except PromptError as error:
        raise HTTPException(error.status, str(error)) from error
    except FileExistsError as error:
        raise HTTPException(409, '目标已存在，请更换名称或刷新列表。') from error
    except FileNotFoundError as error:
        raise HTTPException(409, '文件已被移动或删除，请刷新列表。') from error
    except (UnicodeError, ValueError) as error:
        raise HTTPException(422, '文件格式无效，请使用 UTF-8 编码的 Markdown 文件。') from error
    except OSError as error:
        raise HTTPException(503, '文件操作失败，请检查目录权限和磁盘状态。') from error


def create_router(library: PromptLibrary, write_access: Callable):
    router = APIRouter(prefix='/api/prompts', tags=['prompts'])
    writes = [Depends(write_access)]

    @router.get('')
    def snapshot() -> dict:
        with errors():
            return library.snapshot()

    @router.get('/document')
    def document(path: str) -> dict:
        with errors():
            return library.read(path)

    @router.get('/search')
    def search(q: str, category: str = '') -> list[dict]:
        with errors():
            return library.search(q, category)

    @router.post('/document', dependencies=writes)
    def save(data: SavePrompt) -> dict:
        with errors():
            return library.save(data.category, data.title, data.body, data.source, data.revision)

    @router.post('/categories', dependencies=writes)
    def create_category(data: CategoryInput) -> dict:
        with errors():
            return library.create_category(data.parent, data.name)

    @router.put('/categories', dependencies=writes)
    def update_category(data: CategoryInput) -> dict:
        with errors():
            return library.update_category(data.source, data.parent, data.name, data.revision)

    @router.delete('/categories', dependencies=writes)
    def delete_category(data: ExistingInput) -> dict:
        with errors():
            library.delete_category(data.path, data.revision)
            return {'ok': True}

    @router.delete('/document', dependencies=writes)
    def discard(data: ExistingInput) -> dict:
        with errors():
            return library.discard(data.path, data.revision)

    @router.post('/preview', dependencies=writes)
    def preview(data: PreviewInput) -> dict:
        return {'html': MARKDOWN.render(data.body)}

    @router.get('/trash')
    def trash() -> list[dict]:
        with errors():
            return library.trash_list()

    @router.get('/trash/document')
    def trash_document(id: str) -> dict:
        with errors():
            return library.trash_read(id)

    @router.post('/trash/restore', dependencies=writes)
    def restore(data: RestoreInput) -> dict:
        with errors():
            return library.restore(data.id, data.category, data.title, data.revision)

    @router.delete('/trash', dependencies=writes)
    def purge(data: TrashInput) -> dict:
        with errors():
            library.purge(data.id, data.revision)
            return {'ok': True}

    return router
