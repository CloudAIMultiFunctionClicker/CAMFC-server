"""
文件操作模块
提供删除、重命名、移动、复制等文件操作API
"""

import logging
import shutil
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Query
from fastapi.responses import JSONResponse

from config import STORAGE_DIR
from api.utils.path_utils import _validate_path, _is_safe_operation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/files", tags=["files"])


# 回收站相关（这里先定义，后面可能会移到单独的trash模块）
TRASH_DIR = STORAGE_DIR / ".trash"

def _ensure_trash_dir():
    """确保回收站目录存在"""
    if not TRASH_DIR.exists():
        TRASH_DIR.mkdir(parents=True, exist_ok=True)


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
