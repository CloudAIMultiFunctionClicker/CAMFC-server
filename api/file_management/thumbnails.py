"""
缩略图相关功能模块
提供图像文件的缩略图生成和预览功能

注意：这个模块依赖于Pillow库来生成缩略图
如果没有安装Pillow，缩略图功能将不可用
"""

import logging
import hashlib
from pathlib import Path
from typing import Optional
import io

from fastapi import APIRouter, HTTPException, status, Query, Request
from fastapi.responses import StreamingResponse

from config import get_user_storage_dir
from api.utils.path_utils import validate_user_path

logger = logging.getLogger(__name__)

# 创建缩略图专用的路由
# 这里暂时不把router导入到main中，因为可能会创建多个缩略图相关的路由
# 或者我们可以选择在需要的地方导入这个router

router = APIRouter(prefix="/files/thumb", tags=["files-thumbnails"])


def _is_image_file(file_path: Path) -> bool:
    """检查文件是否是支持的图像格式
    
    目前支持常见的图片格式，不过我感觉列表可能不够全
    比如有些相机用的RAW格式就没包含，不过那些格式用缩略图意义也不大？
    
    Args:
        file_path: 文件路径
        
    Returns:
        bool: 是否是支持的图像文件
    """
    # 支持的图像扩展名
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}
    # TODO: 也许应该通过文件魔数（magic number）来判断更准确？
    # 不过扩展名判断简单快捷，先这样吧
    return file_path.suffix.lower() in image_extensions


def _generate_thumbnail(
    image_path: Path,
    width: int = 200,
    height: int = 200,
    quality: int = 85
) -> Optional[bytes]:
    """生成缩略图
    
    注意：这里需要Pillow库，但我不想在顶部无条件导入
    因为不是所有环境都安装了Pillow，所以动态导入
    如果Pillow没安装，就返回None
    
    Args:
        image_path: 图像文件路径
        width: 缩略图宽度
        height: 缩略图高度
        quality: JPEG质量 (1-100)
        
    Returns:
        Optional[bytes]: 缩略图字节数据，失败返回None
    """
    try:
        # 动态导入Pillow，避免在没有安装时导致导入错误
        # 这里我有点犹豫，动态导入会影响性能吗？不过缩略图生成本来就不频繁，应该还好
        from PIL import Image
        
        # 打开图像
        with Image.open(image_path) as img:
            # 转换模式（如果是RGBA/P等）
            # 之前遇到过PNG带透明通道，直接转JPEG会丢失透明度，不过缩略图好像问题不大？
            if img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            
            # 计算新的尺寸，保持宽高比
            img_width, img_height = img.size
            # 这里用min来保持宽高比，避免图片变形
            ratio = min(width / img_width, height / img_height)
            new_width = int(img_width * ratio)
            new_height = int(img_height * ratio)
            
            # 调整大小
            # LANCZOS据说质量最好，不过处理速度慢一点
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # 保存到内存
            thumbnail_buffer = io.BytesIO()
            # 统一保存为JPEG格式，虽然可能不是最佳选择（比如PNG会更适合带透明通道的图片）
            # 不过JPEG压缩率高，文件小，适合网络传输
            img.save(thumbnail_buffer, format='JPEG', quality=quality)
            
            return thumbnail_buffer.getvalue()
            
    except ImportError:
        logger.warning("Pillow库未安装，无法生成缩略图")
        # 其实这里可以给用户更明确的提示，或者提供安装指引
        return None
    except Exception as e:
        logger.error(f"生成缩略图失败: {image_path}, error={e}")
        # 这里应该记录更详细的错误信息，方便调试
        # 比如图片文件损坏、权限问题等等
        return None


@router.get("/{file_id_or_path}")
async def get_thumbnail(
    request: Request,
    file_id_or_path: str,
    width: int = Query(200, ge=50, le=800, description="缩略图宽度"),
    height: int = Query(200, ge=50, le=800, description="缩略图高度"),
    quality: int = Query(85, ge=1, le=100, description="JPEG质量 (1-100)"),
) -> StreamingResponse:
    """获取文件缩略图（重构版，支持用户隔离存储）
    
    为图像文件生成缩略图，支持调整尺寸和质量
    如果不是图像文件或Pillow未安装，返回错误
    
    Args:
        request: FastAPI请求对象，用于获取用户UUID
        file_id_or_path: 文件ID（SHA256）或相对路径（相对于用户存储目录）
        width: 缩略图宽度
        height: 缩略图高度
        quality: JPEG质量
        
    Returns:
        StreamingResponse: 缩略图图像流
    """
    try:
        # 从请求状态获取用户UUID
        user_uuid = getattr(request.state, 'user_uuid', None)
        if not user_uuid:
            logger.error("获取缩略图时无法获取用户UUID")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication missing"
            )
        
        # 获取用户的存储目录
        user_dir = get_user_storage_dir(user_uuid)
        
        # 首先尝试作为路径处理
        file_path = None
        try:
            file_path = validate_user_path(user_uuid, file_id_or_path)
        except HTTPException:
            # 如果不是有效路径，尝试作为文件ID查找
            for potential_file in user_dir.rglob("*"):
                if potential_file.is_file():
                    # 计算文件哈希
                    sha256_hash = hashlib.sha256()
                    try:
                        with open(potential_file, "rb") as f:
                            for chunk in iter(lambda: f.read(4096), b""):
                                sha256_hash.update(chunk)
                        file_hash = sha256_hash.hexdigest()
                        if file_hash == file_id_or_path:
                            file_path = potential_file
                            break
                    except Exception:
                        continue
        
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
        
        # 检查是否是支持的图像文件
        if not _is_image_file(file_path):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File is not a supported image format. Supported formats: JPG, JPEG, PNG, GIF, BMP, TIFF, WEBP"
            )
        
        # 生成缩略图
        thumbnail_data = _generate_thumbnail(file_path, width, height, quality)
        
        if thumbnail_data is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate thumbnail. Pillow library may not be installed."
            )
        
        logger.info(f"生成缩略图: user={user_uuid}, file={file_path.name}, size={width}x{height}")
        
        return StreamingResponse(
            iter([thumbnail_data]),
            media_type="image/jpeg",
            headers={
                "Content-Type": "image/jpeg",
                "Cache-Control": "public, max-age=3600",
                "X-User-UUID": user_uuid  # 添加用户UUID到响应头，方便调试
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取缩略图失败: id={file_id_or_path}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get thumbnail: {str(e)}"
        )
