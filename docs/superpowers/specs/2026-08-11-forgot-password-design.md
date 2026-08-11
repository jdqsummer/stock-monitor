# 忘记密码 / 重置密码 — 设计文档

**日期**：2026-08-11
**状态**：已批准
**方案**：验证码式重置（复用现有邮箱验证码基建）

## 背景

生产环境用户 `1140467720@qq.com` 忘记密码（登录一直提示「邮箱或密码错误」）。系统当前无任何密码自助重置能力，需要新增「忘记密码 / 重置密码」功能。

## 方案选择

对比三种方案后采用 **A. 验证码式重置**：

| 方案 | 结论 |
|:--|:--|
| A. 验证码式重置（复用 Redis 验证码 + 邮件） | **采用**，改动最小，与注册/登录码流程一致 |
| B. 邮件链接 Token 式 | 更安全但需独立路由页面，对单用户系统过重 |
| C. 仅服务端脚本重置 | 不解决用户自助需求 |

## 后端设计

### Schema（`backend/schemas/user.py`）

新增 `ResetPasswordRequest`：

```python
class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=6, max_length=128)
```

修改 `SendCodeRequest.purpose` 正则：`^(register|login|reset_password)$`

### AuthService（`backend/services/auth_svc.py`）

新增方法：

```python
@staticmethod
async def reset_password(db, email, code, new_password) -> User | None:
    """验证码 + 新密码重置。验证码不过返回 None，通过则更新 password_hash。"""
```

复用现有：`save_verify_code` / `verify_code` / `check_rate_limit` / `hash_password`。

### EmailService（`backend/services/email_svc.py`）

`purpose` 文案映射增加：`reset_password` → `"重置密码"`。

### API 端点（`backend/api/auth.py`）

| 端点 | 请求 | 行为 |
|:--|:--|:--|
| `POST /api/auth/password/send-code` | `{email}` | 邮箱未注册 → 409「该邮箱未注册，请先注册」；限频 → 429；发码 → 200 |
| `POST /api/auth/password/reset` | `{email, code, new_password}` | 验证码错/过期 → 400「验证码错误或已过期」；成功 → 更新 `password_hash`，返回「密码重置成功」 |

**注意**：重置发码端点请求体为 `{email}`，端点内部**硬编码 `purpose="reset_password"`**（不复用 `SendCodeRequest.purpose` 默认值 `"register"`，避免 Redis 键错存）。为此新增轻量 schema `ResetSendCodeRequest(BaseModel): email: EmailStr`。

## 前端设计（登录页弹窗）

- 登录卡片「密码」下方加 **「忘记密码？」** 链接。
- 点击弹 `Modal`，两步：
  1. 第一步：填邮箱 + 「发送验证码」按钮（60s 倒计时复用 `sendRegisterCode` 逻辑）→ 成功切第二步。
  2. 第二步：填 6 位验证码 + 新密码 + 确认新密码（前端校验一致）→ 提交成功提示「密码已重置，请登录」并关闭弹窗。

## 错误处理

| 场景 | 状态码 | 提示 |
|:--|:--|:--|
| 邮箱未注册（发码） | 409 | 该邮箱未注册，请先注册 |
| 发送过于频繁 | 429 | 发送过于频繁，请稍后再试 |
| 验证码错误/过期 | 400 | 验证码错误或已过期 |
| 新密码与确认不一致（前端） | — | 两次输入的密码不一致 |

**已知限制**：重置后不强制旧 JWT 失效（token 无版本机制，24h 过期，个人系统可接受，本次不做）。

## 数据流

```
登录页「忘记密码」→ 弹窗填邮箱 → POST /password/send-code
  → [未注册? 409] → EmailService 发码（dev 打印控制台 / prod SMTP）→ Redis 存码(5min)
→ 填 验证码+新密码+确认 → POST /password/reset
  → verify_code(校验即删) → bcrypt 哈希新密码 → 更新 users.password_hash → 返回成功 → 回登录页
```

## 测试计划（TDD）

`tests/test_api/test_auth.py` 新增用例：
- 发码成功（已注册邮箱）→ 200
- 未注册邮箱发码 → 409
- 重置成功 → 200，且旧密码登录 401、新密码登录 200
- 验证码错误 → 400
- 发码限频 → 429
