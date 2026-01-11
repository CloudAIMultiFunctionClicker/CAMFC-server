"""
Copyright (C) 2026 Jiale Xu (许嘉乐) (ANTmmmmm) <https://github.com/ant-cave>
Email: ANTmmmmm@outlook.com, ANTmmmmm@126.com, 1504596931@qq.com

Copyright (C) 2026 Xinhang Chen (陈欣航) <https://github.com/cxh09>
Email: abc.cxh2009@foxmail.com

Copyright (C) 2026 Zimo Wen (温子墨) <https://github.com/lusamaqq>
Email: 1220594170@qq.com

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

文件管理模块
提供文件列表、文件信息、目录浏览等API
"""

import logging
import mimetypes
import hashlib
import shutil
import zipfile
import io
import os
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Query, Body
from fastapi.responses import JSONResponse, StreamingResponse

from config import STORAGE_DIR, UPLOAD_DIR

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/files", tags=["files"])


def get_file_info(file_path: Path) -> Dict:
    """获取文件的详细信息
    
    Args:
        file_path: 文件路径
        
    Returns:
        Dict: 文件信息字典
    """
    stat = file_path.stat()
    
    # 计算文件哈希（SHA256）作为唯一ID
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        file_hash = sha256_hash.hexdigest()
    except Exception as e:
        logger.warning(f"计算文件哈希失败: {file_path}, error={e}")
        file_hash = None
    
    # 猜测MIME类型
    mime_type, encoding = mimetypes.guess_type(file_path.name)
    
    return {
        "name": file_path.name,
        "path": str(file_path.relative_to(STORAGE_DIR)),
        "size": stat.st_size,
        "sha256": file_hash,
        "mime_type": mime_type or "application/octet-stream",
        "encoding": encoding,
        "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "accessed_at": datetime.fromtimestamp(stat.st_atime).isoformat(),
        "is_file": True,
        "is_dir": False,
    }


def get_directory_info(dir_path: Path) -> Dict:
    """获取目录信息
    
    Args:
        dir_path: 目录路径
        
    Returns:
        Dict: 目录信息字典
    """
    try:
        # 获取目录下的所有条目
        entries = []
        total_size = 0
        file_count = 0
        dir_count = 0
        
        for entry in dir_path.iterdir():
            if entry.is_file():
                entries.append(get_file_info(entry))
                total_size += entry.stat().st_size
                file_count += 1
            elif entry.is_dir():
                dir_stat = entry.stat()
                entries.append({
                    "name": entry.name,
                    "path": str(entry.relative_to(STORAGE_DIR)),
                    "size": 0,  # 目录大小需要递归计算，这里简单设为0
                    "sha256": None,
                    "mime_type": "inode/directory",
                    "encoding": None,
                    "created_at": datetime.fromtimestamp(dir_stat.st_ctime).isoformat(),
                    "modified_at": datetime.fromtimestamp(dir_stat.st_mtime).isoformat(),
                    "accessed_at": datetime.fromtimestamp(dir_stat.st_atime).isoformat(),
                    "is_file": False,
                    "is_dir": True,
                })
                dir_count += 1
        
        # 按名称排序
        entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        
        dir_stat = dir_path.stat()
        return {
            "path": str(dir_path.relative_to(STORAGE_DIR)),
            "name": dir_path.name,
            "is_root": dir_path == STORAGE_DIR,
            "total_entries": len(entries),
            "file_count": file_count,
            "dir_count": dir_count,
            "total_size": total_size,
            "created_at": datetime.fromtimestamp(dir_stat.st_ctime).isoformat(),
            "modified_at": datetime.fromtimestamp(dir_stat.st_mtime).isoformat(),
            "entries": entries,
        }
        
    except PermissionError as e:
        logger.error(f"权限错误访问目录: {dir_path}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {dir_path}"
        )
    except Exception as e:
        logger.error(f"访问目录失败: {dir_path}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to access directory: {str(e)}"
        )


@router.get("/")
async def list_files(
    path: Optional[str] = Query(None, description="相对路径，为空时列出根目录"),
    recursive: bool = Query(False, description="是否递归列出所有文件"),
    page: int = Query(1, ge=1, description="页码，从1开始"),
    limit: int = Query(100, ge=1, le=100, description="每页数量，最大100"),
) -> JSONResponse:
    """列出文件/目录
    
    列出指定目录下的文件和子目录
    默认列出根目录（storage目录）
    支持分页，每页最多100个文件
    
    Args:
        path: 相对路径（相对于storage目录）
        recursive: 是否递归列出
        page: 页码，从1开始
        limit: 每页数量，最大100
        
    Returns:
        JSONResponse: 目录信息
    """
    try:
        # 确定目标目录
        if path:
            target_path = (STORAGE_DIR / path).resolve()
            # 安全检查：确保目标路径在STORAGE_DIR内
            if not str(target_path).startswith(str(STORAGE_DIR.resolve())):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Path traversal is not allowed"
                )
        else:
            target_path = STORAGE_DIR
        
        # 检查路径是否存在
        if not target_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Directory not found"
            )
        
        # 检查是否是目录
        if not target_path.is_dir():
            # 如果是文件，返回文件信息
            file_info = get_file_info(target_path)
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "is_file": True,
                    "is_dir": False,
                    "file": file_info,
                    "message": "This is a file, not a directory"
                }
            )
        
        if recursive:
            # 递归列出所有文件（简化版本）
            all_files = []
            total_size = 0
            file_count = 0
            
            for file_path in target_path.rglob("*"):
                if file_path.is_file():
                    file_info = get_file_info(file_path)
                    all_files.append(file_info)
                    total_size += file_path.stat().st_size
                    file_count += 1
            
            # 按路径排序
            all_files.sort(key=lambda x: x["path"])
            
            # 分页处理
            total_pages = (file_count + limit - 1) // limit  # 向上取整
            start_idx = (page - 1) * limit
            end_idx = start_idx + limit
            paged_files = all_files[start_idx:end_idx]
            
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "path": str(target_path.relative_to(STORAGE_DIR)),
                    "recursive": True,
                    "total_files": file_count,
                    "total_size": total_size,
                    "page": page,
                    "limit": limit,
                    "total_pages": total_pages,
                    "has_next": page < total_pages,
                    "has_prev": page > 1,
                    "files": paged_files,
                }
            )
        else:
            # 非递归，列出目录内容
            dir_info = get_directory_info(target_path)
            
            # 分页处理（对目录条目进行分页）
            all_entries = dir_info.get("entries", [])
            total_entries = len(all_entries)
            total_pages = (total_entries + limit - 1) // limit  # 向上取整
            start_idx = (page - 1) * limit
            end_idx = start_idx + limit
            paged_entries = all_entries[start_idx:end_idx]
            
            # 更新返回信息，包含分页数据
            dir_info.update({
                "page": page,
                "limit": limit,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
                "entries": paged_entries,
            })
            
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=dir_info
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"列出文件失败: path={path}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list files: {str(e)}"
        )


@router.get("/info/{file_id_or_path}")
async def get_file_info_by_id(
    file_id_or_path: str,
    include_content_hash: bool = Query(True, description="是否包含文件内容哈希（计算较慢）"),
) -> JSONResponse:
    """获取文件详细信息
    
    通过文件ID（SHA256）或路径获取文件详细信息
    
    Args:
        file_id_or_path: 文件ID（SHA256）或相对路径
        include_content_hash: 是否计算文件哈希
        
    Returns:
        JSONResponse: 文件详细信息
    """
    try:
        # 首先尝试作为路径处理
        file_path = (STORAGE_DIR / file_id_or_path).resolve()
        
        # 安全检查：确保路径在STORAGE_DIR内
        if not str(file_path).startswith(str(STORAGE_DIR.resolve())):
            # 如果不是有效路径，尝试作为文件ID查找
            file_path = None
            for potential_file in STORAGE_DIR.rglob("*"):
                if potential_file.is_file():
                    # 计算或比较文件哈希
                    if include_content_hash:
                        sha256_hash = hashlib.sha256()
                        with open(potential_file, "rb") as f:
                            for chunk in iter(lambda: f.read(4096), b""):
                                sha256_hash.update(chunk)
                        file_hash = sha256_hash.hexdigest()
                        if file_hash == file_id_or_path:
                            file_path = potential_file
                            break
                    else:
                        # 简单比较文件名（不准确，但快速）
                        if potential_file.name == file_id_or_path:
                            file_path = potential_file
                            break
        
        if not file_path or not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found"
            )
        
        if not file_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Path is not a file"
            )
        
        # 获取文件信息
        file_info = get_file_info(file_path)
        
        # 如果不要求计算哈希，移除哈希字段以加快响应
        if not include_content_hash:
            file_info["sha256"] = None
        
        logger.info(f"获取文件信息: {file_path.name}, size={file_info['size']}")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=file_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文件信息失败: id={file_id_or_path}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get file info: {str(e)}"
        )


@router.get("/stats")
async def get_storage_stats() -> JSONResponse:
    """获取存储统计信息
    
    返回存储目录的整体统计信息
    
    Returns:
        JSONResponse: 存储统计信息
    """
    try:
        total_size = 0
        total_files = 0
        total_dirs = 0
        
        # 遍历storage目录计算统计
        for entry in STORAGE_DIR.rglob("*"):
            if entry.is_file():
                total_size += entry.stat().st_size
                total_files += 1
            elif entry.is_dir():
                total_dirs += 1
        
        # 计算根目录统计（排除根目录自身）
        total_dirs = max(0, total_dirs - 1)  # 减去根目录自身
        
        # 获取存储目录信息
        storage_stat = STORAGE_DIR.stat()
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "storage_path": str(STORAGE_DIR),
                "total_size_bytes": total_size,
                "total_size_human": _human_readable_size(total_size),
                "total_files": total_files,
                "total_directories": total_dirs,
                "created_at": datetime.fromtimestamp(storage_stat.st_ctime).isoformat(),
                "available_space": _get_available_space(STORAGE_DIR),
                "message": "Storage statistics",
            }
        )
        
    except Exception as e:
        logger.error(f"获取存储统计失败: error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get storage stats: {str(e)}"
        )


def _human_readable_size(size_bytes: int) -> str:
    """将字节数转换为人类可读的格式"""
    if size_bytes == 0:
        return "0 B"
    
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    
    while size_bytes >= 1024 and unit_index < len(units) - 1:
        size_bytes = size_bytes // 1024
        unit_index += 1
    
    return f"{size_bytes:.2f} {units[unit_index]}"


def _get_available_space(path: Path) -> Dict:
    """获取可用磁盘空间信息"""
    try:
        import shutil
        total, used, free = shutil.disk_usage(path)
        
        return {
            "total_bytes": total,
            "total_human": _human_readable_size(total),
            "used_bytes": used,
            "used_human": _human_readable_size(used),
            "free_bytes": free,
            "free_human": _human_readable_size(free),
            "usage_percent": round((used / total) * 100, 2) if total > 0 else 0,
        }
    except Exception as e:
        logger.warning(f"获取磁盘空间信息失败: error={e}")
        return {
            "total_bytes": 0,
            "total_human": "Unknown",
            "used_bytes": 0,
            "used_human": "Unknown",
            "free_bytes": 0,
            "free_human": "Unknown",
            "usage_percent": 0,
        }


# v2: 添加文件搜索功能（按名称、类型、大小等）
# v3: 添加文件元数据管理（标签、描述等）
# 辅助函数：安全检查
def _validate_path(user_path: str) -> Path:
    """验证路径是否在STORAGE_DIR内
    
    Args:
        user_path: 用户提供的路径
        
    Returns:
        Path: 解析后的安全路径
        
    Raises:
        HTTPException: 如果路径不安全或不存在
    """
    if not user_path or user_path == ".":
        target_path = STORAGE_DIR
    else:
        target_path = (STORAGE_DIR / user_path).resolve()
    
    # 安全检查：确保路径在STORAGE_DIR内
    if not str(target_path).startswith(str(STORAGE_DIR.resolve())):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path traversal is not allowed"
        )
    
    # 检查路径是否存在
    if not target_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Path not found"
        )
    
    return target_path


def _is_safe_operation(source: Path, destination: Path) -> bool:
    """检查文件操作是否安全（目标不在源内，防止循环）
    
    Args:
        source: 源路径
        destination: 目标路径
        
    Returns:
        bool: 是否安全
    """
    try:
        # 检查目标是否在源目录内（防止循环复制/移动）
        return not str(destination).startswith(str(source))
    except Exception:
        return False


# 回收站相关
TRASH_DIR = STORAGE_DIR / ".trash"

def _ensure_trash_dir():
    """确保回收站目录存在"""
    if not TRASH_DIR.exists():
        TRASH_DIR.mkdir(parents=True, exist_ok=True)


# 删除文件/目录
@router.delete("/{path:path}")
async def delete_file_or_directory(
    path: str,
    permanent: bool = Query(False, description="是否永久删除（不走回收站）"),
) -> JSONResponse:
    """删除文件或目录
    
    默认移动到回收站（.trash目录），可指定永久删除
    对于目录会递归删除所有内容
    
    Args:
        path: 要删除的文件/目录路径（相对于storage目录）
        permanent: 是否永久删除
        
    Returns:
        JSONResponse: 操作结果
    """
    try:
        # 验证路径
        target_path = _validate_path(path)
        
        # 如果是根目录，不允许删除
        if target_path == STORAGE_DIR:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete root storage directory"
            )
        
        # 如果是.trash目录，特殊处理
        if target_path == TRASH_DIR:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete trash directory directly"
            )
        
        # 获取路径信息用于返回
        is_dir = target_path.is_dir()
        item_name = target_path.name
        item_path = str(target_path.relative_to(STORAGE_DIR))
        
        if permanent:
            # 永久删除
            if is_dir:
                shutil.rmtree(target_path)
                operation = "permanently deleted directory"
            else:
                target_path.unlink()
                operation = "permanently deleted file"
            logger.warning(f"永久删除: {item_path}")
        else:
            # 移动到回收站
            _ensure_trash_dir()
            
            # 生成唯一的回收站路径（避免文件名冲突）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            trash_item_name = f"{timestamp}_{item_name}"
            trash_path = TRASH_DIR / trash_item_name
            
            # 移动文件/目录到回收站
            if is_dir:
                shutil.move(str(target_path), str(trash_path))
            else:
                shutil.move(str(target_path), str(trash_path))
            
            operation = "moved to trash"
            logger.info(f"移动到回收站: {item_path} -> {trash_item_name}")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "success": True,
                "path": item_path,
                "name": item_name,
                "is_directory": is_dir,
                "operation": operation,
                "permanent": permanent,
                "message": f"{'Directory' if is_dir else 'File'} {operation} successfully"
            }
        )
        
    except HTTPException:
        raise
    except PermissionError as e:
        logger.error(f"权限错误删除: {path}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {str(e)}"
        )
    except Exception as e:
        logger.error(f"删除失败: {path}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete: {str(e)}"
        )


# 重命名文件/目录
@router.patch("/rename")
async def rename_file_or_directory(
    source_path: str = Query(..., description="原路径（相对于storage目录）"),
    new_name: str = Query(..., description="新名称（不含路径）"),
) -> JSONResponse:
    """重命名文件或目录（原子操作）
    
    重命名操作是原子的，要么成功要么失败，不会处于中间状态
    新名称不能包含路径分隔符
    
    Args:
        source_path: 原路径
        new_name: 新名称
        
    Returns:
        JSONResponse: 操作结果
    """
    try:
        # 验证原路径
        source = _validate_path(source_path)
        
        # 检查新名称是否合法
        if not new_name or not new_name.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New name cannot be empty"
            )
        
        if "/" in new_name or "\\" in new_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New name cannot contain path separators"
            )
        
        if new_name in [".", ".."]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New name cannot be '.' or '..'"
            )
        
        # 构造新路径
        new_path = source.parent / new_name
        
        # 检查目标是否已存在
        if new_path.exists():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A file or directory with the new name already exists"
            )
        
        # 执行重命名（原子操作）
        source.rename(new_path)
        
        logger.info(f"重命名: {source_path} -> {new_name}")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "success": True,
                "old_path": str(source.relative_to(STORAGE_DIR)),
                "old_name": source.name,
                "new_path": str(new_path.relative_to(STORAGE_DIR)),
                "new_name": new_name,
                "is_directory": source.is_dir(),
                "message": f"{'Directory' if source.is_dir() else 'File'} renamed successfully"
            }
        )
        
    except HTTPException:
        raise
    except PermissionError as e:
        logger.error(f"权限错误重命名: {source_path}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {str(e)}"
        )
    except Exception as e:
        logger.error(f"重命名失败: {source_path}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to rename: {str(e)}"
        )


# 移动文件/目录
@router.patch("/move")
async def move_file_or_directory(
    source_path: str = Query(..., description="原路径（相对于storage目录）"),
    dest_path: str = Query(..., description="目标目录路径（相对于storage目录）"),
) -> JSONResponse:
    """移动文件或目录到新位置（原子操作）
    
    移动操作是原子的，会保持完整的目录结构
    不能移动到自身内部（防止循环）
    
    Args:
        source_path: 原路径
        dest_path: 目标目录路径
        
    Returns:
        JSONResponse: 操作结果
    """
    try:
        # 验证原路径
        source = _validate_path(source_path)
        
        # 验证目标路径
        dest = _validate_path(dest_path)
        
        # 检查目标是否是目录
        if not dest.is_dir():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Destination must be a directory"
            )
        
        # 安全检查：防止移动到自身内部
        if not _is_safe_operation(source, dest / source.name):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot move directory into itself or its subdirectories"
            )
        
        # 检查目标位置是否已存在同名文件/目录
        new_location = dest / source.name
        if new_location.exists():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A file or directory with the same name already exists in the destination"
            )
        
        # 执行移动（原子操作）
        shutil.move(str(source), str(dest))
        
        logger.info(f"移动: {source_path} -> {dest_path}")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "success": True,
                "old_path": str(source.relative_to(STORAGE_DIR)),
                "new_path": str(new_location.relative_to(STORAGE_DIR)),
                "is_directory": source.is_dir(),
                "message": f"{'Directory' if source.is_dir() else 'File'} moved successfully"
            }
        )
        
    except HTTPException:
        raise
    except PermissionError as e:
        logger.error(f"权限错误移动: {source_path} -> {dest_path}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {str(e)}"
        )
    except Exception as e:
        logger.error(f"移动失败: {source_path} -> {dest_path}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to move: {str(e)}"
        )


# 复制文件/目录
@router.post("/copy")
async def copy_file_or_directory(
    source_path: str = Query(..., description="原路径（相对于storage目录）"),
    dest_path: str = Query(..., description="目标目录路径（相对于storage目录）"),
    overwrite: bool = Query(False, description="是否覆盖已存在的文件"),
) -> JSONResponse:
    """复制文件或目录
    
    支持文件和目录的递归复制
    可以选择是否覆盖目标位置已存在的文件
    
    Args:
        source_path: 原路径
        dest_path: 目标目录路径
        overwrite: 是否覆盖
        
    Returns:
        JSONResponse: 操作结果
    """
    try:
        # 验证原路径
        source = _validate_path(source_path)
        
        # 验证目标路径
        dest = _validate_path(dest_path)
        
        # 检查目标是否是目录
        if not dest.is_dir():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Destination must be a directory"
            )
        
        # 安全检查：防止复制到自身内部
        new_location = dest / source.name
        if not _is_safe_operation(source, new_location):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot copy directory into itself or its subdirectories"
            )
        
        # 检查目标位置是否已存在
        if new_location.exists() and not overwrite:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A file or directory with the same name already exists in the destination. Use overwrite=true to replace it."
            )
        
        # 执行复制
        is_dir = source.is_dir()
        if is_dir:
            # 复制目录
            if new_location.exists() and overwrite:
                shutil.rmtree(new_location)
            shutil.copytree(str(source), str(new_location))
        else:
            # 复制文件
            if new_location.exists() and overwrite:
                new_location.unlink()
            shutil.copy2(str(source), str(new_location))
        
        logger.info(f"复制: {source_path} -> {dest_path}/{source.name}")
        
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "success": True,
                "source_path": str(source.relative_to(STORAGE_DIR)),
                "dest_path": str(new_location.relative_to(STORAGE_DIR)),
                "is_directory": is_dir,
                "overwritten": overwrite and new_location.exists(),
                "message": f"{'Directory' if is_dir else 'File'} copied successfully"
            }
        )
        
    except HTTPException:
        raise
    except PermissionError as e:
        logger.error(f"权限错误复制: {source_path} -> {dest_path}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {str(e)}"
        )
    except Exception as e:
        logger.error(f"复制失败: {source_path} -> {dest_path}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to copy: {str(e)}"
        )


# 搜索文件
@router.get("/search")
async def search_files(
    q: str = Query(..., description="搜索关键词，支持*和?通配符"),
    path: Optional[str] = Query(None, description="搜索的根目录（为空时搜索整个storage）"),
    case_sensitive: bool = Query(False, description="是否区分大小写"),
    page: int = Query(1, ge=1, description="页码，从1开始"),
    limit: int = Query(100, ge=1, le=100, description="每页数量，最大100"),
) -> JSONResponse:
    """搜索文件/目录
    
    按名称搜索文件和目录，支持通配符
    搜索结果包含文件信息和匹配位置
    
    Args:
        q: 搜索关键词
        path: 搜索根目录
        case_sensitive: 是否区分大小写
        page: 页码
        limit: 每页数量
        
    Returns:
        JSONResponse: 搜索结果
    """
    try:
        # 确定搜索根目录
        if path:
            search_root = _validate_path(path)
            if not search_root.is_dir():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Search path must be a directory"
                )
        else:
            search_root = STORAGE_DIR
        
        # 将通配符模式转换为正则表达式
        # 简单的通配符支持：* -> .*, ? -> .
        import re
        pattern = re.escape(q)
        pattern = pattern.replace(r'\*', '.*').replace(r'\?', '.')
        
        if not case_sensitive:
            regex = re.compile(pattern, re.IGNORECASE)
        else:
            regex = re.compile(pattern)
        
        # 递归搜索
        matches = []
        for item in search_root.rglob("*"):
            if regex.search(item.name):
                try:
                    if item.is_file():
                        info = get_file_info(item)
                    else:
                        info = {
                            "name": item.name,
                            "path": str(item.relative_to(STORAGE_DIR)),
                            "size": 0,
                            "sha256": None,
                            "mime_type": "inode/directory",
                            "encoding": None,
                            "created_at": datetime.fromtimestamp(item.stat().st_ctime).isoformat(),
                            "modified_at": datetime.fromtimestamp(item.stat().st_mtime).isoformat(),
                            "accessed_at": datetime.fromtimestamp(item.stat().st_atime).isoformat(),
                            "is_file": False,
                            "is_dir": True,
                        }
                    matches.append(info)
                except Exception as e:
                    logger.warning(f"获取文件信息失败，跳过: {item}, error={e}")
                    continue
        
        # 按名称排序
        matches.sort(key=lambda x: x["name"].lower())
        
        # 分页处理
        total_matches = len(matches)
        total_pages = (total_matches + limit - 1) // limit  # 向上取整
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paged_matches = matches[start_idx:end_idx]
        
        logger.info(f"搜索: q={q}, 找到 {total_matches} 个结果")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "query": q,
                "search_root": str(search_root.relative_to(STORAGE_DIR)),
                "case_sensitive": case_sensitive,
                "total_matches": total_matches,
                "page": page,
                "limit": limit,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
                "matches": paged_matches,
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"搜索失败: q={q}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search: {str(e)}"
        )


# 打包下载多个文件/目录
@router.get("/download/zip")
async def download_as_zip(
    paths: str = Query(..., description="要打包的路径列表，用逗号分隔（相对于storage目录）"),
    filename: Optional[str] = Query(None, description="自定义ZIP文件名（不含.zip扩展名）"),
) -> StreamingResponse:
    """打包下载多个文件/目录为ZIP
    
    支持选择多个文件和目录进行打包下载
    目录会被递归包含所有内容
    
    Args:
        paths: 路径列表（逗号分隔）
        filename: 自定义ZIP文件名
        
    Returns:
        StreamingResponse: ZIP文件流
    """
    try:
        # 解析路径列表
        path_list = [p.strip() for p in paths.split(",") if p.strip()]
        if not path_list:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="至少需要一个路径"
            )
        
        # 验证所有路径
        validated_paths = []
        for p in path_list:
            try:
                validated_paths.append(_validate_path(p))
            except HTTPException:
                # 如果路径不存在，记录并跳过
                logger.warning(f"跳过不存在的路径: {p}")
                continue
        
        if not validated_paths:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="所有指定的路径都不存在"
            )
        
        # 创建内存ZIP文件
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for item_path in validated_paths:
                # 计算在ZIP中的相对路径
                rel_path = item_path.relative_to(STORAGE_DIR)
                
                if item_path.is_file():
                    # 添加单个文件
                    zip_file.write(str(item_path), str(rel_path))
                else:
                    # 递归添加目录
                    for file_path in item_path.rglob("*"):
                        if file_path.is_file():
                            file_rel_path = file_path.relative_to(STORAGE_DIR)
                            zip_file.write(str(file_path), str(file_rel_path))
        
        # 设置ZIP文件名
        zip_filename = filename or f"download_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if not zip_filename.endswith('.zip'):
            zip_filename += '.zip'
        
        # 将缓冲区指针重置到开头
        zip_buffer.seek(0)
        
        logger.info(f"打包下载: {len(validated_paths)} 个路径 -> {zip_filename}")
        
        return StreamingResponse(
            iter([zip_buffer.getvalue()]),
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={zip_filename}",
                "Content-Type": "application/zip"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"打包下载失败: paths={paths}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create zip: {str(e)}"
        )


# 回收站操作 - 移入回收站
@router.post("/trash/{path:path}")
async def move_to_trash(
    path: str,
    rename: bool = Query(True, description="是否重命名以避免冲突"),
) -> JSONResponse:
    """将文件/目录移入回收站
    
    这是DELETE接口的替代方案，允许更灵活的控制
    默认会添加时间戳前缀以避免文件名冲突
    
    Args:
        path: 要移入回收站的路径
        rename: 是否重命名
        
    Returns:
        JSONResponse: 操作结果
    """
    try:
        # 验证路径
        target_path = _validate_path(path)
        
        # 特殊路径检查
        if target_path == STORAGE_DIR:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot move root storage directory to trash"
            )
        
        if target_path == TRASH_DIR:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot move trash directory to itself"
            )
        
        # 确保回收站目录存在
        _ensure_trash_dir()
        
        # 生成回收站路径
        item_name = target_path.name
        if rename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            trash_item_name = f"{timestamp}_{item_name}"
        else:
            trash_item_name = item_name
        
        trash_path = TRASH_DIR / trash_item_name
        
        # 检查回收站中是否已存在同名文件（当rename=False时）
        if trash_path.exists() and not rename:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An item with the same name already exists in trash. Use rename=true to avoid conflict."
            )
        
        # 移动到回收站
        shutil.move(str(target_path), str(trash_path))
        
        logger.info(f"移入回收站: {path} -> {trash_item_name}")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "success": True,
                "original_path": str(target_path.relative_to(STORAGE_DIR)),
                "original_name": item_name,
                "trash_name": trash_item_name,
                "trash_path": str(trash_path.relative_to(STORAGE_DIR)),
                "is_directory": target_path.is_dir(),
                "renamed": rename,
                "message": "Item moved to trash successfully"
            }
        )
        
    except HTTPException:
        raise
    except PermissionError as e:
        logger.error(f"权限错误移入回收站: {path}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {str(e)}"
        )
    except Exception as e:
        logger.error(f"移入回收站失败: {path}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to move to trash: {str(e)}"
        )


# 列出回收站内容
@router.get("/trash")
async def list_trash_contents(
    page: int = Query(1, ge=1, description="页码，从1开始"),
    limit: int = Query(100, ge=1, le=100, description="每页数量，最大100"),
) -> JSONResponse:
    """列出回收站中的文件/目录
    
    显示回收站中的内容，包含原始路径信息和时间戳
    支持分页查看
    
    Args:
        page: 页码
        limit: 每页数量
        
    Returns:
        JSONResponse: 回收站内容
    """
    try:
        # 确保回收站目录存在
        _ensure_trash_dir()
        
        # 获取回收站中所有项目
        trash_items = []
        for item in TRASH_DIR.iterdir():
            try:
                # 解析文件名以提取原始名称和时间戳
                item_name = item.name
                is_dir = item.is_dir()
                
                # 尝试解析时间戳前缀（格式：YYYYMMDD_HHMMSS_原始名称）
                original_name = item_name
                timestamp = None
                
                if "_" in item_name:
                    parts = item_name.split("_", 2)
                    if len(parts) >= 3 and len(parts[0]) == 8 and len(parts[1]) == 6:
                        # 看起来像时间戳格式：YYYYMMDD_HHMMSS_原始名称
                        try:
                            datetime.strptime(f"{parts[0]}_{parts[1]}", "%Y%m%d_%H%M%S")
                            timestamp = f"{parts[0]}_{parts[1]}"
                            original_name = "_".join(parts[2:]) if len(parts) > 2 else item_name
                        except ValueError:
                            pass
                
                # 获取项目信息
                if is_dir:
                    info = {
                        "name": item_name,
                        "original_name": original_name,
                        "path": str(item.relative_to(STORAGE_DIR)),
                        "size": 0,
                        "sha256": None,
                        "mime_type": "inode/directory",
                        "encoding": None,
                        "created_at": datetime.fromtimestamp(item.stat().st_ctime).isoformat(),
                        "modified_at": datetime.fromtimestamp(item.stat().st_mtime).isoformat(),
                        "is_file": False,
                        "is_dir": True,
                    }
                else:
                    info = get_file_info(item)
                    info["original_name"] = original_name
                
                info["timestamp"] = timestamp
                info["deleted_at"] = timestamp  # 向后兼容
                
                trash_items.append(info)
            except Exception as e:
                logger.warning(f"处理回收站项目失败，跳过: {item}, error={e}")
                continue
        
        # 按删除时间倒序排序（最近删除的在前）
        trash_items.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
        
        # 分页处理
        total_items = len(trash_items)
        total_pages = (total_items + limit - 1) // limit
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paged_items = trash_items[start_idx:end_idx]
        
        # 计算回收站统计
        total_size = sum(item.get("size", 0) for item in trash_items)
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "trash_dir": str(TRASH_DIR.relative_to(STORAGE_DIR)),
                "total_items": total_items,
                "total_size": total_size,
                "total_size_human": _human_readable_size(total_size),
                "page": page,
                "limit": limit,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
                "items": paged_items,
            }
        )
        
    except Exception as e:
        logger.error(f"列出回收站失败: error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list trash contents: {str(e)}"
        )


# TODO: 添加缩略图生成功能
# 需要安装Pillow库：pip install pillow
# v4: 添加文件缩略图生成和预览

# 缩略图相关功能
def _is_image_file(file_path: Path) -> bool:
    """检查文件是否是支持的图像格式
    
    Args:
        file_path: 文件路径
        
    Returns:
        bool: 是否是支持的图像文件
    """
    # 支持的图像扩展名
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}
    return file_path.suffix.lower() in image_extensions


def _generate_thumbnail(
    image_path: Path,
    width: int = 200,
    height: int = 200,
    quality: int = 85
) -> Optional[bytes]:
    """生成缩略图
    
    注意：这里需要Pillow库，但我不想在顶部无条件导入
    因为不是所有环境都安装了Pillow，所以动态导入
    
    Args:
        image_path: 图像文件路径
        width: 缩略图宽度
        height: 缩略图高度
        quality: JPEG质量 (1-100)
        
    Returns:
        Optional[bytes]: 缩略图字节数据，失败返回None
    """
    try:
        # 动态导入Pillow，避免在没有安装时导致导入错误
        from PIL import Image
        import io
        
        # 打开图像
        with Image.open(image_path) as img:
            # 转换模式（如果是RGBA/P等）
            if img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            
            # 计算新的尺寸，保持宽高比
            img_width, img_height = img.size
            ratio = min(width / img_width, height / img_height)
            new_width = int(img_width * ratio)
            new_height = int(img_height * ratio)
            
            # 调整大小
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # 保存到内存
            thumbnail_buffer = io.BytesIO()
            img.save(thumbnail_buffer, format='JPEG', quality=quality)
            
            return thumbnail_buffer.getvalue()
            
    except ImportError:
        logger.warning("Pillow库未安装，无法生成缩略图")
        return None
    except Exception as e:
        logger.error(f"生成缩略图失败: {image_path}, error={e}")
        return None


@router.get("/thumb/{file_id_or_path}")
async def get_thumbnail(
    file_id_or_path: str,
    width: int = Query(200, ge=50, le=800, description="缩略图宽度"),
    height: int = Query(200, ge=50, le=800, description="缩略图高度"),
    quality: int = Query(85, ge=1, le=100, description="JPEG质量 (1-100)"),
) -> StreamingResponse:
    """获取文件缩略图
    
    为图像文件生成缩略图，支持调整尺寸和质量
    如果不是图像文件或Pillow未安装，返回错误
    
    Args:
        file_id_or_path: 文件ID（SHA256）或相对路径
        width: 缩略图宽度
        height: 缩略图高度
        quality: JPEG质量
        
    Returns:
        StreamingResponse: 缩略图图像流
    """
    try:
        # 首先尝试作为路径处理
        file_path = (STORAGE_DIR / file_id_or_path).resolve()
        
        # 安全检查：确保路径在STORAGE_DIR内
        if not str(file_path).startswith(str(STORAGE_DIR.resolve())):
            # 如果不是有效路径，尝试作为文件ID查找
            file_path = None
            for potential_file in STORAGE_DIR.rglob("*"):
                if potential_file.is_file():
                    # 计算文件哈希
                    sha256_hash = hashlib.sha256()
                    try:
                        with open(potential_file, "rb") as f:
                            for chunk in iter(lambda: f.read(4096), b""):
                                sha256_hash.update(chunk)
                        file_hash = sha256_hash.hexdigest()
                        if file_hash == file_id_or_path:
                            file_path = potential_file
                            break
                    except Exception:
                        continue
        
        if not file_path or not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found"
            )
        
        if not file_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Path is not a file"
            )
        
        # 检查是否是支持的图像文件
        if not _is_image_file(file_path):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File is not a supported image format. Supported formats: JPG, JPEG, PNG, GIF, BMP, TIFF, WEBP"
            )
        
        # 生成缩略图
        thumbnail_data = _generate_thumbnail(file_path, width, height, quality)
        
        if thumbnail_data is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate thumbnail. Pillow library may not be installed."
            )
        
        logger.info(f"生成缩略图: {file_path.name}, size={width}x{height}")
        
        return StreamingResponse(
            iter([thumbnail_data]),
            media_type="image/jpeg",
            headers={
                "Content-Type": "image/jpeg",
                "Cache-Control": "public, max-age=3600"  # 缓存1小时
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取缩略图失败: id={file_id_or_path}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get thumbnail: {str(e)}"
        )


@router.post("/directories")
async def create_directory(
    path: str = Query(..., description="目录路径（相对于storage目录）"),
    directory_name: str = Query(..., description="要创建的目录名称"),
) -> JSONResponse:
    """创建新目录
    
    在指定路径下创建新目录
    目录名称不能包含路径分隔符
    
    Args:
        path: 相对路径（相对于storage目录）
        directory_name: 要创建的目录名称
        
    Returns:
        JSONResponse: 操作结果
    """
    try:
        # 确定目标目录
        if path:
            target_path = (STORAGE_DIR / path).resolve()
            # 安全检查：确保目标路径在STORAGE_DIR内
            if not str(target_path).startswith(str(STORAGE_DIR.resolve())):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Path traversal is not allowed"
                )
        else:
            target_path = STORAGE_DIR
        
        # 检查路径是否存在且是目录
        if not target_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Parent directory not found"
            )
        
        if not target_path.is_dir():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parent path is not a directory"
            )
        
        # 检查目录名称是否包含非法字符（主要是路径分隔符）
        if "/" in directory_name or "\\" in directory_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Directory name cannot contain path separators"
            )
        
        # 检查目录名称是否为空
        if not directory_name.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Directory name cannot be empty"
            )
        
        # 创建新目录路径
        new_dir_path = target_path / directory_name
        
        # 检查目录是否已存在
        if new_dir_path.exists():
            if new_dir_path.is_dir():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Directory already exists"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A file with the same name already exists"
                )
        
        # 创建目录
        new_dir_path.mkdir(parents=False, exist_ok=False)  # 不创建父目录（父目录应已存在）
        
        logger.info(f"创建目录成功: {new_dir_path.relative_to(STORAGE_DIR)}")
        
        # 获取新创建的目录信息
        dir_info = {
            "name": directory_name,
            "path": str(new_dir_path.relative_to(STORAGE_DIR)),
            "created_at": datetime.now().isoformat(),
            "message": "Directory created successfully"
        }
        
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=dir_info
        )
        
    except HTTPException:
        raise
    except PermissionError as e:
        logger.error(f"权限错误创建目录: {path}/{directory_name}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {str(e)}"
        )
    except Exception as e:
        logger.error(f"创建目录失败: path={path}, name={directory_name}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create directory: {str(e)}"
        )
