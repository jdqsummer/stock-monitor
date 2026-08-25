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
