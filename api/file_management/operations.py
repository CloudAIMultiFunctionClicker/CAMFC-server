"""
文件操作模块
提供删除、重命名、移动、复制等文件操作API

重构说明：现在支持用户隔离存储
所有操作都在用户的存储目录内进行：/storage/{user_uuid}/
"""

import logging
import shutil
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Query, Request
from fastapi.responses import JSONResponse

from config import STORAGE_DIR, get_user_storage_dir
from api.utils.path_utils import validate_user_path, _is_safe_operation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/files", tags=["files"])


@router.delete("/{path:path}")
async def delete_file_or_directory(
    request: Request,
    path: str,
    permanent: bool = Query(False, description="是否永久删除（不走回收站）"),
) -> JSONResponse:
    """删除文件或目录（重构版，支持用户隔离存储）
    
    默认移动到回收站（用户目录内的.trash目录），可指定永久删除
    对于目录会递归删除所有内容
    
    Args:
        request: FastAPI请求对象，用于获取用户UUID
        path: 要删除的文件/目录路径（相对于用户存储目录）
        permanent: 是否永久删除
        
    Returns:
        JSONResponse: 操作结果
    """
    try:
        # 从请求状态获取用户UUID
        user_uuid = getattr(request.state, 'user_uuid', None)
        if not user_uuid:
            logger.error("删除文件时无法获取用户UUID")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication missing"
            )
        
        # 验证路径（相对于用户存储目录）
        target_path = validate_user_path(user_uuid, path)
        
        # 获取用户的存储目录
        user_dir = get_user_storage_dir(user_uuid)
        
        # 如果是用户的根目录，不允许删除
        if target_path == user_dir:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete user root directory"
            )
        
        # 用户的回收站目录
        user_trash_dir = user_dir / ".trash"
        
        # 如果是.trash目录，特殊处理
        if target_path == user_trash_dir:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete trash directory directly"
            )
        
        # 获取路径信息用于返回（相对于用户目录）
        is_dir = target_path.is_dir()
        item_name = target_path.name
        item_path = str(target_path.relative_to(user_dir))
        
        if permanent:
            # 永久删除
            if is_dir:
                shutil.rmtree(target_path)
                operation = "permanently deleted directory"
            else:
                target_path.unlink()
                operation = "permanently deleted file"
            logger.warning(f"永久删除: user={user_uuid}, path={item_path}")
        else:
            # 移动到回收站
            user_trash_dir.mkdir(exist_ok=True)
            
            # 生成唯一的回收站路径（避免文件名冲突）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            trash_item_name = f"{timestamp}_{item_name}"
            trash_path = user_trash_dir / trash_item_name
            
            # 移动文件/目录到回收站
            if is_dir:
                shutil.move(str(target_path), str(trash_path))
            else:
                shutil.move(str(target_path), str(trash_path))
            
            operation = "moved to trash"
            logger.info(f"移动到回收站: user={user_uuid}, {item_path} -> {trash_item_name}")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "success": True,
                "path": item_path,
                "name": item_name,
                "is_directory": is_dir,
                "operation": operation,
                "permanent": permanent,
                "user_uuid": user_uuid,
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


@router.patch("/rename")
async def rename_file_or_directory(
    request: Request,
    source_path: str = Query(..., description="原路径（相对于用户存储目录）"),
    new_name: str = Query(..., description="新名称（不含路径）"),
) -> JSONResponse:
    """重命名文件或目录（重构版，支持用户隔离存储）
    
    重命名操作是原子的，要么成功要么失败，不会处于中间状态
    新名称不能包含路径分隔符
    
    Args:
        request: FastAPI请求对象，用于获取用户UUID
        source_path: 原路径
        new_name: 新名称
        
    Returns:
        JSONResponse: 操作结果
    """
    try:
        # 从请求状态获取用户UUID
        user_uuid = getattr(request.state, 'user_uuid', None)
        if not user_uuid:
            logger.error("重命名文件时无法获取用户UUID")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication missing"
            )
        
        # 验证原路径
        source = validate_user_path(user_uuid, source_path)
        
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
        
        # 获取用户的存储目录，用于计算相对路径
        user_dir = get_user_storage_dir(user_uuid)
        
        logger.info(f"重命名: user={user_uuid}, {source_path} -> {new_name}")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "success": True,
                "old_path": str(source.relative_to(user_dir)),
                "old_name": source.name,
                "new_path": str(new_path.relative_to(user_dir)),
                "new_name": new_name,
                "is_directory": source.is_dir(),
                "user_uuid": user_uuid,
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


@router.patch("/move")
async def move_file_or_directory(
    request: Request,
    source_path: str = Query(..., description="原路径（相对于用户存储目录）"),
    dest_path: str = Query(..., description="目标目录路径（相对于用户存储目录）"),
) -> JSONResponse:
    """移动文件或目录到新位置（重构版，支持用户隔离存储）
    
    移动操作是原子的，会保持完整的目录结构
    不能移动到自身内部（防止循环）
    
    Args:
        request: FastAPI请求对象，用于获取用户UUID
        source_path: 原路径
        dest_path: 目标目录路径
        
    Returns:
        JSONResponse: 操作结果
    """
    try:
        # 从请求状态获取用户UUID
        user_uuid = getattr(request.state, 'user_uuid', None)
        if not user_uuid:
            logger.error("移动文件时无法获取用户UUID")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication missing"
            )
        
        # 验证原路径
        source = validate_user_path(user_uuid, source_path)
        
        # 验证目标路径
        dest = validate_user_path(user_uuid, dest_path)
        
        # 检查目标是否是目录
        if not dest.is_dir():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Destination must be a directory"
            )
        
        # 安全检查：防止移动到自身内部
        new_location = dest / source.name
        if not _is_safe_operation(source, new_location):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot move directory into itself or its subdirectories"
            )
        
        # 检查目标位置是否已存在同名文件/目录
        if new_location.exists():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A file or directory with the same name already exists in the destination"
            )
        
        # 执行移动（原子操作）
        shutil.move(str(source), str(dest))
        
        # 获取用户的存储目录，用于计算相对路径
        user_dir = get_user_storage_dir(user_uuid)
        
        logger.info(f"移动: user={user_uuid}, {source_path} -> {dest_path}")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "success": True,
                "old_path": str(source.relative_to(user_dir)),
                "new_path": str(new_location.relative_to(user_dir)),
                "is_directory": source.is_dir(),
                "user_uuid": user_uuid,
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


@router.post("/copy")
async def copy_file_or_directory(
    request: Request,
    source_path: str = Query(..., description="原路径（相对于用户存储目录）"),
    dest_path: str = Query(..., description="目标目录路径（相对于用户存储目录）"),
    overwrite: bool = Query(False, description="是否覆盖已存在的文件"),
) -> JSONResponse:
    """复制文件或目录（重构版，支持用户隔离存储）
    
    支持文件和目录的递归复制
    可以选择是否覆盖目标位置已存在的文件
    
    Args:
        request: FastAPI请求对象，用于获取用户UUID
        source_path: 原路径
        dest_path: 目标目录路径
        overwrite: 是否覆盖
        
    Returns:
        JSONResponse: 操作结果
    """
    try:
        # 从请求状态获取用户UUID
        user_uuid = getattr(request.state, 'user_uuid', None)
        if not user_uuid:
            logger.error("复制文件时无法获取用户UUID")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication missing"
            )
        
        # 验证原路径
        source = validate_user_path(user_uuid, source_path)
        
        # 验证目标路径
        dest = validate_user_path(user_uuid, dest_path)
        
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
        
        # 获取用户的存储目录，用于计算相对路径
        user_dir = get_user_storage_dir(user_uuid)
        
        logger.info(f"复制: user={user_uuid}, {source_path} -> {dest_path}/{source.name}")
        
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "success": True,
                "source_path": str(source.relative_to(user_dir)),
                "dest_path": str(new_location.relative_to(user_dir)),
                "is_directory": is_dir,
                "overwritten": overwrite and new_location.exists(),
                "user_uuid": user_uuid,
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


@router.post("/directories")
async def create_directory(
    request: Request,
    path: str = Query(..., description="目录路径（相对于用户存储目录）"),
    directory_name: str = Query(..., description="要创建的目录名称"),
) -> JSONResponse:
    """创建新目录（重构版，支持用户隔离存储）
    
    在用户存储目录的指定路径下创建新目录
    目录名称不能包含路径分隔符
    
    Args:
        request: FastAPI请求对象，用于获取用户UUID
        path: 相对路径（相对于用户存储目录）
        directory_name: 要创建的目录名称
        
    Returns:
        JSONResponse: 操作结果
    """
    try:
        # 从请求状态获取用户UUID
        user_uuid = getattr(request.state, 'user_uuid', None)
        if not user_uuid:
            logger.error("创建目录时无法获取用户UUID")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication missing"
            )
        
        # 获取用户的存储目录
        user_dir = get_user_storage_dir(user_uuid)
        
        # 确定目标目录
        if path:
            target_path = (user_dir / path).resolve()
            # 安全检查：确保目标路径在用户目录内
            if not str(target_path).startswith(str(user_dir.resolve())):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Path traversal is not allowed"
                )
        else:
            target_path = user_dir
        
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
        
        logger.info(f"创建目录成功: user={user_uuid}, {new_dir_path.relative_to(user_dir)}")
        
        # 获取新创建的目录信息
        dir_info = {
            "name": directory_name,
            "path": str(new_dir_path.relative_to(user_dir)),
            "created_at": datetime.now().isoformat(),
            "user_uuid": user_uuid,
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
