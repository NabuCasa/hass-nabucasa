"""Tests for the trimmed botocore data used by the Cognito client."""

import importlib.util
from pathlib import Path

import botocore
from botocore.awsrequest import AWSResponse
import botocore.config
import botocore.session

from hass_nabucasa import auth as auth_api
from hass_nabucasa.auth.cognito import BOTOCORE_DATA_PATH

SCRIPT = Path(__file__).parent.parent / "scripts/update_botocore_data.py"
UNSIGNED = botocore.config.Config(signature_version=botocore.UNSIGNED)


def _load_script():
    """Load the generator script as a module."""
    spec = importlib.util.spec_from_file_location("update_botocore_data", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _trimmed_session() -> botocore.session.Session:
    """Return a botocore session reading the trimmed data."""
    session = botocore.session.Session()
    session.set_config_variable("data_path", str(BOTOCORE_DATA_PATH))
    return session


def _cognito_regions() -> list[str]:
    """Return every region stock botocore knows for Cognito."""
    session = botocore.session.Session()
    return [
        region
        for partition in session.get_available_partitions()
        for region in session.get_available_regions("cognito-idp", partition)
    ]


def _request_response_view(model: dict, operations: set[str]) -> dict:
    """Return what shapes the requests and parses the responses.

    Every operation field is compared, including ``auth`` and ``authtype``,
    which keep the calls unsigned. Error shapes are left out: botocore adds
    new error types between releases, and hass_nabucasa maps errors by their
    code string.
    """
    script = _load_script()
    view = {}
    pending = []
    for name in sorted(operations):
        operation = script._strip_docs(model["operations"][name])
        view[name] = {key: value for key, value in operation.items() if key != "errors"}
        assert {"auth", "authtype"} <= view[name].keys(), name
        pending.extend(operation[key]["shape"] for key in ("input", "output"))

    shapes = {}
    while pending:
        name = pending.pop()
        if name in shapes:
            continue
        shape = script._strip_docs(model["shapes"][name])
        shapes[name] = shape
        pending.extend(member["shape"] for member in shape.get("members", {}).values())
        pending.extend(
            shape[key]["shape"] for key in ("member", "key", "value") if key in shape
        )
    return {"operations": view, "shapes": shapes}


def test_service_model_matches_botocore():
    """Test the trimmed model builds and parses requests like installed botocore."""
    stock = botocore.session.Session().get_component("data_loader")
    trimmed = _trimmed_session().get_component("data_loader")
    stock_model = stock.load_service_model("cognito-idp", "service-2")
    trimmed_model = trimmed.load_service_model("cognito-idp", "service-2")

    operations = set(trimmed_model["operations"])
    assert operations == _load_script().OPERATIONS
    assert _request_response_view(trimmed_model, operations) == (
        _request_response_view(stock_model, operations)
    )


def test_endpoints_match_botocore():
    """Test every Cognito region resolves to the same endpoint as stock data."""
    regions = _cognito_regions()
    assert "us-east-1" in regions

    stock = botocore.session.Session()
    trimmed = _trimmed_session()
    for region in regions:
        expected = stock.create_client(
            "cognito-idp", region_name=region, config=UNSIGNED
        ).meta.endpoint_url
        actual = trimmed.create_client(
            "cognito-idp", region_name=region, config=UNSIGNED
        ).meta.endpoint_url
        assert actual == expected, region


def test_request_matches_botocore():
    """Test a Cognito call sends the same request with trimmed data."""
    sent = []

    def _send(request, **kwargs):
        sent.append((request.url, dict(request.headers), request.body))
        body = b'{"AuthenticationResult":{"AccessToken":"token","ExpiresIn":3600}}'
        raw = type("Raw", (), {"stream": lambda *_, **__: [body]})()
        return AWSResponse(
            request.url, 200, {"content-type": "application/x-amz-json-1.1"}, raw
        )

    results = []
    for session in (botocore.session.Session(), _trimmed_session()):
        client = session.create_client(
            "cognito-idp", region_name="us-east-1", config=UNSIGNED
        )
        client.meta.events.register("before-send", _send)
        results.append(
            client.initiate_auth(
                ClientId="client-id",
                AuthFlow="REFRESH_TOKEN_AUTH",
                AuthParameters={"REFRESH_TOKEN": "refresh"},
            )["AuthenticationResult"]
        )

    stock, trimmed = sent
    for request in (stock, trimmed):
        # Differs per request.
        request[1].pop("amz-sdk-invocation-id", None)
    assert trimmed == stock
    assert results[0] == results[1]


async def test_client_uses_trimmed_data(cloud_mock):
    """Test the Cognito client loads the trimmed files."""
    cloud_mock.user_pool_id = "us-east-1_abcdefghi"
    cloud_mock.cognito_client_id = "client-id"
    cloud_mock.region = "us-east-1"
    auth = auth_api.CognitoAuth(cloud_mock)

    cognito = await cloud_mock.run_executor(auth._create_cognito_client)

    loader = auth._session._session.get_component("data_loader")
    _, path = loader.load_data_with_path("endpoints")
    assert Path(path).parent == BOTOCORE_DATA_PATH
    assert cognito.client.meta.endpoint_url == (
        "https://cognito-idp.us-east-1.amazonaws.com"
    )
