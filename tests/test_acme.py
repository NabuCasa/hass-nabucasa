"""Test ACME handler functionality."""

from socket import gaierror
from unittest.mock import Mock, patch

from acme import messages
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.extensions import SubjectAlternativeName
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


def test_acme_handler_generate_csr_creates_private_key(cloud: Cloud) -> None:
    """Test _generate_csr creates, stores and uses a new private key."""
    handler = AcmeHandler(cloud, ["test.example.com"], "test@example.com", Mock())

    with (
        patch("pathlib.Path.write_bytes") as mock_write_bytes,
        patch("pathlib.Path.chmod") as mock_chmod,
    ):
        csr_pem = handler._generate_csr()

    mock_write_bytes.assert_called_once()
    mock_chmod.assert_called_once_with(0o600)

    key_pem = mock_write_bytes.call_args[0][0]
    assert key_pem.startswith(b"-----BEGIN PRIVATE KEY-----")

    key = serialization.load_pem_private_key(key_pem, password=None)
    assert isinstance(key, rsa.RSAPrivateKey)
    assert key.key_size == 2048

    csr = x509.load_pem_x509_csr(csr_pem)
    assert csr.is_signature_valid
    assert csr.public_key().public_numbers() == key.public_key().public_numbers()
    alternative_names = csr.extensions.get_extension_for_class(
        SubjectAlternativeName,
    ).value
    assert [str(entry.value) for entry in alternative_names] == ["test.example.com"]


def test_acme_handler_generate_csr_existing_private_key(cloud: Cloud) -> None:
    """Test _generate_csr reuses an existing private key."""
    handler = AcmeHandler(cloud, ["test.example.com"], "test@example.com", Mock())

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.read_bytes", return_value=key_pem),
        patch("pathlib.Path.write_bytes") as mock_write_bytes,
    ):
        csr_pem = handler._generate_csr()

    mock_write_bytes.assert_not_called()

    csr = x509.load_pem_x509_csr(csr_pem)
    assert csr.public_key().public_numbers() == key.public_key().public_numbers()


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
