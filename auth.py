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
import json
from typing import Optional, Tuple
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Scope, Receive, Send

# 导入用户认证模块
# 注意：这里直接导入，因为user_auth.py在同一目录下
# 如果导入失败，说明路径有问题，需要检查项目结构
from user_auth import verify_totp

logger = logging.getLogger(__name__)




class AuthMiddleware:
    """TOTP鉴权中间件（重构版）
    
    新的认证格式：请求头包含 {"Id": uuid, "Totp": totp}
    验证逻辑：根据uuid找到对应的TOTP密钥，验证totp码
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
            
            # 从请求头提取UUID和TOTP码
            auth_result = self._extract_auth_info(request)
            
            if not auth_result:
                # 提取认证信息失败
                await self._unauthorized_response(scope, receive, send)
                logger.warning(f"认证信息提取失败: {path}")
                return
            
            uuid_str, totp_code = auth_result
            
            # 验证TOTP码
            if not verify_totp(uuid_str, totp_code):
                await self._unauthorized_response(scope, receive, send)
                logger.warning(f"TOTP验证失败: {path}, uuid={uuid_str}")
                return
            
            # 验证通过，把UUID存到请求状态里，后面路径处理要用
            # 这里需要将UUID存储到request.state中，这样路由函数才能访问
            # 但是我们现在在中间件里，request是在这里创建的，需要让后续的中间件和路由能访问到
            # Starlette/FastAPI中，我们可以通过scope来传递数据
            scope.setdefault('state', {})['user_uuid'] = uuid_str
            logger.debug(f"认证通过: uuid={uuid_str}, path={path}")
        
        await self.app(scope, receive, send)
    
    def _extract_auth_info(self, request: Request) -> Optional[Tuple[str, str]]:
        """从请求头提取UUID和TOTP码
        
        支持的格式：
        1. 自定义头：Id: uuid, Totp: totp
        2. JSON格式的Authorization头：{"Id": uuid, "Totp": totp}
        """
        # 首选：直接读取自定义头（更简洁）
        uuid_str = request.headers.get("Id")
        totp_code = request.headers.get("Totp")
        
        if uuid_str and totp_code:
            return str(uuid_str), str(totp_code)
        
        # 备选：尝试从Authorization头提取JSON格式
        auth_header = request.headers.get("Authorization")
        if auth_header:
            try:
                # 去掉可能的Bearer前缀
                if auth_header.startswith("Bearer "):
                    auth_json_str = auth_header[7:]  # 去掉"Bearer "
                else:
                    auth_json_str = auth_header
                
                auth_data = json.loads(auth_json_str)
                uuid_str = auth_data.get("Id")
                totp_code = auth_data.get("Totp")
                
                if uuid_str and totp_code:
                    return str(uuid_str), str(totp_code)
            except json.JSONDecodeError:
                logger.debug("Authorization头不是有效的JSON格式")
            except Exception as e:
                logger.warning(f"解析认证头失败: {e}")
        
        # 提取失败
        logger.debug("无法从请求头提取认证信息")
        return None
    
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
