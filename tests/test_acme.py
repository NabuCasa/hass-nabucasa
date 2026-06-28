"""Test ACME handler functionality."""

import asyncio
from socket import gaierror
from unittest.mock import AsyncMock, Mock, patch

from acme import messages
import pytest
from requests.exceptions import RequestException

from hass_nabucasa import Cloud
from hass_nabucasa.acme import (
    AcmeChallengeError,
    AcmeClientError,
    AcmeHandler,
    AcmeJWSVerificationError,
    _raise_if_jws_verification_failed,
)
from hass_nabucasa.instance_api import InstanceApiError


@pytest.mark.parametrize(
    "error",
    [
        messages.Error(
            typ="urn:ietf:params:acme:error:malformed",
            detail="JWS verification error",
        ),
        messages.Error(
            typ="urn:ietf:params:acme:error:malformed",
            detail="Unable to validate JWS",
        ),
        messages.Error(
            typ="urn:ietf:params:acme:error:malformed",
            detail="Unable to validate JWS :: Invalid Content-Type header on",
        ),
    ],
)
def test_raise_if_jws_verification_failed_should_raise(error):
    """Test _raise_if_jws_verification_failed raises exception for JWS errors."""
    with pytest.raises(AcmeJWSVerificationError, match="JWS verification failed"):
        _raise_if_jws_verification_failed(error)


@pytest.mark.parametrize(
    "error",
    [
        messages.Error(
            typ="urn:ietf:params:acme:error:malformed",
            detail="Some other malformed reason",
        ),
        messages.Error(
            typ="about:blank",
            detail="JWS verification error",
        ),
        ValueError("Some other error"),
    ],
)
def test_raise_if_jws_verification_failed_should_not_raise(error):
    """Test _raise_if_jws_verification_failed does not raise for non-JWS errors."""
    _raise_if_jws_verification_failed(error)


def test_acme_handler_create_client_jws_error_existing_registration(
    cloud: Cloud,
) -> None:
    """Test _create_client handles JWS error when registration exists."""
    handler = AcmeHandler(cloud, ["test.example.com"], "test@example.com", Mock())

    registration_data = '{"uri": "https://acme-v99.api.letsencrypt.org/acme/acct/1"}'

    with (
        patch("hass_nabucasa.acme.client.ClientV2") as mock_clientv2,
        patch("hass_nabucasa.acme.client.ClientNetwork"),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.read_text", return_value=registration_data),
        patch("pathlib.Path.unlink"),
        patch(
            "hass_nabucasa.acme.messages.RegistrationResource.json_loads"
        ) as mock_json_loads,
        patch.object(handler, "_load_account_key"),
    ):
        mock_regr = Mock()
        mock_regr.uri = "https://acme-v99.api.letsencrypt.org/acme/acct/1"
        mock_json_loads.return_value = mock_regr

        handler._account_jwk = Mock()

        jws_error = messages.Error(
            typ="urn:ietf:params:acme:error:malformed",
            detail="JWS verification error",
        )

        mock_clientv2.get_directory.side_effect = jws_error

        with pytest.raises(AcmeJWSVerificationError):
            handler._create_client()


@pytest.mark.parametrize(
    "error_detail,error_location",
    [
        ("Unable to validate JWS", "get_directory"),
        ("JWS verification error", "new_account"),
    ],
)
def test_acme_handler_create_client_jws_error_no_registration(
    cloud: Cloud,
    error_detail: str,
    error_location: str,
) -> None:
    """Test _create_client handles JWS errors when no registration exists."""
    handler = AcmeHandler(cloud, ["test.example.com"], "test@example.com", Mock())

    with (
        patch("hass_nabucasa.acme.client.ClientV2") as mock_clientv2,
        patch("hass_nabucasa.acme.client.ClientNetwork"),
        patch("pathlib.Path.exists", return_value=False),
        patch.object(handler, "_load_account_key"),
        patch("pathlib.Path.write_text"),
        patch("pathlib.Path.chmod"),
    ):
        handler._account_jwk = Mock()

        jws_error = messages.Error(
            typ="urn:ietf:params:acme:error:malformed",
            detail=error_detail,
        )

        if error_location == "get_directory":
            mock_clientv2.get_directory.side_effect = jws_error
        else:
            mock_directory = Mock()
            mock_directory.meta.terms_of_service = "https://example.com/tos"
            mock_clientv2.get_directory.return_value = mock_directory

            mock_client_instance = Mock()
            mock_client_instance.directory = mock_directory
            mock_clientv2.return_value = mock_client_instance
            mock_client_instance.new_account.side_effect = jws_error

        with pytest.raises(AcmeJWSVerificationError):
            handler._create_client()


@pytest.mark.parametrize(
    ("exception_type", "exception_args"),
    [
        (gaierror, ("getaddrinfo failed",)),
        (RequestException, ("Connection timeout",)),
    ],
)
def test_acme_handler_create_client_network_errors(
    cloud: Cloud,
    exception_type: type[Exception],
    exception_args: tuple,
) -> None:
    """Test _create_client handles network errors (gaierror, RequestException)."""
    handler = AcmeHandler(cloud, ["test.example.com"], "test@example.com", Mock())

    with (
        patch("hass_nabucasa.acme.client.ClientV2") as mock_clientv2,
        patch("hass_nabucasa.acme.client.ClientNetwork"),
        patch("pathlib.Path.exists", return_value=False),
        patch.object(handler, "_load_account_key"),
    ):
        handler._account_jwk = Mock()

        # Simulate network error during directory retrieval
        mock_clientv2.get_directory.side_effect = exception_type(*exception_args)

        with pytest.raises(AcmeClientError, match="Can't connect to ACME server"):
            handler._create_client()


@pytest.mark.parametrize(
    ("exception_type", "exception_args"),
    [
        (gaierror, ("DNS resolution failed",)),
        (RequestException, ("Network unreachable",)),
    ],
)
def test_acme_handler_create_order_network_errors(
    cloud: Cloud,
    exception_type: type[Exception],
    exception_args: tuple,
) -> None:
    """Test _create_order handles network errors (gaierror, RequestException)."""
    handler = AcmeHandler(cloud, ["test.example.com"], "test@example.com", Mock())

    mock_client = Mock()
    handler._acme_client = mock_client

    # Simulate network error during order creation
    mock_client.new_order.side_effect = exception_type(*exception_args)

    with pytest.raises(AcmeChallengeError, match="Can't order a new ACME challenge"):
        handler._create_order(b"test_csr")


@pytest.mark.parametrize(
    ("exception_type", "exception_args"),
    [
        (gaierror, ("DNS lookup failed",)),
        (RequestException, ("Connection error",)),
    ],
)
def test_acme_handler_answer_challenge_network_errors(
    cloud: Cloud,
    exception_type: type[Exception],
    exception_args: tuple,
) -> None:
    """Test _answer_challenge handles network errors (gaierror, RequestException)."""
    handler = AcmeHandler(cloud, ["test.example.com"], "test@example.com", Mock())

    mock_client = Mock()
    handler._acme_client = mock_client

    mock_challenge_handler = Mock()
    mock_challenge_handler.challenge = Mock()
    mock_challenge_handler.response = Mock()

    # Simulate network error during challenge answer
    mock_client.answer_challenge.side_effect = exception_type(*exception_args)

    with pytest.raises(AcmeChallengeError, match="Can't accept ACME challenge"):
        handler._answer_challenge(mock_challenge_handler)


@pytest.mark.parametrize(
    ("exception_type", "exception_args"),
    [
        (gaierror, ("Connection error",)),
        (RequestException, ("Timeout during poll",)),
    ],
)
def test_acme_handler_deactivate_account_network_errors(
    cloud: Cloud,
    exception_type: type[Exception],
    exception_args: tuple,
) -> None:
    """Test _deactivate_account handles network errors (gaierror, RequestException)."""
    handler = AcmeHandler(cloud, ["test.example.com"], "test@example.com", Mock())

    mock_client = Mock()
    handler._acme_client = mock_client

    registration_data = '{"uri": "https://acme-v99.api.letsencrypt.org/acme/acct/1"}'

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.read_text", return_value=registration_data),
        patch(
            "hass_nabucasa.acme.messages.RegistrationResource.json_loads"
        ) as mock_json_loads,
    ):
        mock_regr = Mock()
        mock_json_loads.return_value = mock_regr

        # Simulate network error during account deactivation
        mock_client.deactivate_registration.side_effect = exception_type(
            *exception_args
        )

        with pytest.raises(AcmeClientError, match="Can't deactivate account"):
            handler._deactivate_account()


def _prepare_issue_certificate_handler(cloud: Cloud) -> tuple[AcmeHandler, Mock]:
    """Return an AcmeHandler with the issue_certificate internals mocked out."""
    handler = AcmeHandler(cloud, ["test.example.com"], "test@example.com", Mock())

    challenge = Mock()
    challenge.validation = "test-validation"

    cloud.instance.create_dns_challenge_record = AsyncMock()
    cloud.instance.cleanup_dns_challenge_record = AsyncMock()

    patches = patch.multiple(
        handler,
        _create_client=Mock(),
        _generate_csr=Mock(return_value=b"csr"),
        _create_order=Mock(return_value=Mock()),
        _start_challenge=Mock(return_value=[challenge]),
        _answer_challenge=Mock(),
        _finish_challenge=Mock(),
        load_certificate=AsyncMock(),
    )
    return handler, patches


async def test_issue_certificate_cancelled_skips_dns_cleanup(cloud: Cloud) -> None:
    """Test cancelling issue_certificate skips the authenticated DNS cleanup."""
    handler, patches = _prepare_issue_certificate_handler(cloud)

    parked = asyncio.Event()

    async def _fake_sleep(_seconds: float) -> None:
        """Park the task at a cancellable await point."""
        parked.set()
        await asyncio.Event().wait()

    with patches, patch("hass_nabucasa.acme.asyncio.sleep", side_effect=_fake_sleep):
        task = asyncio.ensure_future(handler.issue_certificate())
        await parked.wait()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    cloud.instance.create_dns_challenge_record.assert_awaited_once()
    cloud.instance.cleanup_dns_challenge_record.assert_not_awaited()


async def test_issue_certificate_cleanup_instance_error_is_logged(
    cloud: Cloud,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test a failing DNS cleanup is logged and does not propagate."""
    handler, patches = _prepare_issue_certificate_handler(cloud)
    cloud.instance.cleanup_dns_challenge_record = AsyncMock(
        side_effect=InstanceApiError("No authentication found"),
    )

    with patches, patch("hass_nabucasa.acme.asyncio.sleep", AsyncMock()):
        await handler.issue_certificate()

        # Issuance continued past the failed cleanup instead of aborting.
        handler.load_certificate.assert_awaited_once()

    cloud.instance.cleanup_dns_challenge_record.assert_awaited_once()
    assert "Failed to clean up challenge from NabuCasa DNS" in caplog.text
