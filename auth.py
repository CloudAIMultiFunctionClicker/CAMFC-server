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
"""

import logging
from typing import Optional
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Scope, Receive, Send

logger = logging.getLogger(__name__)


def verify_token(token: str) -> bool:
    """验证Token有效性
    
    Args:
        token: 从Authorization头提取的Token字符串
        
    Returns:
        bool: Token是否有效
        
    【用户自定义区】——你后续在此填入动态验证逻辑（如查DB/Redis/JWT解码）
    示例：return token == "test123" 仅用于测试！
    """
    if token == "test123":
        return True
    
    logger.warning(f"Token验证失败: {token[:10]}...")
    return False


class AuthMiddleware:
    """Token鉴权中间件
    
    所有请求需包含 Authorization: Bearer <token> 头
    验证失败返回401，不暴露具体原因
    """
    
    def __init__(self, app: ASGIApp):
        self.app = app
        
    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        # 只处理HTTP请求
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 跳过 OPTIONS 请求（CORS 预检）
        if scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return
            
        request = Request(scope, receive)
        path = request.url.path
        
        # 仅对特定路径启用鉴权
        if (path.startswith("/upload") or 
            path.startswith("/download") or 
            path.startswith("/files")):
            
            token = self._extract_token(request)
            if not token or not verify_token(token):
                await self._unauthorized_response(scope, receive, send)
                logger.warning(f"未授权访问: {path}")
                return
        
        await self.app(scope, receive, send)
    
    def _extract_token(self, request: Request) -> Optional[str]:
        """从请求头提取Token
        
        支持格式：Authorization: Bearer <token>
        """
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return None
            
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None
            
        return parts[1]
    
    async def _unauthorized_response(self, scope: Scope, receive: Receive, send: Send):
        """返回401未授权响应"""
        response = JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized"}
        )
        await response(scope, receive, send)


def add_auth_middleware(app):
    """为FastAPI应用添加鉴权中间件（兼容用法）"""
    return AuthMiddleware(app)