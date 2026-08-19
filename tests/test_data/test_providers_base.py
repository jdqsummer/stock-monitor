import pytest

from backend.data.providers.base import is_hk, market_of, normalize_code


def test_normalize_code_hk_suffix():
    assert normalize_code("00700.HK") == ("hk00700", "116.00700")
    assert normalize_code("01398.HK") == ("hk01398", "116.01398")


def test_normalize_code_hk_prefix():
    assert normalize_code("hk00700") == ("hk00700", "116.00700")


def test_normalize_code_a_share_unchanged():
    assert normalize_code("600519") == ("sh600519", "1.600519")
    assert normalize_code("000001") == ("sz000001", "0.000001")


def test_market_of():
    assert market_of("00700.HK") == "HK"
    assert market_of("hk00700") == "HK"
    assert market_of("600519") == "A"
    assert market_of("sh600519") == "A"


def test_is_hk():
    assert is_hk("00700.HK") is True
    assert is_hk("600519") is False
