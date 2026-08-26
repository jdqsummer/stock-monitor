# tests/test_api/test_diary_images.py
"""Diary 图片上传/读取 API 测试 — TDD

图片按 {DIARY_IMAGE_DIR}/{user_id}/ 子目录存储；读取需登录态（Authorization 头或
「token」cookie，<img> 标签无法携带 header 故支持 cookie 回退），且仅本人可见：
他人访问一律 404（不泄露存在性）。
"""
import base64

import pytest
from fastapi import HTTPException
from unittest.mock import patch

from backend.models.user import User
from backend.services.auth_svc import AuthService
from tests.test_api.test_chat import _register_and_login


def _png_bytes() -> bytes:
    # 1x1 透明 PNG
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )


async def _upload_png(client, token, tmp_path):
    with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
        return await client.post(
            "/api/diary/images",
            files={"file": ("shot.png", _png_bytes(), "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


class TestDiaryImageUpload:
    @pytest.mark.asyncio
    async def test_upload_valid_png(self, client, tmp_path):
        token = await _register_and_login(client, "img@example.com")
        uid = AuthService.decode_token(token)
        resp = await _upload_png(client, token, tmp_path)
        assert resp.status_code == 200
        url = resp.json()["data"]["url"]
        assert url.startswith(f"/api/diary/images/{uid}/")
        assert url.endswith(".png")
        stored = tmp_path / uid / url.rsplit("/", 1)[-1]
        assert stored.read_bytes() == _png_bytes()

    @pytest.mark.asyncio
    async def test_upload_rejects_non_image(self, client, tmp_path):
        token = await _register_and_login(client, "img2@example.com")
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
            resp = await client.post(
                "/api/diary/images",
                files={"file": ("note.txt", b"hello", "text/plain")},
                headers=_auth(token),
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
                headers=_auth(token),
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


class TestDiaryImageGet:
    @pytest.mark.asyncio
    async def test_get_with_bearer(self, client, tmp_path):
        """本人经 Authorization 头读取（前端 axios 同通道）。"""
        token = await _register_and_login(client, "img4@example.com")
        data = _png_bytes()
        up = await _upload_png(client, token, tmp_path)
        url = up.json()["data"]["url"]
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
            resp = await client.get(url, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.content == data
        assert resp.headers["content-type"].startswith("image/")

    @pytest.mark.asyncio
    async def test_get_with_cookie(self, client, tmp_path):
        """本人经 cookie 读取（<img> 标签无法携带 Authorization 头）。"""
        token = await _register_and_login(client, "img5@example.com")
        up = await _upload_png(client, token, tmp_path)
        url = up.json()["data"]["url"]
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
            resp = await client.get(url, cookies={"token": token})
        assert resp.status_code == 200
        assert resp.content == _png_bytes()

    @pytest.mark.asyncio
    async def test_get_without_auth_rejected(self, client, tmp_path):
        token = await _register_and_login(client, "img6@example.com")
        up = await _upload_png(client, token, tmp_path)
        url = up.json()["data"]["url"]
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
            resp = await client.get(url)
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_get_other_users_image_404(self, client, tmp_path):
        """跨用户不可见：B 访问 A 的图片一律 404（不泄露存在性）。"""
        token_a = await _register_and_login(client, "img7@example.com")
        up = await _upload_png(client, token_a, tmp_path)
        url = up.json()["data"]["url"]
        token_b = await _register_and_login(client, "img8@example.com")
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
            resp = await client.get(url, headers=_auth(token_b))
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_missing_404(self, client, tmp_path):
        token = await _register_and_login(client, "img9@example.com")
        uid = AuthService.decode_token(token)
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
            resp = await client.get(f"/api/diary/images/{uid}/missing.png",
                                    headers=_auth(token))
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_traversal_rejected(self, tmp_path):
        from backend.api.diary import get_diary_image
        me = User(id="u-traversal")
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
            for uid, fname in [("u-traversal", "../secret.txt"),
                               ("../../etc", "a.png")]:
                with pytest.raises(HTTPException) as ei:
                    await get_diary_image(uid, fname, current_user=me)
                assert ei.value.status_code == 404


class TestLegacyImageMigration:
    """旧版平铺根目录图片 → 属主子目录一次性迁移（幂等）。"""

    @pytest.mark.asyncio
    async def test_migrate_moves_file_and_rewrites_note(self, client, tmp_path, db_session):
        png = _png_bytes()
        fname = "a" * 32 + ".png"
        token = await _register_and_login(client, "mig1@example.com")
        uid = AuthService.decode_token(token)
        legacy_url = f"/api/diary/images/{fname}"
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", ""):
            resp = await client.post(
                "/api/diary", json={"content": f"![截图]({legacy_url})"},
                headers=_auth(token))
        assert resp.status_code == 200
        note_id = resp.json()["data"]["id"]
        (tmp_path / fname).write_bytes(png)          # 旧版：平铺根目录

        from backend.services.diary_svc import migrate_legacy_diary_images
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
            stats = await migrate_legacy_diary_images(db_session)

        assert stats["migrated_files"] == 1
        assert not (tmp_path / fname).exists()
        assert (tmp_path / uid / fname).read_bytes() == png
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
            got = await client.get(f"/api/diary/{note_id}", headers=_auth(token))
        new_content = got.json()["data"]["content"]
        assert legacy_url not in new_content
        assert f"/api/diary/images/{uid}/{fname}" in new_content

    @pytest.mark.asyncio
    async def test_migrate_idempotent(self, client, tmp_path, db_session):
        png = _png_bytes()
        fname = "b" * 32 + ".jpg"
        token = await _register_and_login(client, "mig2@example.com")
        legacy_url = f"/api/diary/images/{fname}"
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", ""):
            await client.post("/api/diary",
                              json={"content": f"![]({legacy_url})"},
                              headers=_auth(token))
        (tmp_path / fname).write_bytes(png)

        from backend.services.diary_svc import migrate_legacy_diary_images
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
            first = await migrate_legacy_diary_images(db_session)
            second = await migrate_legacy_diary_images(db_session)

        assert first["migrated_files"] >= 1
        assert second["migrated_files"] == 0
        assert second["rewritten_notes"] == 0

    @pytest.mark.asyncio
    async def test_migrate_skips_orphan_files(self, client, tmp_path, db_session):
        """无任何正文引用的孤儿文件无法归属 → 留在根目录（不再对外服务）。"""
        orphan = "c" * 32 + ".png"
        (tmp_path / orphan).write_bytes(_png_bytes())

        from backend.services.diary_svc import migrate_legacy_diary_images
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
            stats = await migrate_legacy_diary_images(db_session)

        assert stats["migrated_files"] == 0
        assert (tmp_path / orphan).exists()

    @pytest.mark.asyncio
    async def test_migrate_missing_file_only_rewrites_nothing(self, client, tmp_path, db_session):
        """正文引用了已被删除的旧文件 → 不改写正文（避免误改）。"""
        fname = "d" * 32 + ".png"
        token = await _register_and_login(client, "mig3@example.com")
        legacy_url = f"/api/diary/images/{fname}"
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", ""):
            resp = await client.post("/api/diary",
                                     json={"content": f"![]({legacy_url})"},
                                     headers=_auth(token))
        note_id = resp.json()["data"]["id"]

        from backend.services.diary_svc import migrate_legacy_diary_images
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
            stats = await migrate_legacy_diary_images(db_session)

        assert stats["rewritten_notes"] == 0
        with patch("backend.api.diary.settings.DIARY_IMAGE_DIR", str(tmp_path)):
            got = await client.get(f"/api/diary/{note_id}", headers=_auth(token))
        assert got.json()["data"]["content"] == f"![]({legacy_url})"
