"""
回收站管理模块（重构版，支持用户隔离存储）
提供文件移入回收站、查看回收站内容等功能

现在每个用户有自己的回收站目录：/storage/{user_uuid}/.trash/
"""
import logging
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict

from fastapi import APIRouter, HTTPException, status, Query, Request
from fastapi.responses import JSONResponse

from config import get_user_storage_dir
from api.utils.path_utils import validate_user_path
from api.file_operations.browse import get_file_info

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/files", tags=["files"])

def _ensure_trash_dir(user_uuid: str) -> Path:
    """确保用户的回收站目录存在
    
    Args:
        user_uuid: 用户UUID
        
    Returns:
        Path: 用户的回收站目录路径
    """
    # 获取用户的存储目录
    user_dir = get_user_storage_dir(user_uuid)
    
    # 用户的回收站目录
    user_trash_dir = user_dir / ".trash"
    
    if not user_trash_dir.exists():
        user_trash_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"创建用户回收站目录: user={user_uuid}, path={user_trash_dir}")
    
    return user_trash_dir


@router.post("/trash/{path:path}")
async def move_to_trash(
    request: Request,
    path: str,
    rename: bool = Query(True, description="是否重命名以避免冲突"),
) -> JSONResponse:
    """将文件/目录移入回收站（重构版，支持用户隔离存储）
    
    这是DELETE接口的替代方案，允许更灵活的控制
    默认会添加时间戳前缀以避免文件名冲突
    
    Args:
        request: FastAPI请求对象，用于获取用户UUID
        path: 要移入回收站的路径（相对于用户存储目录）
        rename: 是否重命名
        
    Returns:
        JSONResponse: 操作结果
    """
    try:
        # 从请求状态获取用户UUID
        user_uuid = getattr(request.state, 'user_uuid', None)
        if not user_uuid:
            logger.error("移入回收站时无法获取用户UUID")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication missing"
            )
        
        # 获取用户的存储目录
        user_dir = get_user_storage_dir(user_uuid)
        
        # 验证路径
        target_path = validate_user_path(user_uuid, path)
        
        # 特殊路径检查
        if target_path == user_dir:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot move user root directory to trash"
            )
        
        # 获取用户的回收站目录
        user_trash_dir = _ensure_trash_dir(user_uuid)
        
        if target_path == user_trash_dir:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot move trash directory to itself"
            )
        
        # 生成回收站路径
        item_name = target_path.name
        if rename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            trash_item_name = f"{timestamp}_{item_name}"
        else:
            trash_item_name = item_name
        
        trash_path = user_trash_dir / trash_item_name
        
        # 检查回收站中是否已存在同名文件（当rename=False时）
        if trash_path.exists() and not rename:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An item with the same name already exists in trash. Use rename=true to avoid conflict."
            )
        
        # 移动到回收站
        shutil.move(str(target_path), str(trash_path))
        
        logger.info(f"移入回收站: user={user_uuid}, {path} -> {trash_item_name}")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "success": True,
                "original_path": str(target_path.relative_to(user_dir)),
                "original_name": item_name,
                "trash_name": trash_item_name,
                "trash_path": str(trash_path.relative_to(user_dir)),
                "is_directory": target_path.is_dir(),
                "renamed": rename,
                "user_uuid": user_uuid,
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


@router.get("/trash")
async def list_trash_contents(
    request: Request,
    page: int = Query(1, ge=1, description="页码，从1开始"),
    limit: int = Query(100, ge=1, le=100, description="每页数量，最大100"),
) -> JSONResponse:
    """列出回收站中的文件/目录（重构版，支持用户隔离存储）
    
    显示回收站中的内容，包含原始路径信息和时间戳
    支持分页查看
    
    Args:
        request: FastAPI请求对象，用于获取用户UUID
        page: 页码
        limit: 每页数量
        
    Returns:
        JSONResponse: 回收站内容
    """
    try:
        # 从请求状态获取用户UUID
        user_uuid = getattr(request.state, 'user_uuid', None)
        if not user_uuid:
            logger.error("列出回收站内容时无法获取用户UUID")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication missing"
            )
        
        # 获取用户的存储目录和回收站目录
        user_dir = get_user_storage_dir(user_uuid)
        user_trash_dir = _ensure_trash_dir(user_uuid)
        
        # 获取回收站中所有项目
        trash_items = []
        for item in user_trash_dir.iterdir():
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
                        "path": str(item.relative_to(user_dir)),
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
                    info = get_file_info(item, user_dir)
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
        
        # 人类可读大小转换函数
        def _human_readable_size(size_bytes: int) -> str:
            if size_bytes == 0:
                return "0 B"
            
            units = ["B", "KB", "MB", "GB", "TB"]
            unit_index = 0
            
            while size_bytes >= 1024 and unit_index < len(units) - 1:
                size_bytes /= 1024.0
                unit_index += 1
            
            return f"{size_bytes:.2f} {units[unit_index]}"
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "user_uuid": user_uuid,
                "trash_dir": str(user_trash_dir.relative_to(user_dir)),
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
