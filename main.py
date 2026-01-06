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

主应用入口
FastAPI应用初始化、中间件设置、路由注册
"""

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import ensure_dirs, LOG_LEVEL, LOG_FORMAT
from auth import AuthMiddleware
from upload import router as upload_router
from download import router as download_router
from file_manager import router as file_manager_router

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
# HACK: 开发环境下允许所有来源，生产环境应限制
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # v2: 应配置为前端域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加Token鉴权中间件
# 注意：这里我们使用了自定义的ASGI中间件
app.add_middleware(AuthMiddleware)

# 注册路由
app.include_router(upload_router)
app.include_router(download_router)
app.include_router(file_manager_router)


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
