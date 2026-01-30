"""
文件浏览和列表功能
提供文件信息查询、目录浏览、存储统计等API
"""

import logging
import mimetypes
import hashlib
import shutil
import os
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Query, Request
from fastapi.responses import JSONResponse

from config import STORAGE_DIR, get_user_storage_dir
from api.utils.path_utils import validate_user_path

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/files", tags=["files"])


def get_file_info(file_path: Path, user_dir: Path) -> Dict:
    """获取文件的详细信息
    
    Args:
        file_path: 文件路径
        user_dir: 用户的存储目录
        
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
        "path": str(file_path.relative_to(user_dir)),
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


def get_directory_info(dir_path: Path, user_dir: Path) -> Dict:
    """获取目录信息
    
    Args:
        dir_path: 目录路径
        user_dir: 用户的存储目录
        
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
                entries.append(get_file_info(entry, user_dir))
                total_size += entry.stat().st_size
                file_count += 1
            elif entry.is_dir():
                dir_stat = entry.stat()
                entries.append({
                    "name": entry.name,
                    "path": str(entry.relative_to(user_dir)),
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
            "path": str(dir_path.relative_to(user_dir)),
            "name": dir_path.name,
            "is_root": dir_path == user_dir,
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
    request: Request,
    path: Optional[str] = Query(None, description="相对路径，为空时列出用户根目录"),
    recursive: bool = Query(False, description="是否递归列出所有文件"),
    page: int = Query(1, ge=1, description="页码，从1开始"),
    limit: int = Query(100, ge=1, le=100, description="每页数量，最大100"),
) -> JSONResponse:
    """列出文件/目录（重构版，支持用户隔离存储）
    
    列出指定目录下的文件和子目录
    默认列出用户的根目录（/storage/{user_uuid}/）
    支持分页，每页最多100个文件
    
    Args:
        request: FastAPI请求对象，用于获取用户UUID
        path: 相对路径（相对于用户存储目录）
        recursive: 是否递归列出
        page: 页码，从1开始
        limit: 每页数量，最大100
        
    Returns:
        JSONResponse: 目录信息
    """
    try:
        # 从请求状态获取用户UUID
        user_uuid = getattr(request.state, 'user_uuid', None)
        if not user_uuid:
            logger.error("列出文件时无法获取用户UUID")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication missing"
            )
        
        # 获取用户的存储目录
        user_dir = get_user_storage_dir(user_uuid)
        
        # 验证路径（相对于用户存储目录）
        if path:
            target_path = validate_user_path(user_uuid, path)
        else:
            target_path = user_dir
        
        # 检查是否是目录
        if not target_path.is_dir():
            # 如果是文件，返回文件信息
            file_info = get_file_info(target_path, user_dir)
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "is_file": True,
                    "is_dir": False,
                    "file": file_info,
                    "user_uuid": user_uuid,
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
                    file_info = get_file_info(file_path, user_dir)
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
                    "path": str(target_path.relative_to(user_dir)),
                    "user_uuid": user_uuid,
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
            dir_info = get_directory_info(target_path, user_dir)
            
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
                "user_uuid": user_uuid,
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


@router.get("/info/{file_path:path}")
async def get_file_info_by_path(
    request: Request,
    file_path: str,
    include_content_hash: bool = Query(False, description="是否包含文件内容哈希（计算较慢，默认关闭）"),
) -> JSONResponse:
    """获取文件详细信息（仅使用路径，不支持哈希查找）
    
    通过相对路径获取文件详细信息
    
    Args:
        request: FastAPI请求对象，用于获取用户UUID
        file_path: 相对路径（相对于用户存储目录）
        include_content_hash: 是否计算文件哈希
        
    Returns:
        JSONResponse: 文件详细信息
    """
    try:
        # 从请求状态获取用户UUID
        user_uuid = getattr(request.state, 'user_uuid', None)
        if not user_uuid:
            logger.error("获取文件信息时无法获取用户UUID")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication missing"
            )
        
        # 验证路径并获取文件
        target_path = validate_user_path(user_uuid, file_path)
        
        if not target_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found"
            )
        
        if not target_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Path is not a file"
            )
        
        # 获取用户的存储目录
        user_dir = get_user_storage_dir(user_uuid)
        
        # 获取文件信息
        file_info = get_file_info(target_path, user_dir)
        
        # 如果不要求计算哈希，移除哈希字段以加快响应
        if not include_content_hash:
            file_info["sha256"] = None
        
        # 添加用户UUID
        file_info["user_uuid"] = user_uuid
        
        logger.info(f"获取文件信息: user={user_uuid}, file={target_path.name}, size={file_info['size']}")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=file_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文件信息失败: path={file_path}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get file info: {str(e)}"
        )


@router.get("/stats")
async def get_storage_stats(request: Request) -> JSONResponse:
    """获取存储统计信息（重构版，支持用户隔离存储）
    
    返回用户存储目录的整体统计信息
    
    Args:
        request: FastAPI请求对象，用于获取用户UUID
        
    Returns:
        JSONResponse: 存储统计信息
    """
    try:
        # 从请求状态获取用户UUID
        user_uuid = getattr(request.state, 'user_uuid', None)
        if not user_uuid:
            logger.error("获取存储统计时无法获取用户UUID")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication missing"
            )
        
        # 获取用户的存储目录
        user_dir = get_user_storage_dir(user_uuid)
        
        total_size = 0
        total_files = 0
        total_dirs = 0
        
        # 遍历用户存储目录计算统计
        for entry in user_dir.rglob("*"):
            if entry.is_file():
                total_size += entry.stat().st_size
                total_files += 1
            elif entry.is_dir():
                total_dirs += 1
        
        # 计算根目录统计（排除根目录自身）
        total_dirs = max(0, total_dirs - 1)  # 减去用户根目录自身
        
        # 获取存储目录信息
        storage_stat = user_dir.stat()
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "user_uuid": user_uuid,
                "storage_path": str(user_dir),
                "total_size_bytes": total_size,
                "total_size_human": _human_readable_size(total_size),
                "total_files": total_files,
                "total_directories": total_dirs,
                "created_at": datetime.fromtimestamp(storage_stat.st_ctime).isoformat(),
                "available_space": _get_available_space(user_dir),
                "message": "User storage statistics",
            }
        )
        
    except Exception as e:
        logger.error(f"获取存储统计失败: error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get storage stats: {str(e)}"
        )


def _human_readable_size(size_bytes: int) -> str:
    """将字节数转换为人类可读的格式
    
    这里用这个简单的方案，不搞太复杂的分级转换了
    TODO: 考虑是否需要更精细的单位转换
    """
    if size_bytes == 0:
        return "0 B"
    
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    
    while size_bytes >= 1024 and unit_index < len(units) - 1:
        size_bytes /= 1024.0
        unit_index += 1
    
    return f"{size_bytes:.2f} {units[unit_index]}"


def _get_available_space(path: Path) -> Dict:
    """获取可用磁盘空间信息
    
    注意：shutil.disk_usage在Windows上应该也能用
    不过如果权限不够可能会报错，这里简单处理下异常
    """
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
