# 忘记密码 / 重置密码 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增「忘记密码 / 重置密码」功能：用户通过邮箱验证码重置密码。

**Architecture:** 完全复用现有「邮箱验证码」基建（Redis 存码 5 分钟过期 + 60s 限频 + 邮件/控制台发码）。新增 2 个后端端点 + 1 个前端弹窗组件，登录页加「忘记密码？」入口。

**Tech Stack:** FastAPI / SQLAlchemy(async) / Redis / bcrypt / React 19 / Ant Design 5 / TypeScript

## Global Constraints

- 验证码用途字符串统一为 `reset_password`（与 `register`、`login` 区分）。
- 重置发码端点请求体为 `{email}`，**端点内部硬编码 `purpose="reset_password"`**；不复用 `SendCodeRequest`（其 `purpose` 默认 `"register"` 会存错 Redis 键），因此**不改 `SendCodeRequest.purpose` 正则**。
- 邮箱未注册发码 → 409「该邮箱未注册，请先注册」；限频 → 429「发送过于频繁，请稍后再试」；验证码错误/过期 → 400「验证码错误或已过期」。
- 新密码校验规则与注册一致：`min_length=6, max_length=128`。
- 重置后不强制旧 JWT 失效（token 无版本机制，24h 过期，已知限制）。
- 前端错误提示统一走 `getErrorMessage`（从 axios error 提取后端 detail）。

---

### Task 1: 后端忘记密码（Schema + Service + Email + API）

**Files:**
- Test: `tests/test_api/test_auth.py`
- Modify: `backend/schemas/user.py`
- Modify: `backend/services/email_svc.py:20-23`
- Modify: `backend/services/auth_svc.py`（新增 `reset_password` 方法）
- Modify: `backend/api/auth.py`

**Interfaces:**
- Consumes: `AuthService.verify_code(email, purpose, code)`、`AuthService.hash_password`、`AuthService.save_verify_code`、`AuthService.check_rate_limit`、`AuthService.get_user_by_email`、`EmailService.generate_code()`、`EmailService.send_verify_code(email, code, purpose)`（均已存在）
- Produces:
  - `AuthService.reset_password(db, email, code, new_password) -> User | None`
  - Schema `ResetSendCodeRequest(BaseModel): email: EmailStr`
  - Schema `ResetPasswordRequest(BaseModel): email, code, new_password`
  - 端点 `POST /api/auth/password/send-code`（body `{email}`）
  - 端点 `POST /api/auth/password/reset`（body `{email, code, new_password}`）

- [ ] **Step 1: 写失败测试**

在 `tests/test_api/test_auth.py` 文件末尾（`TestAuth` 类内）追加 5 个用例：

```python
    @pytest.mark.asyncio
    async def test_send_reset_code(self, client, mock_redis):
        """已注册邮箱发送重置验证码"""
        await _register_user(client, "reset1@example.com", "oldpass123")
        resp = await client.post("/api/auth/password/send-code", json={
            "email": "reset1@example.com",
        })
        assert resp.status_code == 200
        assert resp.json()["message"] == "验证码已发送"

    @pytest.mark.asyncio
    async def test_send_reset_code_unregistered(self, client, mock_redis):
        """未注册邮箱发送重置验证码 → 409"""
        resp = await client.post("/api/auth/password/send-code", json={
            "email": "nobody@example.com",
        })
        assert resp.status_code == 409
        assert resp.json()["detail"] == "该邮箱未注册，请先注册"

    @pytest.mark.asyncio
    async def test_reset_password(self, client, mock_redis):
        """重置密码后旧密码失效、新密码可登录"""
        await _register_user(client, "reset2@example.com", "oldpass123")
        resp = await client.post("/api/auth/password/reset", json={
            "email": "reset2@example.com",
            "code": "000000",
            "new_password": "newpass456",
        })
        assert resp.status_code == 200
        assert resp.json()["message"] == "密码重置成功"
        # 旧密码登录失败
        old = await client.post("/api/auth/login", json={
            "email": "reset2@example.com",
            "password": "oldpass123",
        })
        assert old.status_code == 401
        # 新密码登录成功
        new = await client.post("/api/auth/login", json={
            "email": "reset2@example.com",
            "password": "newpass456",
        })
        assert new.status_code == 200

    @pytest.mark.asyncio
    async def test_reset_password_wrong_code(self, client, mock_redis):
        """验证码错误 → 400"""
        await _register_user(client, "reset3@example.com", "oldpass123")
        resp = await client.post("/api/auth/password/reset", json={
            "email": "reset3@example.com",
            "code": "999999",
            "new_password": "newpass456",
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_reset_send_code_rate_limit(self, client, mock_redis):
        """重置验证码发送限频 → 429"""
        from unittest.mock import AsyncMock
        await _register_user(client, "reset4@example.com", "oldpass123")
        mock_redis.exists = AsyncMock(return_value=1)  # 注册完成后再开限频
        resp = await client.post("/api/auth/password/send-code", json={
            "email": "reset4@example.com",
        })
        assert resp.status_code == 429
```

> 注：`mock_redis.exists` 默认返回 0，限频测试需在注册完成后覆盖为 1。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd D:/project/github/stock-monitor && python -m pytest tests/test_api/test_auth.py -v 2>&1 | tail -30`
Expected: 5 个新用例 FAIL（`/api/auth/password/send-code`、`/api/auth/password/reset` 返回 404），原有用例 PASS。

- [ ] **Step 3: 添加 Schema**

`backend/schemas/user.py` 文件末尾追加：

```python
class ResetSendCodeRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=6, max_length=128)
```

- [ ] **Step 4: 扩展 EmailService 用途文案**

`backend/services/email_svc.py` 中 `send_verify_code` 内，把：

```python
        purpose_text = "注册" if purpose == "register" else "登录"
```

改为：

```python
        _PURPOSE_TEXT = {"register": "注册", "login": "登录", "reset_password": "重置密码"}
        # ...（_PURPOSE_TEXT 放在 send_verify_code 方法外、类内作为常量更佳）
        purpose_text = {"register": "注册", "login": "登录", "reset_password": "重置密码"}.get(purpose, "操作")
```

- [ ] **Step 5: AuthService 新增 `reset_password`**

`backend/services/auth_svc.py` 中 `get_user_by_id` 方法之后追加：

```python
    @staticmethod
    async def reset_password(db: AsyncSession, email: str, code: str, new_password: str) -> User | None:
        """验证码 + 新密码重置。验证码不过或邮箱不存在返回 None。"""
        if not await AuthService.verify_code(email, "reset_password", code):
            return None
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            return None
        user.password_hash = AuthService.hash_password(new_password)
        await db.commit()
        await db.refresh(user)
        return user
```

- [ ] **Step 6: 添加 2 个 API 端点**

`backend/api/auth.py`：
1. 在 import 列表（`from backend.schemas.user import (...)`）中追加 `ResetPasswordRequest` 和 `ResetSendCodeRequest`。
2. 在 `get_me` 端点之前追加：

```python
@router.post("/password/send-code")
async def password_send_code(req: ResetSendCodeRequest, db: AsyncSession = Depends(get_db)):
    """发送重置密码验证码"""
    if not await AuthService.get_user_by_email(db, req.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱未注册，请先注册")
    if not await AuthService.check_rate_limit(req.email, "reset_password"):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="发送过于频繁，请稍后再试")

    code = EmailService.generate_code()
    await AuthService.save_verify_code(req.email, "reset_password", code)
    await EmailService.send_verify_code(req.email, code, "reset_password")
    return ApiResponse(message="验证码已发送")


@router.post("/password/reset", response_model=ApiResponse)
async def password_reset(req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """验证码 + 新密码重置密码"""
    user = await AuthService.reset_password(db, req.email, req.code, req.new_password)
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误或已过期")
    return ApiResponse(message="密码重置成功")
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd D:/project/github/stock-monitor && python -m pytest tests/test_api/test_auth.py -v 2>&1 | tail -30`
Expected: 全部 PASS（原有用例 + 5 个新用例）。

- [ ] **Step 8: 提交**

```bash
cd D:/project/github/stock-monitor
git add backend/schemas/user.py backend/services/email_svc.py backend/services/auth_svc.py backend/api/auth.py tests/test_api/test_auth.py
git commit -m "feat: 忘记密码/重置密码后端 — 验证码式重置接口 + 测试

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 前端 API 方法 + 共享错误工具

**Files:**
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/utils/error.ts`

**Interfaces:**
- Consumes: 无（独立）
- Produces:
  - `authApi.sendResetCode(email: string) => Promise<AxiosResponse<ApiResponse>>`
  - `authApi.resetPassword(email: string, code: string, newPassword: string) => Promise<AxiosResponse<ApiResponse>>`
  - `getErrorMessage(err: unknown, fallback: string) => string`（`frontend/src/utils/error.ts`）

- [ ] **Step 1: 创建共享错误工具**

Create `frontend/src/utils/error.ts`：

```typescript
// 从 axios 错误中提取后端具体错误信息（FastAPI HTTPException 的 detail / 校验错误的 msg）
export function getErrorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string };
    if (first?.msg) return first.msg;
  }
  return fallback;
}
```

- [ ] **Step 2: client.ts 添加重置密码 API**

`frontend/src/api/client.ts` 的 `authApi` 对象内（`login` 方法之后）追加：

```typescript
  sendResetCode: (email: string) =>
    client.post<ApiResponse>('/auth/password/send-code', { email }),
  resetPassword: (email: string, code: string, newPassword: string) =>
    client.post<ApiResponse>('/auth/password/reset', { email, code, new_password: newPassword }),
```

- [ ] **Step 3: 构建验证**

Run: `cd D:/project/github/stock-monitor/frontend && npm run build`
Expected: `tsc -b && vite build` 成功，无类型错误。

- [ ] **Step 4: 提交**

```bash
cd D:/project/github/stock-monitor
git add frontend/src/api/client.ts frontend/src/utils/error.ts
git commit -m "feat: 前端重置密码 API 方法 + 共享 getErrorMessage 工具

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: ForgotPasswordModal 弹窗组件

**Files:**
- Create: `frontend/src/components/ForgotPasswordModal.tsx`

**Interfaces:**
- Consumes: `authApi.sendResetCode`、`authApi.resetPassword`（Task 2）、`getErrorMessage`（Task 2）
- Produces: `ForgotPasswordModal({ open: boolean, onClose: () => void })`

- [ ] **Step 1: 创建组件**

Create `frontend/src/components/ForgotPasswordModal.tsx`：

```tsx
import { useState } from 'react';
import { Button, Form, Input, Modal, message } from 'antd';
import { LockOutlined, MailOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import { authApi } from '@/api/client';
import { getErrorMessage } from '@/utils/error';

interface ForgotPasswordModalProps {
  open: boolean;
  onClose: () => void;
}

export function ForgotPasswordModal({ open, onClose }: ForgotPasswordModalProps) {
  const [step, setStep] = useState(1); // 1=填邮箱发码, 2=填验证码+新密码
  const [email, setEmail] = useState('');
  const [countdown, setCountdown] = useState(0);
  const [sending, setSending] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const sendCode = async () => {
    if (!email) {
      message.warning('请先填写邮箱');
      return;
    }
    setSending(true);
    try {
      await authApi.sendResetCode(email);
      message.success('验证码已发送，请查收邮箱');
      setStep(2);
      let left = 60;
      setCountdown(left);
      const timer = setInterval(() => {
        left -= 1;
        setCountdown(left);
        if (left <= 0) clearInterval(timer);
      }, 1000);
    } catch (err) {
      message.error(getErrorMessage(err, '验证码发送失败，请稍后重试'));
    } finally {
      setSending(false);
    }
  };

  const handleReset = async (values: { code: string; new_password: string }) => {
    setSubmitting(true);
    try {
      await authApi.resetPassword(email, values.code, values.new_password);
      message.success('密码已重置，请登录');
      handleClose();
    } catch (err) {
      message.error(getErrorMessage(err, '重置失败，请稍后重试'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleClose = () => {
    onClose();
    setStep(1);
    setEmail('');
    setCountdown(0);
  };

  return (
    <Modal title="忘记密码" open={open} onCancel={handleClose} footer={null} width={420}>
      {step === 1 ? (
        <Form layout="vertical">
          <Form.Item label="邮箱" required>
            <Input
              prefix={<MailOutlined />}
              placeholder="注册邮箱"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onPressEnter={sendCode}
            />
          </Form.Item>
          <Button type="primary" block loading={sending} onClick={sendCode}>
            发送验证码
          </Button>
        </Form>
      ) : (
        <Form layout="vertical" onFinish={handleReset}>
          <Form.Item label="邮箱">
            <Input prefix={<MailOutlined />} value={email} disabled />
          </Form.Item>
          <Form.Item name="code" rules={[{ required: true, len: 6, message: '请输入6位数字验证码' }]}>
            <Input prefix={<SafetyCertificateOutlined />} placeholder="验证码" />
          </Form.Item>
          <Form.Item name="new_password" rules={[{ required: true, min: 6, message: '密码至少6个字符' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="新密码（至少6位）" />
          </Form.Item>
          <Form.Item name="confirm" dependencies={['new_password']} rules={[
            { required: true, message: '请再次输入新密码' },
            ({ getFieldValue }) => ({
              validator(_, value) {
                if (!value || getFieldValue('new_password') === value) {
                  return Promise.resolve();
                }
                return Promise.reject(new Error('两次输入的密码不一致'));
              },
            }),
          ]}>
            <Input.Password prefix={<LockOutlined />} placeholder="确认新密码" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={submitting}>
            重置密码
          </Button>
        </Form>
      )}
    </Modal>
  );
}
```

- [ ] **Step 2: 构建验证**

Run: `cd D:/project/github/stock-monitor/frontend && npm run build`
Expected: `tsc -b && vite build` 成功，无类型错误。

- [ ] **Step 3: 提交**

```bash
cd D:/project/github/stock-monitor
git add frontend/src/components/ForgotPasswordModal.tsx
git commit -m "feat: 忘记密码弹窗组件 — 两步表单（发码 → 验证码+新密码）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 登录页接入弹窗

**Files:**
- Modify: `frontend/src/pages/Login.tsx`

**Interfaces:**
- Consumes: `ForgotPasswordModal`（Task 3）、`getErrorMessage`（Task 2）
- Produces: 登录页「忘记密码？」入口 + 弹窗挂载

- [ ] **Step 1: 移除本地 `getErrorMessage` 并改 import**

`frontend/src/pages/Login.tsx` 顶部：

1. 删除文件内的 `getErrorMessage` 函数定义（第 7-16 行）。
2. 在 `import { authApi } from '@/api/client';` 之后加一行：

```tsx
import { getErrorMessage } from '@/utils/error';
```

- [ ] **Step 2: 添加状态与 import**

`frontend/src/pages/Login.tsx`：
1. 顶部加 import：

```tsx
import { ForgotPasswordModal } from '@/components/ForgotPasswordModal';
```

2. 在 `const [regEmail, setRegEmail] = useState('');` 之后加：

```tsx
  const [forgotOpen, setForgotOpen] = useState(false);
```

- [ ] **Step 3: 加「忘记密码？」链接**

`frontend/src/pages/Login.tsx` 登录 Tab 表单中，密码 `Form.Item`（`name="password"`）之后、提交按钮 `Form.Item` 之前，插入：

```tsx
                <Form.Item>
                  <div style={{ textAlign: 'right' }}>
                    <Button type="link" size="small" onClick={() => setForgotOpen(true)}>
                      忘记密码？
                    </Button>
                  </div>
                </Form.Item>
```

- [ ] **Step 4: 挂载弹窗**

`frontend/src/pages/Login.tsx` 最外层 `</Card>` 之后、外层 `</div>` 之前，加：

```tsx
      <ForgotPasswordModal open={forgotOpen} onClose={() => setForgotOpen(false)} />
```

- [ ] **Step 5: 构建验证**

Run: `cd D:/project/github/stock-monitor/frontend && npm run build`
Expected: `tsc -b && vite build` 成功，无类型错误。

- [ ] **Step 6: 提交**

```bash
cd D:/project/github/stock-monitor
git add frontend/src/pages/Login.tsx
git commit -m "feat: 登录页接入忘记密码弹窗

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 全量验证

**Files:** 无新增

- [ ] **Step 1: 运行全量后端测试**

Run: `cd D:/project/github/stock-monitor && python -m pytest tests/ -v 2>&1 | tail -20`
Expected: 全部 PASS（原 139 + 5 个新用例 = 144 passed）。

- [ ] **Step 2: 前端生产构建**

Run: `cd D:/project/github/stock-monitor/frontend && npm run build`
Expected: 构建成功，`dist/` 产物生成。

- [ ] **Step 3: 本地冒烟（可选）**

启动本地后端 + 前端 dev，走一遍：登录页 → 忘记密码 → 发码（控制台打印验证码）→ 重置 → 新密码登录。

- [ ] **Step 4: 提交（如有改动）**

```bash
cd D:/project/github/stock-monitor
git add -A
git commit -m "chore: 忘记密码功能全量验证通过

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review 结果

- **Spec 覆盖**：后端 Schema（ResetSendCodeRequest/ResetPasswordRequest）✓、AuthService.reset_password ✓、EmailService 文案 ✓、2 端点 ✓、前端弹窗 ✓、错误处理表（409/429/400/前端校验）✓、测试计划 5 用例 ✓。
- **占位符**：无 TBD/TODO，所有代码步骤为完整可执行代码。
- **类型一致性**：`purpose="reset_password"` 在后端服务/API/EmailService、前端请求、测试中统一；端点路径 `/api/auth/password/send-code`、`/api/auth/password/reset` 前后端一致；`ResetPasswordRequest.new_password`（后端）↔ `resetPassword(..., newPassword)` 序列化为 `new_password`（前端）一致。
- **规格偏差说明**：规格文档曾列「扩展 `SendCodeRequest.purpose` 正则」，实际采用独立 `ResetSendCodeRequest` + 端点硬编码 purpose，故不改 `SendCodeRequest`（避免死代码），已在上方 Global Constraints 说明。
