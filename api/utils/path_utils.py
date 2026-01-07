"""
路径验证和安全检查工具函数
原来在 file_manager.py 中的路径相关函数
"""

from pathlib import Path
from typing import Optional
from fastapi import HTTPException, status

from config import STORAGE_DIR


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
