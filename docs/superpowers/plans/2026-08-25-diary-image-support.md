# 投资日记图片支持（粘贴直插）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让投资日记编辑器支持图片——复制/拖入图片自动上传到后端磁盘，markdown 中以 `![](/api/diary/images/<uuid>.<ext>)` 引用，阅读端正常渲染。

**Architecture:** 前端 Tiptap 编辑器拦截粘贴/拖放图片文件 → `POST /api/diary/images` 上传 → 返回 URL → 插入 Image 节点 → markdown 自动保存。后端 FastAPI 新增上传端点（需登录、校验类型/大小）+ 读取端点（公开 FileResponse，防路径穿越），图片存磁盘（Docker 复用 `app_data` 卷）。

**Tech Stack:** Tiptap v3.30.3（`@tiptap/extension-image` 新增）、React 19、axios、FastAPI 0.111、python-multipart（已装）、pytest。

## Global Constraints

- Tiptap 各包版本族统一 `^3.30.3`（新增 `@tiptap/extension-image@^3.30.3`）
- `python-multipart` 已在 requirements.txt，**不要重复添加**
- 图片内容类型白名单：`image/png` / `image/jpeg` / `image/gif` / `image/webp`
- 上传需登录（`get_current_user`）；**读取公开**（`<img>` 标签无法携带 Authorization）
- 文件名由 `uuid4().hex + 白名单扩展名` 生成，**绝不使用用户文件名**（防路径穿越）
- 完成标准：`pytest tests/ -v` 全通过 + `cd frontend && npm run build && npm run lint` 通过
- 提交信息沿用项目风格 `feat(diary): ...` / `test(diary): ...`

---

### Task 1: 后端配置 + 图片上传端点（TDD）

**Files:**
- Modify: `backend/config.py:49`（CHAT_PERSONA_PATH 之后新增两组配置）
- Modify: `backend/api/diary.py:1-12`（新增 imports）+ 在 `_folder_dict` 之后新增 `POST /images`
- Test: `tests/test_api/test_diary_images.py`（新建，仅上传用例）

**Interfaces:**
- Produces: 配置 `settings.DIARY_IMAGE_DIR: str`（默认 `"./uploads/diary"`）、`settings.DIARY_IMAGE_MAX_SIZE_MB: int`（默认 `10`）
- Produces: `POST /api/diary/images`（multipart 字段 `file`，需登录）→ 成功 `200 {data:{url: "/api/diary/images/<uuid>.<ext>"}}`，非图片/超限 `400`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_api/test_diary_images.py`：

```python
# tests/test_api/test_diary_images.py
"""Diary 图片上传 API 测试 — TDD"""
import base64

import pytest
from unittest.mock import patch

from tests.test_api.test_chat import _register_and_login


def _png_bytes() -> bytes:
    # 1x1 透明 PNG
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )


class TestDiaryImageUpload:
    @pytest.mark.asyncio
    async def test_upload_valid_png(self, client, tmp_path):
        token = await _register_and_login(client, "img@example.com")
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
            resp = await client.post(
                "/api/diary/images",
                files={"file": ("shot.png", _png_bytes(), "image/png")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        url = resp.json()["data"]["url"]
        assert url.startswith("/api/diary/images/")
        assert url.endswith(".png")
        assert (tmp_path / url.rsplit("/", 1)[-1]).read_bytes() == _png_bytes()

    @pytest.mark.asyncio
    async def test_upload_rejects_non_image(self, client, tmp_path):
        token = await _register_and_login(client, "img2@example.com")
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
            resp = await client.post(
                "/api/diary/images",
                files={"file": ("note.txt", b"hello", "text/plain")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_rejects_oversize(self, client, tmp_path):
        token = await _register_and_login(client, "img3@example.com")
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)), \
             patch("backend.api.diary.settings.DIARY_IMAGE_MAX_SIZE_MB", 0):
            resp = await client.post(
                "/api/diary/images",
                files={"file": ("big.png", _png_bytes(), "image/png")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_requires_auth(self, client, tmp_path):
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
            resp = await client.post(
                "/api/diary/images",
                files={"file": ("a.png", _png_bytes(), "image/png")},
            )
        assert resp.status_code in (401, 403)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_api/test_diary_images.py -v`

Expected: FAIL —— `404`（路由不存在）或 `assert` 失败。未实现前必然红。

- [ ] **Step 3: 实现配置 + 上传端点**

`backend/config.py`，在 `CHAT_PERSONA_PATH` 一行后新增：

```python
    # 投资日记图片
    DIARY_IMAGE_DIR: str = "./uploads/diary"      # 图片存储目录
    DIARY_IMAGE_MAX_SIZE_MB: int = 10             # 单图大小上限（MB）
```

`backend/api/diary.py` 顶部 imports 改为：

```python
# stock-monitor/backend/api/diary.py
"""投资笔记 API — CRUD + 文件夹树 + 图片"""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.config import settings
from backend.models.user import User
from backend.schemas.common import ApiResponse
from backend.services.diary_svc import DiaryService
```

`backend/api/diary.py`，在 `_folder_dict` 函数（原 39 行）之后、`@router.post("")` 之前新增：

```python
_IMAGE_EXTS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}


@router.post("/images", response_model=ApiResponse)
async def upload_diary_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """上传投资笔记图片 → 返回可引用的 URL（markdown 中存 ![](url)）。"""
    ext = _IMAGE_EXTS.get(file.content_type or "")
    if ext is None:
        raise HTTPException(status_code=400, detail="仅支持 PNG/JPEG/GIF/WebP 图片")
    data = await file.read()
    if len(data) > settings.DIARY_IMAGE_MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400,
                            detail=f"图片超过 {settings.DIARY_IMAGE_MAX_SIZE_MB}MB 上限")
    img_dir = Path(settings.DIARY_IMAGE_DIR)
    img_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{ext}"
    (img_dir / filename).write_bytes(data)
    return ApiResponse(data={"url": f"/api/diary/images/{filename}"})
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_api/test_diary_images.py -v`

Expected: 4 个用例 PASS（此时只含上传用例，GET 用例在 Task 2 追加）。

- [ ] **Step 5: 提交**

```bash
git add backend/config.py backend/api/diary.py tests/test_api/test_diary_images.py
git commit -m "feat(diary): 图片上传端点 + 配置（TDD）"
```

---

### Task 2: 后端图片读取端点（TDD）

**Files:**
- Modify: `backend/api/diary.py`（`POST /images` 之后新增 `GET /images/{filename}`）
- Test: `tests/test_api/test_diary_images.py`（追加 GET 用例）

**Interfaces:**
- Consumes: Task 1 的 `settings.DIARY_IMAGE_DIR`
- Produces: `GET /api/diary/images/{filename}`（公开，无鉴权）→ `200 FileResponse`；文件名含路径分隔/文件不存在 → `404`

- [ ] **Step 1: 追加失败测试**

`tests/test_api/test_diary_images.py` 文件末尾追加：

```python
class TestDiaryImageGet:
    @pytest.mark.asyncio
    async def test_get_served_image(self, client, tmp_path):
        token = await _register_and_login(client, "img4@example.com")
        data = _png_bytes()
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
            up = await client.post(
                "/api/diary/images",
                files={"file": ("shot.png", data, "image/png")},
                headers={"Authorization": f"Bearer {token}"},
            )
            url = up.json()["data"]["url"]
            resp = await client.get(url)
        assert resp.status_code == 200
        assert resp.content == data
        assert resp.headers["content-type"].startswith("image/")

    @pytest.mark.asyncio
    async def test_get_missing_404(self, tmp_path):
        from backend.api.diary import get_diary_image
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
            with pytest.raises(HTTPException) as ei:
                await get_diary_image("missing.png")
        assert ei.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_traversal_rejected(self, tmp_path):
        from backend.api.diary import get_diary_image
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
            with pytest.raises(HTTPException) as ei:
                await get_diary_image("../secret.txt")
        assert ei.value.status_code == 404
```

补顶部 imports：`from fastapi import HTTPException`。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_api/test_diary_images.py -v`

Expected: 上传用例 PASS，GET 用例 FAIL（`get_diary_image` 不存在 / 404 路由不存在）。

- [ ] **Step 3: 实现读取端点**

`backend/api/diary.py`，在 `upload_diary_image` 函数之后新增：

```python
@router.get("/images/{filename}")
async def get_diary_image(filename: str):
    """公开读取已上传的笔记图片（<img> 无法携带 Authorization，故不鉴权）。"""
    if Path(filename).name != filename:
        raise HTTPException(status_code=404, detail="not found")
    img_path = Path(settings.DIARY_IMAGE_DIR) / filename
    if not img_path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(img_path)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_api/test_diary_images.py -v`

Expected: 7 个用例全 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/api/diary.py tests/test_api/test_diary_images.py
git commit -m "feat(diary): 图片读取端点（FileResponse，防路径穿越）"
```

---

### Task 3: Docker 图片目录挂载

**Files:**
- Modify: `docker-compose.yml`（app 服务 environment）

**Interfaces:**
- Consumes: `settings.DIARY_IMAGE_DIR` 约定
- Produces: 生产/开发容器内图片目录指向已持久化的 `app_data` 卷

- [ ] **Step 1: 加环境变量**

`docker-compose.yml` app 服务 `environment:` 块（DSH_CALC_URL 行后）新增：

```yaml
      # 投资日记图片目录：复用 app_data 卷，容器重建图片不丢
      - DIARY_IMAGE_DIR=${DIARY_IMAGE_DIR:-/app/data/diary_images}
```

- [ ] **Step 2: 提交**

```bash
git add docker-compose.yml
git commit -m "chore(docker): 日记图片目录指向 app_data 卷"
```

---

### Task 4: 前端 API 客户端 uploadImage

**Files:**
- Modify: `frontend/src/api/client.ts:124-140`（diaryApi 对象）

**Interfaces:**
- Produces: `diaryApi.uploadImage(file: File) → Promise<AxiosResponse<ApiResponse<{url: string}>>>`

- [ ] **Step 1: 实现 uploadImage**

`frontend/src/api/client.ts` 的 `diaryApi` 对象内，`remove` 之后新增：

```ts
  uploadImage: (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return client.post<ApiResponse<{ url: string }>>('/diary/images', fd);
  },
```

**不手动设置 `Content-Type`**（axios 对 FormData 自动带 multipart boundary）。

- [ ] **Step 2: 验证类型/构建**

Run: `cd frontend && npm run build`

Expected: tsc + vite build 成功，无类型错误。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/api/client.ts
git commit -m "feat(diary): 前端 uploadImage API"
```

---

### Task 5: 编辑器图片扩展 + 粘贴/拖放上传

**Files:**
- Modify: `frontend/package.json`（新增依赖）
- Modify: `frontend/src/pages/diary/DiaryEditor.tsx`

**Interfaces:**
- Consumes: Task 4 的 `diaryApi.uploadImage`
- Produces: 编辑器支持粘贴/拖放图片 → 上传 → 插入图片节点，`getMarkdown()` 产出 `![](url)`

- [ ] **Step 1: 安装依赖**

Run: `cd frontend && npm install @tiptap/extension-image@^3.30.3`

Expected: package.json 新增 `"@tiptap/extension-image": "^3.30.3"`。

- [ ] **Step 2: 实现编辑器**

`frontend/src/pages/diary/DiaryEditor.tsx` 全部改动：

imports 区（第 1-15 行）调整：

```tsx
import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { Tooltip, message as antMsg } from 'antd';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Underline from '@tiptap/extension-underline';
import Link from '@tiptap/extension-link';
import Image from '@tiptap/extension-image';
import { Table } from '@tiptap/extension-table';
import TableRow from '@tiptap/extension-table-row';
import TableCell from '@tiptap/extension-table-cell';
import TableHeader from '@tiptap/extension-table-header';
import TaskList from '@tiptap/extension-task-list';
import TaskItem from '@tiptap/extension-task-item';
import Placeholder from '@tiptap/extension-placeholder';
import { Markdown } from '@tiptap/markdown';
import { diaryApi } from '@/api/client';
```

组件内 `const editor = useEditor({...})` 之前新增 `insertImage` helper：

```tsx
  /** 上传图片并插入编辑器；失败不插入，仅提示 */
  const insertImage = async (file: File) => {
    try {
      const res = await diaryApi.uploadImage(file);
      const url = res.data.data.url;
      editor?.chain().focus().setImage({ src: url }).run();
    } catch {
      antMsg.error('图片上传失败');
    }
  };
```

`useEditor` 调用改为：

```tsx
  const editor = useEditor({
    extensions: [
      StarterKit,
      Underline,
      Link.configure({ openOnClick: false }),
      Image,
      Table.configure({ resizable: true }),
      TableRow,
      TableHeader,
      TableCell,
      TaskList,
      TaskItem.configure({ nested: true }),
      Placeholder.configure({ placeholder: '写下你的投资思考…' }),
      Markdown,
    ],
    content: initialMarkdown,
    contentType: 'markdown',
    onUpdate: ({ editor }) => onChange(editor.getMarkdown()),
    editorProps: {
      // 粘贴图片文件 → 上传插入；返回 true 阻止默认粘贴行为
      handlePaste: (_view, event) => {
        const items = Array.from(event.clipboardData?.items ?? []);
        const images = items.filter((i) => i.kind === 'file' && i.type.startsWith('image/'));
        if (images.length === 0) return false;
        images.forEach((item) => {
          const file = item.getAsFile();
          if (file) void insertImage(file);
        });
        return true;
      },
      // 拖入图片文件 → 同一上传插入路径
      handleDrop: (_view, event, _slice, moved) => {
        if (moved) return false;
        const files = Array.from(event.dataTransfer?.files ?? []);
        const images = files.filter((f) => f.type.startsWith('image/'));
        if (images.length === 0) return false;
        event.preventDefault();
        images.forEach((f) => void insertImage(f));
        return true;
      },
    },
  });
```

- [ ] **Step 3: 验证构建 + lint**

Run: `cd frontend && npm run build && npm run lint`

Expected: tsc + vite build 通过，oxlint 无错误。

- [ ] **Step 4: 提交**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/pages/diary/DiaryEditor.tsx
git commit -m "feat(diary): 编辑器图片粘贴/拖放上传"
```

---

### Task 6: 图片样式 + 阅读端 class

**Files:**
- Modify: `frontend/src/index.css`（末尾新增图片样式）
- Modify: `frontend/src/pages/diary/DiaryReader.tsx:24`（内容容器加 class）

**Interfaces:**
- Consumes: Task 5 生成的 `![](url)` markdown
- Produces: 编辑器/阅读端图片自适应宽度、圆角

- [ ] **Step 1: 加样式**

`frontend/src/index.css` 末尾追加：

```css
/* 投资日记图片：自适应宽度，不溢出 */
.diary-editor .tiptap img { max-width: 100%; height: auto; border-radius: 6px; }
.diary-reader img { max-width: 100%; height: auto; border-radius: 6px; }
```

- [ ] **Step 2: 阅读端容器加 class**

`frontend/src/pages/diary/DiaryReader.tsx` 第 24 行内容容器：

```tsx
      <div className="diary-reader" style={{ fontSize: 15.5, lineHeight: 2, color: '#2A2A2A' }}>
```

- [ ] **Step 3: 验证构建**

Run: `cd frontend && npm run build`

Expected: 构建通过。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/index.css frontend/src/pages/diary/DiaryReader.tsx
git commit -m "style(diary): 图片样式 + 阅读端渲染容器 class"
```

---

### Task 7: 全量回归验证

**Files:** 无改动

- [ ] **Step 1: 后端全量测试**

Run: `pytest tests/ -v`

Expected: 全部 PASS（含新增图片用例；应为 451 + 7 = 458 用例，实际以输出为准，必须 0 failed）。

- [ ] **Step 2: 前端构建 + lint**

Run: `cd frontend && npm run build && npm run lint`

Expected: 均通过，无错误。
