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

文件上传模块
实现分片上传、断点续传功能
"""

import logging
import hashlib
import shutil
import uuid
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, HTTPException, status, Query
from fastapi.responses import JSONResponse

from config import UPLOAD_DIR, STORAGE_DIR, CHUNK_SIZE, ensure_dirs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/upload", tags=["upload"])

# 内存中的上传状态跟踪（v1: 简单实现，重启后状态丢失）
# v2: 可考虑使用Redis或数据库持久化上传状态
upload_status: Dict[str, Dict] = {}


@router.post("/init")
async def init_upload() -> JSONResponse:
    """初始化上传，生成唯一upload_id
    
    客户端应先调用此接口获取upload_id，然后按分片上传
    支持断点续传：客户端可查询已上传分片情况
    
    Returns:
        JSONResponse: 包含upload_id和已上传分片信息
    """
    # 生成唯一上传ID
    upload_id = str(uuid.uuid4())
    
    # 创建上传目录
    upload_path = UPLOAD_DIR / upload_id
    upload_path.mkdir(parents=True, exist_ok=True)
    
    # 初始化状态
    upload_status[upload_id] = {
        "upload_path": upload_path,
        "uploaded_chunks": set(),  # 已上传的分片索引
        "created_at": datetime.now().isoformat(),
        "total_chunks": None,
    }
    
    logger.info(f"上传初始化: upload_id={upload_id}")
    
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "upload_id": upload_id,
            "uploaded_chunks": list(upload_status[upload_id]["uploaded_chunks"]),
            "message": "Upload initialized successfully"
        }
    )


@router.post("/chunk")
async def upload_chunk(
    upload_id: str = Query(..., description="上传会话ID"),
    index: int = Query(..., description="分片索引，从0开始"),
    file: UploadFile = File(...),
) -> JSONResponse:
    """上传单个分片
    
    每个分片 ≤ 4MB（由前端保证）
    分片存储在 ./uploads/{upload_id}/chunk_{index:04d}
    
    Args:
        upload_id: 上传会话ID
        index: 分片索引
        file: 分片文件
        
    Returns:
        JSONResponse: 上传结果
    """
    # 验证upload_id
    if upload_id not in upload_status:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload session not found or expired"
        )
    
    status_info = upload_status[upload_id]
    upload_path: Path = status_info["upload_path"]
    
    # 检查是否已上传（断点续传支持）
    if index in status_info["uploaded_chunks"]:
        logger.info(f"分片已存在，跳过: upload_id={upload_id}, chunk={index}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "upload_id": upload_id,
                "chunk": index,
                "message": "Chunk already uploaded, skipped"
            }
        )
    
    # 构建分片文件名
    chunk_filename = f"chunk_{index:04d}"
    chunk_path = upload_path / chunk_filename
    
    try:
        # 读取分片数据
        content = await file.read()
        
        # 验证分片大小（不超过CHUNK_SIZE）
        if len(content) > CHUNK_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Chunk size exceeds limit ({CHUNK_SIZE} bytes)"
            )
        
        # 保存分片到磁盘
        with open(chunk_path, "wb") as f:
            f.write(content)
        
        # 更新状态
        status_info["uploaded_chunks"].add(index)
        
        logger.info(f"分片上传成功: upload_id={upload_id}, chunk={index}/{len(content)} bytes")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "upload_id": upload_id,
                "chunk": index,
                "size": len(content),
                "message": "Chunk uploaded successfully"
            }
        )
        
    except Exception as e:
        logger.error(f"分片上传失败: upload_id={upload_id}, chunk={index}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload chunk: {str(e)}"
        )


@router.post("/finish")
async def finish_upload(
    upload_id: str = Query(..., description="上传会话ID"),
    filename: str = Query(..., description="原始文件名"),
    total_chunks: int = Query(..., description="总分片数"),
) -> JSONResponse:
    """完成上传，合并分片
    
    客户端在所有分片上传完成后调用此接口
    服务端合并分片，计算文件哈希（SHA256）作为文件ID
    文件最终存储在 ./storage/{file_id}
    
    Args:
        upload_id: 上传会话ID
        filename: 原始文件名
        total_chunks: 总分片数
        
    Returns:
        JSONResponse: 包含文件ID和存储路径
    """
    # 验证upload_id
    if upload_id not in upload_status:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload session not found or expired"
        )
    
    status_info = upload_status[upload_id]
    upload_path: Path = status_info["upload_path"]
    
    # 验证是否所有分片都已上传
    uploaded_chunks = status_info["uploaded_chunks"]
    expected_chunks = set(range(total_chunks))
    
    if uploaded_chunks != expected_chunks:
        missing = expected_chunks - uploaded_chunks
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing chunks: {sorted(missing)}"
        )
    
    try:
        # 确定最终文件名（防覆盖）
        final_filename = filename
        final_path = STORAGE_DIR / final_filename
        
        # 如果文件已存在，添加时间戳后缀
        counter = 1
        while final_path.exists():
            name_parts = filename.rsplit(".", 1)
            if len(name_parts) == 2:
                name, ext = name_parts
                final_filename = f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{counter}.{ext}"
            else:
                final_filename = f"{filename}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{counter}"
            
            final_path = STORAGE_DIR / final_filename
            counter += 1
        
        # 合并分片
        with open(final_path, "wb") as output_file:
            for i in range(total_chunks):
                chunk_filename = f"chunk_{i:04d}"
                chunk_path = upload_path / chunk_filename
                
                with open(chunk_path, "rb") as chunk_file:
                    shutil.copyfileobj(chunk_file, output_file)
                
                logger.debug(f"合并分片: {i+1}/{total_chunks}")
        
        # 计算文件SHA256哈希作为文件ID
        sha256_hash = hashlib.sha256()
        with open(final_path, "rb") as f:
            # 分块读取大文件
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        
        file_id = sha256_hash.hexdigest()
        
        # 可选：重命名文件为哈希值（便于查找）
        # hashed_path = STORAGE_DIR / file_id
        # final_path.rename(hashed_path)
        # final_path = hashed_path
        
        # 清理临时文件
        try:
            shutil.rmtree(upload_path)
            del upload_status[upload_id]  # 移除状态
        except Exception as e:
            logger.warning(f"清理临时文件失败: {upload_path}, error={e}")
        
        logger.info(f"上传完成: upload_id={upload_id}, file_id={file_id}, size={final_path.stat().st_size}")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "file_id": file_id,
                "filename": final_filename,
                "original_filename": filename,
                "size": final_path.stat().st_size,
                "sha256": file_id,
                "message": "File uploaded and merged successfully"
            }
        )
        
    except Exception as e:
        logger.error(f"合并分片失败: upload_id={upload_id}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to merge chunks: {str(e)}"
        )


@router.get("/status/{upload_id}")
async def get_upload_status(upload_id: str) -> JSONResponse:
    """查询上传状态（断点续传）
    
    客户端可查询已上传的分片，实现断点续传
    
    Args:
        upload_id: 上传会话ID
        
    Returns:
        JSONResponse: 上传状态信息
    """
    if upload_id not in upload_status:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload session not found or expired"
        )
    
    status_info = upload_status[upload_id]
    
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "upload_id": upload_id,
            "uploaded_chunks": sorted(status_info["uploaded_chunks"]),
            "created_at": status_info["created_at"],
            "total_chunks": status_info["total_chunks"],
        }
    )


# v2: 添加分片上传超时清理（定时任务清理过期上传）
# v3: 支持并行上传优化（多个分片同时上传）
# v4: 添加上传进度WebSocket推送
