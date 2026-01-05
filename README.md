# 最小可行网络云盘 (Minimum Viable Cloud Drive)

一个支持断点续传的简单网络云盘后端服务，使用 FastAPI 构建。

## 功能特性

- ✅ **分片上传**：支持大文件分片上传，每片 ≤ 4MB
- ✅ **断点续传**：上传中断后可从中断处继续
- ✅ **HTTP Range 下载**：支持标准 HTTP Range 头，实现下载续传
- ✅ **Token 鉴权**：保护上传/下载接口
- ✅ **文件管理**：文件列表、信息查询、目录浏览
- ✅ **简易部署**：单文件启动，依赖少
- ✅ **开放协议**：使用 GNU GPL v3 许可证

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动服务

```bash
python main.py
```

服务将在 `http://localhost:8000` 启动，访问 `http://localhost:8000/docs` 查看 API 文档。

### 3. 测试 Token

默认测试 Token 为 `"test123"`，所有请求需包含头：
```
Authorization: Bearer test123
```

**注意**：生产环境必须修改 `auth.py` 中的 `verify_token` 函数！

## API 使用说明

### 文件管理

1. **列出文件/目录**
   ```
   GET /files/?path=<相对路径>&recursive=<true/false>
   Authorization: Bearer <token>
   ```
   - `path`: 可选，相对路径（相对于storage目录）
   - `recursive`: 可选，是否递归列出所有文件
   返回：目录信息或文件列表

2. **获取文件详细信息**
   ```
   GET /files/info/{文件ID或路径}
   Authorization: Bearer <token>
   ```
   支持通过文件SHA256哈希或相对路径查询

3. **获取存储统计**
   ```
   GET /files/stats
   Authorization: Bearer <token>
   ```
   返回存储空间使用情况和文件统计

### 文件上传流程

1. **初始化上传**（获取 upload_id）
   ```
   POST /upload/init
   Authorization: Bearer <token>
   ```
   返回：`{"upload_id": "uuid", "uploaded_chunks": []}`

2. **上传分片**（支持断点续传）
   ```
   POST /upload/chunk?upload_id=<uuid>&index=<0-based-index>
   Authorization: Bearer <token>
   Content-Type: multipart/form-data
   ```
   分片文件字段名：`file`

3. **完成上传**（合并分片）
   ```
   POST /upload/finish?upload_id=<uuid>&filename=<name>&total_chunks=<N>
   Authorization: Bearer <token>
   ```
   返回：`{"file_id": "sha256", "filename": "...", "size": 1234}`

### 文件下载

1. **完整下载**
   ```
   GET /download/{file_id}
   Authorization: Bearer <token>
   ```

2. **断点续传下载**
   ```
   GET /download/{file_id}
   Authorization: Bearer <token>
   Range: bytes=0-999
   ```
   支持单区间 Range 请求，返回 `206 Partial Content`

## 项目结构

```
.
├── main.py              # FastAPI 应用入口
├── auth.py              # Token 鉴权中间件
├── upload.py            # 文件上传逻辑
├── download.py          # 文件下载逻辑（支持 Range）
├── file_manager.py      # 文件管理逻辑（列表、信息、统计）
├── config.py            # 配置管理
├── requirements.txt     # Python 依赖
├── uploads/             # 临时上传目录（运行时创建）
└── storage/             # 最终文件存储（运行时创建）
```

## 配置说明

- **分片大小**：4MB（`config.py` 中 `CHUNK_SIZE`）
- **存储目录**：`./storage/`（最终文件）、`./uploads/`（临时分片）
- **Token 验证**：默认硬编码 `"test123"`，需在生产环境中替换

## 部署 HTTPS

1. 生成 SSL 证书（或使用 Let's Encrypt）
2. 修改启动命令：
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 443 \
     --ssl-keyfile /path/to/key.pem \
     --ssl-certfile /path/to/cert.pem
   ```
3. 前端将上传地址改为 `https://`

## 已知限制与改进方向

### 当前限制（v1）
- 内存存储上传状态（重启后丢失）
- 仅支持单区间 Range 下载
- 硬编码 Token 验证（仅供测试）

### 计划改进（v2+）
- [ ] 使用 Redis 持久化上传状态
- [ ] 支持多区间 Range 请求
- [ ] 添加 JWT Token 支持
- [ ] 文件分片校验（MD5/SHA1）
- [ ] 上传/下载进度 WebSocket 推送
- [ ] 文件预览（图片、PDF等）
- [ ] 用户配额限制
- [ ] 文件搜索功能（按名称、类型、大小等）
- [ ] 文件元数据管理（标签、描述等）

## 开发说明

### 代码风格
- 简洁优先，避免过度抽象
- 关键路径有详细日志
- 标注临时方案（`# HACK`、`# FIXME`）
- 渐进式改进，保留版本痕迹（`# v1`、`# v2`）

### 测试 Token
- 开发环境：使用 `"test123"`
- 生产环境：必须实现自己的 `verify_token` 逻辑

## 许可证

GNU General Public License v3.0 (GPL-3.0)

```
Copyright (C) 2026 Jiale Xu (ANTmmmmm) <https://github.com/ant-cave>
Copyright (C) 2026 Xinhang Chen <https://github.com/cxh09>
```

本项目是自由软件：您可以重新发布和/或修改它，但需遵守 GNU 通用公共许可证的条款。

## 贡献

欢迎提交 Issue 和 Pull Request！特别是：

1. 更好的错误提示
2. 跨平台路径处理优化
3. 单元测试补充
4. 性能优化（大文件处理）

## 故障排除

### 常见问题

1. **Token 无效**：检查 `Authorization: Bearer test123` 头格式
2. **文件找不到**：确认文件已成功上传并完成合并
3. **分片大小超限**：每片需 ≤ 4MB（前端控制）
4. **跨域问题**：开发环境已配置 CORS，生产环境需限制域名

### 日志查看
- 日志级别：INFO（可在 `config.py` 调整）
- 关键操作都有日志记录（上传、下载、合并等）

---

**提示**：首次使用建议先通过 `/docs` 接口文档进行测试！
