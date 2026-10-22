"""Asset CRUD and bounded original-image uploads, with existing same-origin access."""
from collections.abc import Callable
from contextlib import contextmanager
import sqlite3
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.services.assets import AssetError, AssetLibrary, MAX_IMAGE_BYTES


class Profile(BaseModel):
    model_config = ConfigDict(extra='forbid', str_max_length=20000)
    gender: str = ''
    age: str = ''
    identity: str = ''
    appearance: str = ''
    personality: str = ''
    description: str = ''


class CardInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['person', 'clothing', 'prop']
    name: str = Field(min_length=1, max_length=100)
    category: Literal['', '帽子', '服装', '鞋子', '配饰'] = ''
    profile: Profile = Field(default_factory=Profile)

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('请填写名称')
        return value

    @model_validator(mode='after')
    def category_matches(self):
        if (self.kind == 'clothing') != bool(self.category):
            raise ValueError('服装必须选择分类，人物与道具不使用服装分类')
        return self


class UpdateCard(CardInput):
    revision: int = Field(ge=1)


@contextmanager
def errors():
    try:
        yield
    except AssetError as error:
        raise HTTPException(error.status, str(error)) from error
    except (OSError, sqlite3.Error) as error:
        raise HTTPException(503, '资产读写失败，请检查磁盘空间和目录权限。') from error


def create_router(library: AssetLibrary, write_access: Callable):
    router = APIRouter(prefix='/api/assets', tags=['assets'])
    writes = [Depends(write_access)]

    @router.get('')
    def listing() -> list[dict]:
        with errors():
            return library.list()

    @router.post('', dependencies=writes)
    def create(data: CardInput) -> dict:
        with errors():
            return library.save(data.model_dump())

    @router.get('/{asset_id}')
    def detail(asset_id: str) -> dict:
        with errors():
            return library.read(asset_id)

    @router.put('/{asset_id}', dependencies=writes)
    def update(asset_id: str, data: UpdateCard) -> dict:
        with errors():
            return library.save(data.model_dump(exclude={'revision'}), asset_id, data.revision)

    @router.delete('/{asset_id}', dependencies=writes)
    def delete(asset_id: str, revision: Annotated[int, Query(ge=1)]) -> dict:
        with errors():
            library.delete(asset_id, revision)
            return {'ok': True}

    @router.post('/{asset_id}/images', dependencies=writes)
    def upload(asset_id: str, revision: Annotated[int, Form(ge=1)],
               slot: Annotated[Literal['portrait', 'views', 'album'], Form()],
               file: Annotated[UploadFile, File()]) -> dict:
        with errors():
            return library.upload(asset_id, revision, slot, file.filename or '图片', file.file.read(MAX_IMAGE_BYTES + 1))

    @router.get('/{asset_id}/images/{image_id}')
    def image(asset_id: str, image_id: str, download: bool = False) -> Response:
        with errors():
            value = library.image(asset_id, image_id)
            return Response(value['data'], media_type=value['mime'], headers={
                'X-Content-Type-Options': 'nosniff',
                'Content-Disposition': ('attachment' if download else 'inline') + "; filename*=UTF-8''" + quote(value['name'], safe=''),
            })

    @router.delete('/{asset_id}/images/{image_id}', dependencies=writes)
    def delete_image(asset_id: str, image_id: str, revision: Annotated[int, Query(ge=1)]) -> dict:
        with errors():
            return library.delete_image(asset_id, image_id, revision)

    return router
