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

配置模块
用于管理上传、存储目录和全局设置
"""

import logging
from pathlib import Path
from typing import Optional

# 基础配置
BASE_DIR = Path(__file__).parent.absolute()  # 项目根目录

# 上传相关配置
UPLOAD_DIR = BASE_DIR / "uploads"            # 临时上传分片目录
STORAGE_DIR = BASE_DIR / "storage"           # 最终文件存储目录
CHUNK_SIZE = 4 * 1024 * 1024                 # 分片大小，4MB（与前端协商一致）

# 日志配置
LOG_LEVEL = logging.INFO
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# v1: 简单配置，后续可扩展为从环境变量或配置文件读取
# FIXME: 生产环境需支持热重载配置

def ensure_dirs() -> None:
    """确保必要的目录存在"""
    for dir_path in [UPLOAD_DIR, STORAGE_DIR]:
        dir_path.mkdir(exist_ok=True)
        logging.debug(f"确保目录存在: {dir_path}")

def get_file_path(file_id: str) -> Optional[Path]:
    """根据文件ID获取存储路径
    
    文件ID可以是SHA256哈希或UUID，对应storage目录下的文件名
    为简化，我们直接按文件名查找（不含子目录）
    
    【注意】重构后这个函数可能不太适用了，因为存储变成了用户隔离
    但先留着，后面再改或者废弃
    """
    # 简单实现：在storage目录下查找同名文件
    file_path = STORAGE_DIR / file_id
    if file_path.exists():
        return file_path
    
    # v2: 可考虑建立索引数据库或按哈希前缀分目录存储
    logging.warning(f"文件未找到: {file_id}")
    return None


def get_user_storage_dir(user_uuid: Optional[str] = None) -> Path:
    """获取用户的存储目录
    
    如果提供了user_uuid，返回 /storage/{user_uuid}/
    如果没提供，返回根存储目录（兼容旧代码）
    
    Args:
        user_uuid: 用户UUID，可以为None
    
    Returns:
        Path: 用户存储目录路径
    """
    if user_uuid:
        # 用户隔离存储
        user_dir = STORAGE_DIR / user_uuid
        # 确保目录存在
        user_dir.mkdir(exist_ok=True)
        return user_dir
    else:
        # 没提供UUID，返回根目录（可能用于一些不需要用户隔离的操作）
        return STORAGE_DIR


def get_user_file_path(user_uuid: str, file_id: str) -> Optional[Path]:
    """根据用户UUID和文件ID获取存储路径
    
    新版的get_file_path，考虑了用户隔离
    
    Args:
        user_uuid: 用户UUID
        file_id: 文件ID（文件名或哈希）
    
    Returns:
        Optional[Path]: 文件路径，如果找不到返回None
    """
    user_dir = get_user_storage_dir(user_uuid)
    file_path = user_dir / file_id
    
    if file_path.exists():
        return file_path
    
    logging.warning(f"用户文件未找到: user={user_uuid}, file={file_id}")
    return None


# TODO: 需要修改ensure_dirs函数，确保用户目录也会被创建
# 不过get_user_storage_dir里已经mkdir了，应该够用了
