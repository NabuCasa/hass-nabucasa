"""Test ACME handler functionality."""

from unittest.mock import Mock, patch

from acme import messages
import pytest

from hass_nabucasa import Cloud
from hass_nabucasa.acme import (
    AcmeHandler,
    AcmeJWSVerificationError,
    _raise_if_jws_verification_failed,
)


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
