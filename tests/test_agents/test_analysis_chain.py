from backend.agents.analysis_chain import AnalysisReport


def test_report_roundtrip_conclusion_fields():
    """conclusion / unassessable_risk 经 from_state / to_dict 贯通"""
    state = {
        "stock_code": "600519", "stock_name": "贵州茅台",
        "conclusion": "护城河深但估值偏高，清单证伪后应等待",
        "unassessable_risk": True,
    }
    report = AnalysisReport.from_state(state)
    assert report.conclusion == "护城河深但估值偏高，清单证伪后应等待"
    assert report.unassessable_risk is True
    d = report.to_dict()
    assert d["conclusion"] == report.conclusion
    assert d["unassessable_risk"] is True
