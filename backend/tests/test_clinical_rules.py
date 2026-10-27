from app.services.clinical_rules import validate_findings

def test_quality_gate_blocks_findings():
    result = validate_findings([{"finding_type": "test", "confidence": .99}], {"accepted": False})
    assert result["allowed"] is False
    assert result["findings"] == []

def test_findings_always_require_review():
    result = validate_findings([{"finding_type": "test", "confidence": .95}], {"accepted": True})
    assert result["allowed"] is True
    assert result["findings"][0]["requires_dentist_review"] is True
