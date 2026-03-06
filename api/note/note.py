"""
笔记功能API
提供笔记的增删改查功能
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List

from fastapi import APIRouter, HTTPException, status, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import get_user_storage_dir

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/note", tags=["note"])


class NoteAddRequest(BaseModel):
    uuid: str
    title: Optional[str] = None


class NoteUpdateRequest(BaseModel):
    uuid: str
    content: str
    title: Optional[str] = None


class NoteDeleteRequest(BaseModel):
    uuid: str


class NoteQueryRequest(BaseModel):
    num: int = 10


def get_note_dir(user_uuid: str) -> Path:
    """获取用户的笔记目录"""
    user_dir = get_user_storage_dir(user_uuid)
    note_dir = user_dir / ".note"
    note_dir.mkdir(exist_ok=True)
    return note_dir


def get_index_path(user_uuid: str) -> Path:
    """获取索引文件路径"""
    return get_note_dir(user_uuid) / "index.json"


def load_index(user_uuid: str) -> Dict:
    """加载索引文件"""
    index_path = get_index_path(user_uuid)
    if index_path.exists():
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载索引失败: {e}")
    return {"notes": []}


def save_index(user_uuid: str, index: Dict) -> None:
    """保存索引文件"""
    index_path = get_index_path(user_uuid)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def update_index_add(user_uuid: str, note_uuid: str, title: str) -> None:
    """更新索引，添加新笔记"""
    index = load_index(user_uuid)
    now = datetime.now().isoformat()
    index["notes"].append({
        "uuid": note_uuid,
        "title": title,
        "updated_at": now
    })
    save_index(user_uuid, index)


def update_index_remove(user_uuid: str, note_uuid: str) -> None:
    """更新索引，删除笔记"""
    index = load_index(user_uuid)
    index["notes"] = [n for n in index["notes"] if n["uuid"] != note_uuid]
    save_index(user_uuid, index)


def update_index_update(user_uuid: str, note_uuid: str, title: Optional[str] = None) -> None:
    """更新索引，更新笔记信息"""
    index = load_index(user_uuid)
    for note in index["notes"]:
        if note["uuid"] == note_uuid:
            if title is not None:
                note["title"] = title
            note["updated_at"] = datetime.now().isoformat()
            break
    save_index(user_uuid, index)


@router.post("/add")
async def add_note(
    request: Request,
    body: NoteAddRequest
) -> JSONResponse:
    """添加笔记
    
    Args:
        request: FastAPI请求对象
        body: 请求体
    
    Returns:
        JSONResponse: 添加结果
    """
    uuid = body.uuid
    title = body.title
    user_uuid = getattr(request.state, 'user_uuid', None)
    if not user_uuid:
        raise HTTPException(status_code=401, detail="User authentication missing")
    
    if not uuid:
        raise HTTPException(status_code=400, detail="UUID is required")
    
    note_dir = get_note_dir(user_uuid)
    title = title or "无标题"
    now = datetime.now().isoformat()
    
    meta = {
        "uuid": uuid,
        "title": title,
        "created_at": now,
        "updated_at": now
    }
    
    content = {
        "uuid": uuid,
        "content": ""
    }
    
    meta_path = note_dir / f"{uuid}_meta.json"
    content_path = note_dir / f"{uuid}_content.json"
    
    if meta_path.exists() or content_path.exists():
        raise HTTPException(status_code=400, detail="Note already exists")
    
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    
    with open(content_path, "w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False, indent=2)
    
    update_index_add(user_uuid, uuid, title)
    
    logger.info(f"添加笔记: user={user_uuid}, uuid={uuid}, title={title}")
    
    return JSONResponse(status_code=200, content={
        "success": True,
        "uuid": uuid,
        "message": "Note added successfully"
    })


@router.post("/update")
async def update_note(
    request: Request,
    body: NoteUpdateRequest
) -> JSONResponse:
    """更新笔记
    
    Args:
        request: FastAPI请求对象
        body: 请求体
    
    Returns:
        JSONResponse: 更新结果
    """
    uuid = body.uuid
    content = body.content
    title = body.title
    user_uuid = getattr(request.state, 'user_uuid', None)
    if not user_uuid:
        raise HTTPException(status_code=401, detail="User authentication missing")
    
    if not uuid:
        raise HTTPException(status_code=400, detail="UUID is required")
    
    note_dir = get_note_dir(user_uuid)
    meta_path = note_dir / f"{uuid}_meta.json"
    content_path = note_dir / f"{uuid}_content.json"
    
    if not meta_path.exists() or not content_path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    
    now = datetime.now().isoformat()
    
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    
    meta["updated_at"] = now
    if title is not None:
        meta["title"] = title
    
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    
    content_data = {
        "uuid": uuid,
        "content": content
    }
    
    with open(content_path, "w", encoding="utf-8") as f:
        json.dump(content_data, f, ensure_ascii=False, indent=2)
    
    update_index_update(user_uuid, uuid, title)
    
    logger.info(f"更新笔记: user={user_uuid}, uuid={uuid}")
    
    return JSONResponse(status_code=200, content={
        "success": True,
        "uuid": uuid,
        "message": "Note updated successfully"
    })


@router.post("/delete")
async def delete_note(
    request: Request,
    body: NoteDeleteRequest
) -> JSONResponse:
    """删除笔记
    
    Args:
        request: FastAPI请求对象
        body: 请求体
    
    Returns:
        JSONResponse: 删除结果
    """
    uuid = body.uuid
    user_uuid = getattr(request.state, 'user_uuid', None)
    if not user_uuid:
        raise HTTPException(status_code=401, detail="User authentication missing")
    
    if not uuid:
        raise HTTPException(status_code=400, detail="UUID is required")
    
    note_dir = get_note_dir(user_uuid)
    meta_path = note_dir / f"{uuid}_meta.json"
    content_path = note_dir / f"{uuid}_content.json"
    
    if not meta_path.exists() and not content_path.exists():
        raise HTTPException(status_code=404, detail="Note not found")
    
    if meta_path.exists():
        meta_path.unlink()
    
    if content_path.exists():
        content_path.unlink()
    
    update_index_remove(user_uuid, uuid)
    
    logger.info(f"删除笔记: user={user_uuid}, uuid={uuid}")
    
    return JSONResponse(status_code=200, content={
        "success": True,
        "uuid": uuid,
        "message": "Note deleted successfully"
    })


@router.post("/query")
async def query_notes(
    request: Request,
    body: NoteQueryRequest
) -> JSONResponse:
    """查询笔记
    
    返回最新的num篇笔记（包含元数据和内容）
    
    Args:
        request: FastAPI请求对象
        body: 请求体
    
    Returns:
        JSONResponse: 笔记列表
    """
    num = body.num
    user_uuid = getattr(request.state, 'user_uuid', None)
    if not user_uuid:
        raise HTTPException(status_code=401, detail="User authentication missing")
    
    if num <= 0:
        num = 10
    
    index = load_index(user_uuid)
    notes = index.get("notes", [])
    
    notes.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    notes = notes[:num]
    
    note_dir = get_note_dir(user_uuid)
    result = []
    
    for note_meta in notes:
        note_uuid = note_meta.get("uuid")
        
        meta_path = note_dir / f"{note_uuid}_meta.json"
        content_path = note_dir / f"{note_uuid}_content.json"
        
        meta = {}
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        
        content_data = {"content": ""}
        if content_path.exists():
            with open(content_path, "r", encoding="utf-8") as f:
                content_data = json.load(f)
        
        result.append({
            "uuid": note_uuid,
            "title": meta.get("title", "无标题"),
            "created_at": meta.get("created_at", ""),
            "updated_at": meta.get("updated_at", ""),
            "content": content_data.get("content", "")
        })
    
    logger.info(f"查询笔记: user={user_uuid}, num={num}, found={len(result)}")
    
    return JSONResponse(status_code=200, content={
        "success": True,
        "total": len(result),
        "notes": result
    })
