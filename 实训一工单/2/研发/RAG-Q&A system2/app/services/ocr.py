from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO


@dataclass
class OCRStatus:
    enabled: bool
    available: bool
    engine: str
    message: str


class OCRService:
    """Optional OCR service with graceful fallback when dependencies are missing."""

    def __init__(self, *, enabled: bool = True, language: str = "chi_sim+eng") -> None:
        self.enabled = enabled
        self.language = language
        self._pytesseract = None
        self._available = False
        self._message = "OCR disabled."

        if not enabled:
            return

        try:
            import pytesseract  # type: ignore

            self._pytesseract = pytesseract
            self._available = True
            self._message = "OCR is available."
        except Exception:
            self._available = False
            self._message = "OCR dependencies are not installed."

    def status(self) -> OCRStatus:
        return OCRStatus(
            enabled=self.enabled,
            available=self._available,
            engine="pytesseract" if self._available else "unavailable",
            message=self._message,
        )

    def is_available(self) -> bool:
        return self.enabled and self._available and self._pytesseract is not None

    def extract_page_texts(self, pdf_path) -> list[str]:
        if not self.is_available():
            return []

        try:
            from pdf2image import convert_from_path  # type: ignore
        except Exception:
            self._available = False
            self._message = "pdf2image is not installed."
            return []

        try:
            images = convert_from_path(str(pdf_path))
        except Exception:
            return []

        texts: list[str] = []
        for image in images:
            try:
                text = self._pytesseract.image_to_string(image, lang=self.language) or ""
            except Exception:
                text = ""
            texts.append(self._normalize_ocr_text(text))
        return texts

    def _normalize_ocr_text(self, text: str) -> str:
        return text.replace("\x0c", "").strip()
