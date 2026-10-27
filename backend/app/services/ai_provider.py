from abc import ABC, abstractmethod

class DentalVisionProvider(ABC):
    @abstractmethod
    def analyze(self, image_path: str, quality_result: dict) -> dict: ...

class PrototypeVisionProvider(DentalVisionProvider):
    """No clinical inference. Used to validate plumbing until a validated model is selected."""
    def analyze(self, image_path: str, quality_result: dict) -> dict:
        return {
            "status": "model_not_configured",
            "model_name": "prototype-no-diagnostic-model",
            "model_version": "0.1.0",
            "summary": "Technical image checks completed. No dental findings were generated because a validated dental vision model is not configured.",
            "findings": [],
            "limitations": ["This prototype does not diagnose dental conditions.", "Technical image quality does not establish that an image is suitable for clinical interpretation."]
        }

def get_vision_provider() -> DentalVisionProvider:
    return PrototypeVisionProvider()
