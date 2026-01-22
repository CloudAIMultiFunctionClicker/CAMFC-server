"""
路径验证和安全检查工具函数
原来在 file_manager.py 中的路径相关函数

【重构说明】需要支持用户隔离存储
新的路径验证应该基于用户的存储目录：/storage/{user_uuid}/
"""

from pathlib import Path
from typing import Optional
from fastapi import HTTPException, status

from config import STORAGE_DIR, get_user_storage_dir


def _validate_path(user_path: str) -> Path:
    """验证路径是否在STORAGE_DIR内（旧版，不支持用户隔离）
    
    【注意】重构后这个函数可能不适用了，因为存储变成了用户隔离
    但先留着，可能其他地方还用到了
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


def validate_user_path(user_uuid: str, user_path: str = "") -> Path:
    """验证用户路径是否在用户的存储目录内（新版，支持用户隔离）
    
    用户存储目录：/storage/{user_uuid}/
    所有用户操作都只能在这个目录内进行
    
    Args:
        user_uuid: 用户UUID，用于确定存储目录
        user_path: 用户提供的相对路径（相对于用户存储目录）
        
    Returns:
        Path: 解析后的安全路径
        
    Raises:
        HTTPException: 如果路径不安全或不存在
    """
    # 获取用户的存储目录
    user_dir = get_user_storage_dir(user_uuid)
    
    if not user_path or user_path == ".":
        target_path = user_dir
    else:
        # 注意：这里不能用resolve()，因为如果路径不存在resolve会出问题
        # 先用绝对路径计算，然后检查安全性
        try:
            # 构建目标路径
            target_path = (user_dir / user_path).resolve()
        except Exception as e:
            # 路径格式无效
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid path: {str(e)}"
            )
    
    # 安全检查：确保路径在用户的存储目录内
    user_dir_resolved = user_dir.resolve()
    if not str(target_path).startswith(str(user_dir_resolved)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path traversal is not allowed (user isolation)"
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
