"""
app/userbot_sender.py :: personalize_caption() 동작을 검증한다.

utils.sns_client 모듈은 이전 코드에서 제거됐으므로 이 파일에서 더 이상 테스트하지 않는다.
"""
import pytest
from unittest.mock import MagicMock, patch

import app.userbot_sender as sender


@pytest.fixture(autouse=True)
def reset_gemini_key(monkeypatch):
    """각 테스트 전에 GEMINI_API_KEY 를 비운다."""
    monkeypatch.setattr(sender, "GEMINI_API_KEY", "")


# ── 조기 반환(early-return) 케이스 ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_api_key_returns_original():
    """GEMINI_API_KEY 가 없으면 원본 캡션을 그대로 반환해야 한다."""
    result = await sender.personalize_caption("Hello world!", "user123")
    assert result == "Hello world!"


@pytest.mark.asyncio
async def test_empty_caption_returns_original(monkeypatch):
    """캡션이 빈 문자열이면 API 호출 없이 빈 문자열을 반환해야 한다."""
    monkeypatch.setattr(sender, "GEMINI_API_KEY", "test-key")
    result = await sender.personalize_caption("", "user123")
    assert result == ""


@pytest.mark.asyncio
async def test_empty_username_returns_original(monkeypatch):
    """username 이 빈 문자열이면 API 호출 없이 원본을 반환해야 한다."""
    monkeypatch.setattr(sender, "GEMINI_API_KEY", "test-key")
    result = await sender.personalize_caption("Hello!", "")
    assert result == "Hello!"


# ── 정상 호출 ─────────────────────────────────────────────────────────────────

def _mock_genai_modules(mock_genai):
    """google 및 google.generativeai 를 함께 패치하는 context manager 반환."""
    mock_google = MagicMock()
    mock_google.generativeai = mock_genai
    return patch.dict("sys.modules", {
        "google":               mock_google,
        "google.generativeai":  mock_genai,
    })


@pytest.mark.asyncio
async def test_calls_gemini_and_returns_result(monkeypatch):
    """Gemini API 가 정상 응답하면 재작성된 캡션을 반환해야 한다."""
    monkeypatch.setattr(sender, "GEMINI_API_KEY", "test-key")

    mock_response = MagicMock()
    mock_response.text = "Halo dunia!"

    mock_model = MagicMock()
    mock_model.generate_content = MagicMock(return_value=mock_response)

    mock_genai = MagicMock()
    mock_genai.GenerativeModel.return_value = mock_model

    with _mock_genai_modules(mock_genai):
        result = await sender.personalize_caption("Hello world!", "budisetiawan")

    assert result == "Halo dunia!"
    mock_genai.configure.assert_called_once_with(api_key="test-key")
    mock_genai.GenerativeModel.assert_called_once_with("gemini-1.5-flash")


# ── 오류 폴백 ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fallback_on_gemini_exception(monkeypatch):
    """Gemini 호출 실패 시 원본 캡션으로 폴백해야 하며 예외가 전파되면 안 된다."""
    monkeypatch.setattr(sender, "GEMINI_API_KEY", "test-key")

    mock_genai = MagicMock()
    mock_genai.GenerativeModel.side_effect = RuntimeError("API error")

    with _mock_genai_modules(mock_genai):
        result = await sender.personalize_caption("Original caption!", "user123")

    assert result == "Original caption!"


@pytest.mark.asyncio
async def test_fallback_on_empty_response(monkeypatch):
    """Gemini 가 빈 텍스트를 반환하면 원본 캡션을 반환해야 한다."""
    monkeypatch.setattr(sender, "GEMINI_API_KEY", "test-key")

    mock_response = MagicMock()
    mock_response.text = "   "  # whitespace only

    mock_model = MagicMock()
    mock_model.generate_content = MagicMock(return_value=mock_response)

    mock_genai = MagicMock()
    mock_genai.GenerativeModel.return_value = mock_model

    with _mock_genai_modules(mock_genai):
        result = await sender.personalize_caption("Fallback me!", "user456")

    assert result == "Fallback me!"
