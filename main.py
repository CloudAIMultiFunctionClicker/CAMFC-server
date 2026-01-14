"""
Copyright (C) 2026 Jiale Xu (许嘉乐) (ANTmmmmm) <https://github.com/ant-cave  >
Email: ANTmmmmm@outlook.com, ANTmmmmm@126.com, 1504596931@qq.com

Copyright (C) 2026 Xinhang Chen (陈欣航) <https://github.com/cxh09  >
Email: abc.cxh2009@foxmail.com

Copyright (C) 2026 Zimo Wen (温子墨) <https://github.com/lusamaqq  >
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
along with this program.  If not, see <https://www.gnu.org/licenses/  >.

主应用入口
FastAPI应用初始化、中间件设置、路由注册
"""

import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from config import ensure_dirs, LOG_LEVEL, LOG_FORMAT
from auth import AuthMiddleware, verify_token
from upload import router as upload_router
from download import router as download_router
# 导入新的模块化路由
from api.file_operations.browse import router as file_browse_router
from api.file_management.operations import router as file_operations_router
from api.file_management.search import router as file_search_router
from api.file_management.trash import router as file_trash_router
from api.file_management.thumbnails import router as file_thumbnails_router

# 配置日志
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI(
    title="最小可行网络云盘",
    description="一个支持断点续传的简单网络云盘后端",
    version="1.0.0",
    docs_url="/docs",  # Swagger UI
    redoc_url="/redoc",  # ReDoc
)

# 确保目录存在
ensure_dirs()
logger.info("初始化目录结构完成")

# 添加CORS中间件（允许前端跨域访问）
# 修改：明确指定允许的源，并添加预检请求处理
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 明确指定前端地址
    allow_credentials=True,                      # 允许带 Cookie/Token
    allow_methods=["*"],                         # 允许所有 HTTP 方法
    allow_headers=["*"],                         # 允许所有请求头
    expose_headers=["*"],                        # 暴露所有响应头
    # max_age=3600, # 可选：设置预检请求缓存时间
)
# AuthMiddleware 放在 CORS 之后
app.add_middleware(AuthMiddleware)

# 注册路由
app.include_router(upload_router)
app.include_router(download_router)
# 注册新的模块化路由
app.include_router(file_browse_router)       # 文件浏览和列表功能
app.include_router(file_operations_router)   # 基本文件操作（删除、重命名、移动、复制、创建目录）
app.include_router(file_search_router)       # 搜索和打包下载
app.include_router(file_trash_router)        # 回收站管理
app.include_router(file_thumbnails_router)   # 缩略图功能


@app.get("/")
async def root():
    """根路径，返回服务状态"""
    return {
        "service": "最小可行网络云盘",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "upload": "/upload/*",
            "download": "/download/{file_id}",
            "files": "/files/*",
            "docs": "/docs",
        },
        "note": "使用Authorization: Bearer <token>头进行认证",
    }


@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "healthy"}


@app.get("/test")
async def test_token(request: Request):
    """测试Token是否正确的接口
    
    从Authorization头提取token并验证，返回验证结果。
    这个路由本身不需要被AuthMiddleware保护，否则没token的用户就测不了了。
    
    注意：目前测试用的token是 'test123'（见auth.py里的verify_token函数）
    """
    # 尝试从请求头提取token
    auth_header = request.headers.get("Authorization")
    
    if not auth_header:
        return {
            "valid": False
        }
    
    # 解析Bearer token
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return {
            "valid": False
        }
    
    token = parts[1]
    
    # 使用auth.py里的验证函数
    is_valid = verify_token(token)
    
    if is_valid:
        return {
            "valid": True
        }
    else:
        return {
            "valid": False
        }


# 启动应用（仅供直接运行，uvicorn会使用此模块）
if __name__ == "__main__":
    import uvicorn
    
    logger.info("启动服务器...")
    logger.info("接口文档：http://localhost:8000/docs")
    logger.info("注意：需设置Authorization头进行测试，测试token: 'test123'")
    
    # 启动参数说明：
    # 后续部署 HTTPS 时：
    # 1. 替换 uvicorn 启动命令为 --ssl-keyfile/--ssl-certfile
    # 2. 前端上传地址改为 https
    uvicorn.run(
        "main:app",
        host="0.0.0.0",  # 监听所有地址
        port=8005,       # 端口
        reload=True,     # 开发模式下自动重载
        log_level="info",
    )
