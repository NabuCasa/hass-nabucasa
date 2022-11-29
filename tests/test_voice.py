"""Test for voice functions."""
from datetime import timedelta

import hass_nabucasa.voice as voice


async def test_token_handling(auth_cloud_mock, aioclient_mock):
    """Test handling around token."""
    auth_cloud_mock.voice_server = "test.local"
    voice_api = voice.Voice(auth_cloud_mock)

    assert not voice_api._validate_token()

    aioclient_mock.get(
        "https://test.local/connection_details",
        json={
            "authorized_key": "test-key",
            "endpoint_stt": "stt-url",
            "endpoint_tts": "tts-url",
            "valid": f"{(voice.utcnow() + timedelta(minutes=9)).timestamp()}",
        },
    )

    await voice_api._update_token()
    assert voice_api._validate_token()

    assert voice_api._endpoint_stt == "stt-url"
    assert voice_api._endpoint_tts == "tts-url"
    assert voice_api._token == "test-key"


async def test_process_stt(auth_cloud_mock, aioclient_mock):
    """Test handling around stt."""
    auth_cloud_mock.voice_server = "test.local"
    voice_api = voice.Voice(auth_cloud_mock)

    aioclient_mock.get(
        "https://test.local/connection_details",
        json={
            "authorized_key": "test-key",
            "endpoint_stt": "stt-url",
            "endpoint_tts": "tts-url",
            "valid": f"{(voice.utcnow() + timedelta(minutes=9)).timestamp()}",
        },
    )

    aioclient_mock.post(
        "stt-url?language=en-US",
        json={"RecognitionStatus": "Success", "DisplayText": "My Text"},
    )
    result = await voice_api.process_stt(b"feet", "video=test", "en-US")

    assert result.success
    assert result.text == "My Text"


async def test_process_tts(auth_cloud_mock, aioclient_mock):
    """Test handling around tts."""
    auth_cloud_mock.voice_server = "test.local"
    voice_api = voice.Voice(auth_cloud_mock)

    aioclient_mock.get(
        "https://test.local/connection_details",
        json={
            "authorized_key": "test-key",
            "endpoint_stt": "stt-url",
            "endpoint_tts": "tts-url",
            "valid": f"{(voice.utcnow() + timedelta(minutes=9)).timestamp()}",
        },
    )

    aioclient_mock.post(
        "tts-url",
        content=b"My sound",
    )
    result = await voice_api.process_tts(
        "Text for Saying", "en-US", voice.Gender.FEMALE
    )

    assert result == b"My sound"
