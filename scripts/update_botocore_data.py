#!/usr/bin/env python3
"""Generate the trimmed botocore data used by the Cognito client.

botocore loads its full endpoints.json (every AWS service) and the complete
cognito-idp service model when a client is created, and keeps both for the
life of the session: about 9 MiB. The Cognito client only needs the
cognito-idp endpoints and the operations listed below.

Run this script after changing OPERATIONS or bumping botocore. Pass --check
to fail instead of writing when the committed files are out of date.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
import sys
from typing import Any

import botocore

SERVICE = "cognito-idp"
API_VERSION = "2016-04-18"

# Every Cognito operation reached through pycognito by hass_nabucasa.auth.
OPERATIONS = frozenset(
    {
        "ForgotPassword",
        "InitiateAuth",
        "ResendConfirmationCode",
        "RespondToAuthChallenge",
        "SignUp",
    }
)

BOTOCORE_DATA = Path(botocore.__file__).parent / "data"
OUTPUT = Path(__file__).parent.parent / "hass_nabucasa/auth/botocore_data"


def _load(path: Path) -> Any:
    """Load a botocore data file, compressed or not."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(gzip.decompress(path.with_suffix(".json.gz").read_bytes()))


def _endpoints() -> dict[str, Any]:
    """Return endpoints.json with only the Cognito service in each partition."""
    data = _load(BOTOCORE_DATA / "endpoints.json")
    for partition in data["partitions"]:
        partition["services"] = {
            name: service
            for name, service in partition["services"].items()
            if name == SERVICE
        }
    return data


def _service_model() -> dict[str, Any]:
    """Return the Cognito model with only OPERATIONS and the shapes they use."""
    model = _load(BOTOCORE_DATA / SERVICE / API_VERSION / "service-2.json")
    missing = OPERATIONS - model["operations"].keys()
    if missing:
        raise SystemExit(f"Operations missing from botocore: {sorted(missing)}")

    shapes: set[str] = set()
    pending: list[str] = []
    for name in OPERATIONS:
        operation = model["operations"][name]
        pending.extend(operation[key]["shape"] for key in ("input", "output"))
        pending.extend(error["shape"] for error in operation.get("errors", []))

    while pending:
        name = pending.pop()
        if name in shapes:
            continue
        shapes.add(name)
        shape = model["shapes"][name]
        pending.extend(member["shape"] for member in shape.get("members", {}).values())
        pending.extend(
            shape[key]["shape"] for key in ("member", "key", "value") if key in shape
        )

    model.pop("documentation", None)
    model["operations"] = {
        name: _strip_docs(operation)
        for name, operation in model["operations"].items()
        if name in OPERATIONS
    }
    model["shapes"] = {
        name: _strip_docs(shape)
        for name, shape in model["shapes"].items()
        if name in shapes
    }
    return model


def _strip_docs(item: dict[str, Any]) -> dict[str, Any]:
    """Remove documentation from an operation or shape and its members.

    botocore only uses these strings to build docstrings.
    """
    item = {key: value for key, value in item.items() if key != "documentation"}
    if "members" in item:
        item["members"] = {
            name: {
                key: value for key, value in member.items() if key != "documentation"
            }
            for name, member in item["members"].items()
        }
    return item


def _render(data: dict[str, Any]) -> str:
    """Render data the same way every time."""
    return json.dumps(data, indent=1, sort_keys=True) + "\n"


def main() -> int:
    """Write the trimmed files, or check them with --check."""
    files = {
        OUTPUT / "endpoints.json": _render(_endpoints()),
        OUTPUT / SERVICE / API_VERSION / "service-2.json": _render(_service_model()),
    }
    check = "--check" in sys.argv[1:]
    stale = []
    for path, content in files.items():
        if path.exists() and path.read_text(encoding="utf-8") == content:
            continue
        stale.append(path)
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    if check and stale:
        names = ", ".join(str(path.relative_to(OUTPUT)) for path in stale)
        print(f"Out of date: {names}. Run {Path(__file__).name}.")  # noqa: T201
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
