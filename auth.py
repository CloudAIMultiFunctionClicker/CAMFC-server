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

鉴权模块
提供Token验证中间件，保护上传/下载接口
"""

import logging
from typing import Optional, Callable
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse

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
    # HACK: 测试用硬编码Token，生产环境必须替换！
    # 简单实现：检查token是否为"test123"
    # v1: 硬编码验证（仅用于开发测试）
    # v2: 可扩展为从数据库查询、验证JWT签名、检查Redis缓存等
    if token == "test123":
        return True
    
    # FIXME: 实现真正的Token验证逻辑
    # 例如：
    # 1. 查询数据库验证token有效性
    # 2. 验证JWT签名和过期时间
    # 3. 检查Redis中的会话状态
    # 4. 调用外部认证服务
    
    # 临时实现：返回False表示无效
    logger.warning(f"Token验证失败: {token[:10]}...")
    return False


class AuthMiddleware:
    """Token鉴权中间件
    
    所有请求需包含 Authorization: Bearer <token> 头
    验证失败返回401，不暴露具体原因
    """
    
    def __init__(self, app: FastAPI):
        self.app = app
        
    async def __call__(self, scope, receive, send):
        # 只处理HTTP请求
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
            
        # 创建FastAPI请求对象
        request = Request(scope, receive)
        
        # 检查是否需要鉴权
        path = request.url.path
        if path.startswith("/upload") or path.startswith("/download"):
            # 需要鉴权的接口
            token = self._extract_token(request)
            if not token:
                # Token缺失，返回401
                await self._unauthorized_response(scope, receive, send)
                return
                
            if not verify_token(token):
                # Token无效，返回401
                await self._unauthorized_response(scope, receive, send)
                return
        
        # 鉴权通过，继续处理请求
        await self.app(scope, receive, send)
    
    def _extract_token(self, request: Request) -> Optional[str]:
        """从请求头提取Token
        
        支持格式：Authorization: Bearer <token>
        """
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return None
            
        # 检查Bearer格式
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None
            
        return parts[1]
    
    async def _unauthorized_response(self, scope, receive, send):
        """返回401未授权响应"""
        response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Unauthorized"}
        )
        await response(scope, receive, send)
        logger.warning(f"未授权访问: {scope.get('path', 'unknown')}")


def add_auth_middleware(app: FastAPI):
    """为FastAPI应用添加鉴权中间件"""
    # 创建中间件实例
    auth_middleware = AuthMiddleware(app)
    
    # 使用ASGI中间件包装应用
    # 注意：这里我们返回包装后的应用
    # 在实际使用中，中间件会在main.py中通过app.add_middleware添加
    return auth_middleware


# v2: 可考虑支持多种鉴权方式（如API Key、JWT、OAuth2）
# v3: 添加权限分级（如只读token、上传token、管理token）
