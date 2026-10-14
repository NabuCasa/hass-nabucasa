"""Test ACME handler functionality."""

from socket import gaierror
from unittest.mock import AsyncMock, Mock, call, patch

from acme import challenges, errors, messages
import pytest
from requests.exceptions import RequestException

from hass_nabucasa import CertificateStatus, Cloud
from hass_nabucasa.acme import (
    AcmeChallengeError,
    AcmeClientError,
    AcmeHandler,
    AcmeJWSVerificationError,
    AcmeNabuCasaError,
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


def test_acme_handler_generate_csr_domains(cloud: Cloud) -> None:
    """Test _generate_csr uses the domain, its wildcard and aliases."""
    handler = AcmeHandler(
        cloud, "test.example.com", ["alias.example.com"], "test@example.com", Mock()
    )

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.read_bytes", return_value=b"key"),
        patch("hass_nabucasa.acme.crypto_util.make_csr") as mock_make_csr,
    ):
        handler._generate_csr()

    mock_make_csr.assert_called_once_with(
        b"key", ["test.example.com", "*.test.example.com", "alias.example.com"]
    )


def test_acme_handler_create_client_jws_error_existing_registration(
    cloud: Cloud,
) -> None:
    """Test _create_client handles JWS error when registration exists."""
    handler = AcmeHandler(cloud, "test.example.com", [], "test@example.com", Mock())

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
    handler = AcmeHandler(cloud, "test.example.com", [], "test@example.com", Mock())

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
    handler = AcmeHandler(cloud, "test.example.com", [], "test@example.com", Mock())

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
    handler = AcmeHandler(cloud, "test.example.com", [], "test@example.com", Mock())

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
    handler = AcmeHandler(cloud, "test.example.com", [], "test@example.com", Mock())

    mock_client = Mock()
    handler._acme_client = mock_client

    mock_challenge_handler = Mock()
    mock_challenge_handler.challenge = Mock()
    mock_challenge_handler.response = Mock()

    # Simulate network error during challenge answer
    mock_client.answer_challenge.side_effect = exception_type(*exception_args)

    with pytest.raises(AcmeChallengeError, match="Can't accept ACME challenge"):
        handler._answer_challenge(mock_challenge_handler)


def _authorization(
    status: messages.Status,
    challenge_error: messages.Error | None = None,
) -> messages.AuthorizationResource:
    """Return an authorization resource with a single DNS challenge."""
    return messages.AuthorizationResource(
        uri="https://example.com/acme/authz/1",
        body=messages.Authorization(
            identifier=messages.Identifier(
                typ=messages.IDENTIFIER_FQDN, value="test.example.com"
            ),
            status=status,
            challenges=(
                messages.ChallengeBody(
                    chall=challenges.DNS01(token=b"t" * 16),
                    status=status,
                    error=challenge_error,
                ),
            ),
        ),
    )


def _challenge_handler() -> Mock:
    """Return a challenge handler for an order with two authorizations."""
    return Mock(
        order=messages.OrderResource(
            uri="https://example.com/acme/order/1",
            body=messages.Order(
                authorizations=[
                    "https://example.com/acme/authz/1",
                    "https://example.com/acme/authz/2",
                ],
            ),
        ),
        authorization=_authorization(messages.STATUS_PENDING),
    )


def test_acme_handler_wait_for_authorization_valid(cloud: Cloud) -> None:
    """Test _wait_for_authorization polls only the authorization of the challenge."""
    handler = AcmeHandler(cloud, "test.example.com", [], "test@example.com", Mock())
    handler._acme_client = Mock()

    handler._wait_for_authorization(_challenge_handler())

    order, _ = handler._acme_client.poll_authorizations.call_args.args
    assert list(order.body.authorizations) == ["https://example.com/acme/authz/1"]


def test_acme_handler_wait_for_authorization_invalid(cloud: Cloud) -> None:
    """Test _wait_for_authorization raises when the authorization is invalid."""
    handler = AcmeHandler(cloud, "test.example.com", [], "test@example.com", Mock())
    handler._acme_client = Mock()
    handler._acme_client.poll_authorizations.side_effect = errors.ValidationError(
        [
            _authorization(
                messages.STATUS_INVALID,
                messages.Error(detail="Incorrect TXT record"),
            )
        ]
    )

    with pytest.raises(
        AcmeChallengeError,
        match=r"(?s)test\.example\.com failed: .*Incorrect TXT record",
    ):
        handler._wait_for_authorization(_challenge_handler())


def test_acme_handler_wait_for_authorization_timeout(cloud: Cloud) -> None:
    """Test _wait_for_authorization raises when the authorization stays pending."""
    handler = AcmeHandler(cloud, "test.example.com", [], "test@example.com", Mock())
    handler._acme_client = Mock()
    handler._acme_client.poll_authorizations.side_effect = errors.TimeoutError()

    with pytest.raises(AcmeChallengeError, match="Timeout waiting"):
        handler._wait_for_authorization(_challenge_handler())


@pytest.mark.parametrize(
    ("exception_type", "exception_args"),
    [
        (gaierror, ("DNS lookup failed",)),
        (RequestException, ("Connection error",)),
    ],
)
def test_acme_handler_wait_for_authorization_network_errors(
    cloud: Cloud,
    exception_type: type[Exception],
    exception_args: tuple,
) -> None:
    """Test _wait_for_authorization handles network errors."""
    handler = AcmeHandler(cloud, "test.example.com", [], "test@example.com", Mock())
    handler._acme_client = Mock()
    handler._acme_client.poll_authorizations.side_effect = exception_type(
        *exception_args
    )

    with pytest.raises(
        AcmeChallengeError, match=r"ACME authorization of test\.example\.com failed"
    ):
        handler._wait_for_authorization(_challenge_handler())


async def test_acme_handler_issue_certificate_waits_for_each_authorization(
    cloud: Cloud,
) -> None:
    """Test issue_certificate waits for each authorization before the next record."""
    status_callback = Mock()
    handler = AcmeHandler(
        cloud,
        "test.example.com",
        ["alias.example.com"],
        "test@example.com",
        status_callback,
    )
    handler._acme_client = Mock()
    order = Mock()
    first = Mock(validation="first")
    second = Mock(validation="second")
    manager = Mock()
    manager.attach_mock(AsyncMock(), "set_dns")
    manager.attach_mock(AsyncMock(), "cleanup_dns")
    status_during_wait = []
    manager.wait.side_effect = lambda _: status_during_wait.append(
        status_callback.call_args
    )

    with (
        patch.object(handler, "_generate_csr"),
        patch.object(handler, "_create_order", return_value=order),
        patch.object(handler, "_start_challenge", return_value=[first, second]),
        patch.object(handler, "_answer_challenge", manager.answer),
        patch.object(handler, "_wait_for_authorization", manager.wait),
        patch.object(handler, "_finish_challenge", manager.finish),
        patch.object(handler, "load_certificate", AsyncMock()),
        patch.object(cloud.instance, "create_dns_challenge_record", manager.set_dns),
        patch.object(
            cloud.instance, "cleanup_dns_challenge_record", manager.cleanup_dns
        ),
        patch("hass_nabucasa.acme.asyncio.sleep", AsyncMock()),
    ):
        await handler.issue_certificate()

    assert manager.mock_calls == [
        call.set_dns(value="first"),
        call.answer(first),
        call.wait(first),
        call.set_dns(value="second"),
        call.answer(second),
        call.wait(second),
        call.cleanup_dns(value="second"),
        call.finish(order),
    ]
    assert status_during_wait == [call(CertificateStatus.CHALLENGE_VALIDATING)] * 2
    assert (
        status_callback.mock_calls.count(call(CertificateStatus.CHALLENGE_VALIDATED))
        == 2
    )


@pytest.mark.parametrize(
    ("answer_error", "expected_cleanup"),
    [
        (None, "second"),
        (AcmeChallengeError("boom"), "first"),
        (RuntimeError("boom"), "first"),
    ],
)
async def test_acme_handler_issue_certificate_cleans_up_published_record(
    cloud: Cloud,
    answer_error: Exception | None,
    expected_cleanup: str,
) -> None:
    """Test issue_certificate cleans up the last DNS record it published."""
    handler = AcmeHandler(
        cloud, "test.example.com", ["alias.example.com"], "test@example.com", Mock()
    )
    handler._acme_client = Mock()
    dns_challenges = [Mock(validation="first"), Mock(validation="second")]

    with (
        patch.object(handler, "_generate_csr"),
        patch.object(handler, "_create_order"),
        patch.object(handler, "_start_challenge", return_value=dns_challenges),
        patch.object(handler, "_answer_challenge", side_effect=answer_error),
        patch.object(handler, "_wait_for_authorization"),
        patch.object(handler, "_finish_challenge"),
        patch.object(handler, "load_certificate", AsyncMock()),
        patch.object(cloud.instance, "create_dns_challenge_record", AsyncMock()),
        patch.object(
            cloud.instance, "cleanup_dns_challenge_record", AsyncMock()
        ) as mock_cleanup,
        patch("hass_nabucasa.acme.asyncio.sleep", AsyncMock()),
    ):
        await handler.issue_certificate()

    mock_cleanup.assert_awaited_once_with(value=expected_cleanup)


async def test_acme_handler_issue_certificate_skips_cleanup_without_record(
    cloud: Cloud,
) -> None:
    """Test issue_certificate skips cleanup when no DNS record was published."""
    handler = AcmeHandler(cloud, "test.example.com", [], "test@example.com", Mock())
    handler._acme_client = Mock()

    with (
        patch.object(handler, "_generate_csr"),
        patch.object(handler, "_create_order"),
        patch.object(
            handler, "_start_challenge", return_value=[Mock(validation="first")]
        ),
        patch.object(
            cloud.instance,
            "create_dns_challenge_record",
            AsyncMock(side_effect=TimeoutError),
        ),
        patch.object(
            cloud.instance, "cleanup_dns_challenge_record", AsyncMock()
        ) as mock_cleanup,
        pytest.raises(AcmeNabuCasaError, match="Can't set challenge token"),
    ):
        await handler.issue_certificate()

    mock_cleanup.assert_not_awaited()


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
    handler = AcmeHandler(cloud, "test.example.com", [], "test@example.com", Mock())

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
