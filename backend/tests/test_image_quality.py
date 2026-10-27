from app.services.image_quality import assess_image

def test_rejects_unsupported_mime_type():
    result = assess_image(b"not an image", "application/pdf")
    assert result["accepted"] is False
    assert result["status"] == "rejected"
