# 投资日记图片支持（粘贴直插）设计

日期：2026-08-25

## 背景

投资日记编辑器（Tiptap v3.30.3 + `@tiptap/markdown`）当前支持标题/表格/代码块/待办等富文本，但无法插入图片。需求：**图片可直接复制粘贴到笔记中**。

## 现状（探查结论）

- 编辑器：`frontend/src/pages/diary/DiaryEditor.tsx`，无 `@tiptap/extension-image`，工具栏无图片按钮
- 阅读端：`frontend/src/pages/diary/DiaryReader.tsx`，ReactMarkdown + remark-gfm，可渲染 `![](url)`
- 后端：`backend/api/diary.py` 仅 content/title/parent_folder_id 字段，无图片上传/存储
- 存储：SQLite（笔记 content 为 markdown）+ Docker `app_data:/app/data` 卷
- 代理：nginx `location /api/` → `backend:8000`，`/api/` 前缀路径自动透传
- `python-multipart==0.0.9` 已在 requirements.txt，multipart 上传开箱可用

## 方案对比

| 方案 | 说明 | 结论 |
|:--|:--|:--|
| **A（采纳）文件上传磁盘 + URL 引用** | 上传到后端磁盘，markdown 存 `![](/api/diary/images/<uuid>.png)` | markdown 干净、不撑爆 SQLite、标准笔记应用模式；需解决磁盘持久化（复用 `app_data` 卷） |
| B base64 内联 | markdown 存 `![](data:image/png;base64,...)` | 无存储管理，但 SQLite 内容膨胀、列表 API 全量拉 content 变重、markdown 不可读 | 不采纳 |

## 后端设计

### 配置（`backend/config.py`）

- `DIARY_IMAGE_DIR: str = "./uploads/diary"` — 图片存储目录
- `DIARY_IMAGE_MAX_SIZE_MB: int = 10` — 单图大小上限（MB）

### 上传端点（`backend/api/diary.py`）

`POST /api/diary/images`（multipart，字段名 `file`，需登录 `get_current_user`）：

1. 校验 content_type 为 `image/*` 且 ∈ {png, jpeg, gif, webp}；大小 ≤ `DIARY_IMAGE_MAX_SIZE_MB`
2. 目录不存在自动 `mkdir(parents=True, exist_ok=True)`
3. 保存为 `DIARY_IMAGE_DIR/<uuid4().hex>.<ext>`；**ext 由 content_type 映射，不使用用户文件名**（防路径穿越）
4. 返回 `{url: "/api/diary/images/<uuid>.png"}`
5. 非图片类型 / 超限 → 400

### 图片读取（`backend/api/diary.py`）

`GET /api/diary/images/{filename}`（**公开，不依赖登录** —— `<img>` 标签无法携带 Authorization 头）：

1. `Path(filename).name != filename` 时拒绝（单段文件名防路径穿越）
2. 目标文件不存在 → 404
3. 存在 → `FileResponse`

选 FileResponse 路由而非 StaticFiles 挂载的原因：**可测试性**。StaticFiles 在 import 时捕获目录路径，测试 patch `settings.DIARY_IMAGE_DIR` 不生效；路由在请求时读 `settings`，测试可 patch。同时避免 mount 与路由的顺序问题、避免 import 时目录必须存在。

路由冲突检查：日记 router 的 `GET /{diary_id}` 只匹配单段路径，`/api/diary/images/<file>` 为两段，不会冲突；`GET /api/diary/images` 裸路径会落到 `/{diary_id}` → 404「笔记不存在」，无真实使用场景，可接受。

### Docker（`docker-compose.yml`）

app 服务新增环境变量 `DIARY_IMAGE_DIR=/app/data/diary_images`，复用已挂载的 `app_data` 卷 → 容器重建图片不丢。

## 前端设计

### 依赖

- 新增 `@tiptap/extension-image@^3.30.3`（与现有 tiptap 包同版本族）

### 编辑器（`DiaryEditor.tsx`）

1. 注册 `Image` 扩展（`setContent` 解析 `![](url)` 与 `getMarkdown()` 序列化均依赖它）
2. `editorProps.handlePaste`：剪贴板含 `kind==='file' && type.startsWith('image/')` 项时 → `diaryApi.uploadImage(file)` 上传 → `editor.chain().focus().setImage({ src })` 插入 → 返回 true 阻止默认
3. `editorProps.handleDrop`：拖入图片文件走同一 `uploadAndInsert(file)` helper
4. 上传失败 → antd `message.error('图片上传失败')`，不插入
5. 上传为异步，多个图逐个上传插入

### API 客户端（`api/client.ts`）

```ts
uploadImage: (file: File) => {
  const fd = new FormData();
  fd.append('file', file);
  return client.post<ApiResponse<{ url: string }>>('/diary/images', fd);
},
```

**不手动设置 `Content-Type`**（浏览器/axios 自动带 multipart boundary）；axios 拦截器自动带 JWT + `/api` baseURL。

### 样式（`index.css`）

```css
.diary-editor .tiptap img { max-width: 100%; height: auto; border-radius: 6px; }
.diary-reader img { max-width: 100%; height: auto; border-radius: 6px; }
```

### 阅读端（`DiaryReader.tsx`）

内容容器加 `diary-reader` class（ReactMarkdown 已能渲染 `![](url)`，仅需样式约束）。

## 数据流

1. 用户在编辑器 Ctrl+V 复制截图 → `handlePaste` 拦截到图片文件
2. `POST /api/diary/images` 上传 → 返回 `/api/diary/images/<uuid>.png`
3. 编辑器插入图片节点 → onUpdate → `getMarkdown()` 产出 `![](/api/diary/images/<uuid>.png)` → 进 autosave
4. 保存到 SQLite content
5. 阅读端 ReactMarkdown 渲染 `<img>`，浏览器经 nginx `/api/` 代理拉取（`FileResponse`）

## 错误处理

- 非图片类型 / 超 10MB → 后端 400，前端 message 提示
- 上传失败（网络/401）→ 不插入图片，提示重试
- 删除笔记不清理磁盘图片（孤儿文件；个人自用可接受，后续可选 GC）

## 测试（TDD）

`tests/test_api/test_diary_images.py`，`client` fixture + patch `backend.api.diary.settings.DIARY_IMAGE_DIR` 为 `tmp_path`：

1. 上传合法 PNG → 200，返回 `/api/diary/images/<file>`，文件落盘
2. 上传 `text/plain` → 400
3. 上传超限 → 400
4. GET 返回的 URL → 200，字节与上传一致（FileResponse 链路）
5. 未登录上传 → 401

## 不做（YAGNI）

- 图片选择器 / 工具栏图片按钮（需求仅粘贴）
- 图片删除 / 孤儿文件 GC
- 图片鉴权（`<img>` 无法携带 Authorization；平台个人自用）
- 缩略图 / 压缩
