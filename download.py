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

文件下载模块
支持HTTP断点续传（Range头）
"""

import logging
import mimetypes
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, status, Header, Request
from fastapi.responses import FileResponse, StreamingResponse, Response

from config import STORAGE_DIR

logger = logging.getLogger(__name__)

def safe_content_disposition(filename: str) -> str:
    """安全构建 Content-Disposition header，处理非ASCII文件名
    
    Args:
        filename: 原始文件名
        
    Returns:
        安全的 Content-Disposition header 值
    """
    # 检查文件名是否只包含ASCII字符
    try:
        filename.encode('ascii')
        # 纯ASCII，直接使用
        return f'attachment; filename="{filename}"'
    except UnicodeEncodeError:
        # 包含非ASCII字符，使用RFC 5987编码
        # UTF-8编码 + 百分号编码
        encoded = quote(filename, encoding='utf-8')
        return f"attachment; filename*=UTF-8''{encoded}"

router = APIRouter(prefix="/download", tags=["download"])


def parse_range_header(range_header: Optional[str], file_size: int) -> Optional[Tuple[int, int]]:
    """解析Range头，返回起始和结束位置（包含）
    
    支持格式：Range: bytes=0-499 或 Range: bytes=500-
    简化：仅支持单区间，不支持多区间（如 bytes=0-499,1000-1499）
    
    Args:
        range_header: Range头字符串
        file_size: 文件总大小
        
    Returns:
        Optional[Tuple[int, int]]: (start, end) 或 None（表示无Range请求）
        
    Raises:
        HTTPException: Range格式无效或无法满足
    """
    if not range_header:
        return None
    
    # 检查格式
    if not range_header.startswith("bytes="):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid range format, must start with 'bytes='"
        )
    
    range_spec = range_header[6:]  # 去掉 "bytes="
    
    # 简化：只处理单区间
    ranges = range_spec.split(",")
    if len(ranges) > 1:
        # v2: 可支持多区间（返回multipart/byteranges）
        # 为简化，暂时不支持多区间
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail="Multiple ranges not supported (yet)"
        )
    
    range_str = ranges[0].strip()
    
    try:
        # 解析区间
        if range_str.startswith("-"):
            # 格式：-500（最后500字节）
            suffix_length = int(range_str[1:])
            if suffix_length <= 0 or suffix_length > file_size:
                raise ValueError()
            
            start = file_size - suffix_length
            end = file_size - 1
            
        elif range_str.endswith("-"):
            # 格式：500-（从500字节到文件末尾）
            start = int(range_str[:-1])
            if start < 0 or start >= file_size:
                raise ValueError()
            
            end = file_size - 1
            
        else:
            # 格式：0-499
            start_str, end_str = range_str.split("-", 1)
            start = int(start_str)
            end = int(end_str)
            
            if start < 0 or end >= file_size or start > end:
                raise ValueError()
        
        return (start, end)
        
    except (ValueError, IndexError):
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail=f"Invalid range: {range_str} for file size {file_size}"
        )


@router.get("/{file_path:path}")
async def download_file(
    request: Request,  # 添加Request参数，用于获取用户UUID
    file_path: str,
    range_header: Optional[str] = Header(None, alias="Range"),
):
    """下载文件，支持HTTP断点续传（仅使用路径，不支持哈希查找）
    
    支持标准Range头：Range: bytes=0-999
    若无Range：返回200 OK + 全文件
    若有Range：返回206 Partial Content + Content-Range
    
    Args:
        request: FastAPI请求对象，用于获取用户UUID
        file_path: 文件相对路径（相对于用户存储目录）
        range_header: Range请求头
        
    Returns:
        FileResponse | StreamingResponse: 文件响应（完整或部分内容）
    """
    # 从请求状态获取用户UUID（认证中间件应该已经设置好了）
    user_uuid = getattr(request.state, 'user_uuid', None)
    
    if not user_uuid:
        # 这不应该发生，因为认证中间件应该已经验证了
        logger.error("下载文件时无法获取用户UUID")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User authentication missing"
        )
    
    # 导入路径验证函数
    from api.utils.path_utils import validate_user_path
    
    try:
        # 验证路径并获取文件
        target_path = validate_user_path(user_uuid, file_path)
    except HTTPException as e:
        # 路径验证失败（可能是路径不存在或越权访问）
        logger.warning(f"用户文件路径验证失败: user={user_uuid}, path={file_path}, error={e.detail}")
        raise
    
    if not target_path.exists():
        logger.warning(f"用户文件不存在: user={user_uuid}, path={file_path}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    if not target_path.is_file():
        logger.warning(f"路径不是文件: user={user_uuid}, path={file_path}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path is not a file"
        )
    
    # 获取文件信息
    file_size = target_path.stat().st_size
    
    # 解析Range头
    range_tuple = parse_range_header(range_header, file_size)
    
    if range_tuple is None:
        # 无Range头，返回完整文件
        logger.info(f"完整下载: {file_path}, size={file_size}")
        
        # 猜测MIME类型
        mime_type, _ = mimetypes.guess_type(target_path.name)
        if not mime_type:
            mime_type = "application/octet-stream"
        
        return FileResponse(
            path=target_path,
            filename=target_path.name,
            media_type=mime_type,
            headers={
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
                "Content-Disposition": safe_content_disposition(target_path.name),
            }
        )
    
    else:
        # 有Range头，返回部分内容
        start, end = range_tuple
        content_length = end - start + 1
        
        logger.info(f"部分下载: {file_path}, range={start}-{end}, size={content_length}")
        
        # 构建部分内容响应
        async def range_content():
            """生成指定范围的文件内容"""
            with open(target_path, "rb") as f:
                f.seek(start)
                remaining = content_length
                chunk_size = 8192  # 8KB 块
                
                while remaining > 0:
                    read_size = min(chunk_size, remaining)
                    chunk = f.read(read_size)
                    if not chunk:
                        break
                    yield chunk
                    remaining -= len(chunk)
        
        # 猜测MIME类型
        mime_type, _ = mimetypes.guess_type(target_path.name)
        if not mime_type:
            mime_type = "application/octet-stream"
        
        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(content_length),
            "Accept-Ranges": "bytes",
            "Content-Disposition": safe_content_disposition(target_path.name),
        }
        
        return StreamingResponse(
            content=range_content(),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type=mime_type,
            headers=headers,
        )


@router.head("/{file_path:path}")
async def get_file_metadata(
    request: Request,  # 添加Request参数，用于获取用户UUID
    file_path: str,
) -> Response:
    """获取文件元数据（HEAD请求，仅使用路径，不支持哈希查找）
    
    用于客户端检查文件是否存在、大小等信息
    支持断点续传：返回Accept-Ranges头
    
    Args:
        request: FastAPI请求对象，用于获取用户UUID
        file_path: 文件相对路径（相对于用户存储目录）
        
    Returns:
        Response: 仅包含头部的响应
    """
    # 从请求状态获取用户UUID（认证中间件应该已经设置好了）
    user_uuid = getattr(request.state, 'user_uuid', None)
    
    if not user_uuid:
        # 这不应该发生，因为认证中间件应该已经验证了
        logger.error("获取文件元数据时无法获取用户UUID")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User authentication missing"
        )
    
    # 导入路径验证函数
    from api.utils.path_utils import validate_user_path
    
    try:
        # 验证路径并获取文件
        target_path = validate_user_path(user_uuid, file_path)
    except HTTPException as e:
        # 路径验证失败（可能是路径不存在或越权访问）
        logger.warning(f"用户文件路径验证失败(HEAD): user={user_uuid}, path={file_path}, error={e.detail}")
        raise
    
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
    
    # 获取文件信息
    file_size = target_path.stat().st_size
    
    # 猜测MIME类型
    mime_type, _ = mimetypes.guess_type(target_path.name)
    if not mime_type:
        mime_type = "application/octet-stream"
    
    logger.info(f"文件元数据查询: {file_path}, size={file_size}")
    
    return Response(
        status_code=status.HTTP_200_OK,
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
            "Content-Type": mime_type,
            "Content-Disposition": safe_content_disposition(target_path.name),
        }
    )


# v2: 添加下载限速（防止服务器过载）
# v3: 支持多区间Range请求（multipart/byteranges）
# v4: 添加下载统计和热文件缓存
