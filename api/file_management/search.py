"""
文件搜索和打包下载模块
提供文件搜索、ZIP打包下载等高级功能
"""

import logging
import re
import io
import zipfile
from pathlib import Path
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from config import get_user_storage_dir
from api.utils.path_utils import validate_user_path
from api.file_operations.browse import get_file_info

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/files", tags=["files"])


@router.get("/search")
async def search_files(
    request: Request,
    q: str = Query(..., description="搜索关键词，支持*和?通配符"),
    path: Optional[str] = Query(None, description="搜索的根目录（为空时搜索用户的整个存储目录）"),
    case_sensitive: bool = Query(False, description="是否区分大小写"),
    page: int = Query(1, ge=1, description="页码，从1开始"),
    limit: int = Query(100, ge=1, le=100, description="每页数量，最大100"),
) -> JSONResponse:
    """搜索文件/目录（重构版，支持用户隔离存储）
    
    按名称搜索文件和目录，支持通配符
    搜索结果包含文件信息和匹配位置
    
    Args:
        request: FastAPI请求对象，用于获取用户UUID
        q: 搜索关键词
        path: 搜索根目录（相对于用户存储目录）
        case_sensitive: 是否区分大小写
        page: 页码
        limit: 每页数量
        
    Returns:
        JSONResponse: 搜索结果
    """
    try:
        # 从请求状态获取用户UUID
        user_uuid = getattr(request.state, 'user_uuid', None)
        if not user_uuid:
            logger.error("搜索文件时无法获取用户UUID")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication missing"
            )
        
        # 获取用户的存储目录
        user_dir = get_user_storage_dir(user_uuid)
        
        # 确定搜索根目录
        if path:
            search_root = validate_user_path(user_uuid, path)
            if not search_root.is_dir():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Search path must be a directory"
                )
        else:
            search_root = user_dir
        
        # 将通配符模式转换为正则表达式
        # 简单的通配符支持：* -> .*, ? -> .
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
                        info = get_file_info(item, user_dir)
                    else:
                        info = {
                            "name": item.name,
                            "path": str(item.relative_to(user_dir)),
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
        
        logger.info(f"搜索: user={user_uuid}, q={q}, 找到 {total_matches} 个结果")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "user_uuid": user_uuid,
                "query": q,
                "search_root": str(search_root.relative_to(user_dir)),
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


@router.get("/download/zip")
async def download_as_zip(
    request: Request,
    paths: str = Query(..., description="要打包的路径列表，用逗号分隔（相对于用户存储目录）"),
    filename: Optional[str] = Query(None, description="自定义ZIP文件名（不含.zip扩展名）"),
) -> StreamingResponse:
    """打包下载多个文件/目录为ZIP（重构版，支持用户隔离存储）
    
    支持选择多个文件和目录进行打包下载
    目录会被递归包含所有内容
    
    Args:
        request: FastAPI请求对象，用于获取用户UUID
        paths: 路径列表（逗号分隔，相对于用户存储目录）
        filename: 自定义ZIP文件名
        
    Returns:
        StreamingResponse: ZIP文件流
    """
    try:
        # 从请求状态获取用户UUID
        user_uuid = getattr(request.state, 'user_uuid', None)
        if not user_uuid:
            logger.error("打包下载时无法获取用户UUID")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication missing"
            )
        
        # 获取用户的存储目录
        user_dir = get_user_storage_dir(user_uuid)
        
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
                validated_paths.append(validate_user_path(user_uuid, p))
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
                # 计算在ZIP中的相对路径（相对于用户目录）
                rel_path = item_path.relative_to(user_dir)
                
                if item_path.is_file():
                    # 添加单个文件
                    zip_file.write(str(item_path), str(rel_path))
                else:
                    # 递归添加目录
                    for file_path in item_path.rglob("*"):
                        if file_path.is_file():
                            file_rel_path = file_path.relative_to(user_dir)
                            zip_file.write(str(file_path), str(file_rel_path))
        
        # 设置ZIP文件名
        zip_filename = filename or f"download_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if not zip_filename.endswith('.zip'):
            zip_filename += '.zip'
        
        # 将缓冲区指针重置到开头
        zip_buffer.seek(0)
        
        logger.info(f"打包下载: user={user_uuid}, {len(validated_paths)} 个路径 -> {zip_filename}")
        
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
