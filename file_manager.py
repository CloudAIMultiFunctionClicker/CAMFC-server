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
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Query
from fastapi.responses import JSONResponse

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
) -> JSONResponse:
    """列出文件/目录
    
    列出指定目录下的文件和子目录
    默认列出根目录（storage目录）
    
    Args:
        path: 相对路径（相对于storage目录）
        recursive: 是否递归列出
        
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
            
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "path": str(target_path.relative_to(STORAGE_DIR)),
                    "recursive": True,
                    "total_files": file_count,
                    "total_size": total_size,
                    "files": all_files,
                }
            )
        else:
            # 非递归，列出目录内容
            dir_info = get_directory_info(target_path)
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
        size_bytes /= 1024.0
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
# v4: 添加文件缩略图生成和预览
