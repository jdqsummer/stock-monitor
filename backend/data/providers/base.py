# stock-monitor/backend/data/providers/base.py
"""多渠道数据源抽象层"""
import abc
import logging

from backend.schemas.stock import CompanyNews, FinancialReport, StockQuote

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """数据源 Provider 异常（网络 / 解析 / 字段缺失）"""
    pass


def normalize_code(code: str) -> tuple[str, str]:
    """
    把裸股票代码转成渠道代码。

    600519 -> ("sh600519", "1.600519")   沪
    000001 -> ("sz000001", "0.000001")   深
    300750 -> ("sz300750", "0.300750")   创业板
    4xx/8xx/920 -> bj（东财 secid 待完善）
    """
    code = code.strip()
    if code[:2].lower() in ("sh", "sz", "bj"):
        rest = code[2:]
    else:
        rest = code
    if rest.startswith(("6", "688", "689")):
        tencent, em_market = "sh" + rest, "1"
    elif rest.startswith(("0", "3")):
        tencent, em_market = "sz" + rest, "0"
    else:
        tencent, em_market = "bj" + rest, "2"
    return tencent, f"{em_market}.{rest}"


class StockDataProvider(abc.ABC):
    """数据源抽象：统一输出 StockQuote / FinancialReport / 新闻 / 搜索"""

    @abc.abstractmethod
    async def fetch_quote(self, code: str) -> StockQuote:
        """获取实时行情"""
        ...

    @abc.abstractmethod
    async def fetch_financials(self, code: str) -> FinancialReport:
        """获取最新财报（单报告期）"""
        ...

    @abc.abstractmethod
    async def fetch_news(self, code: str, limit: int = 10) -> list[CompanyNews]:
        """获取新闻（无公开源时返回空列表）"""
        ...

    @abc.abstractmethod
    async def search_stock(self, keyword: str) -> list[StockQuote]:
        """搜索股票（代码/名称模糊匹配）"""
        ...

    @abc.abstractmethod
    async def fetch_industry(self, code: str) -> str:
        """获取行业分类（返回一级行业名，如「电气设备」；无法判定时抛 ProviderError 由链切换）"""
        ...

    async def close(self):
        """释放底层连接"""
        pass
