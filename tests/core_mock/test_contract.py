"""Contract tests generated from core_mock's published OpenAPI spec (Schemathesis): every
response must match the spec, including the error responses it documents."""

import os
from pathlib import Path

import schemathesis
from hypothesis import HealthCheck, settings

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("CORE_MOCK_POLICIES", str(ROOT / "data" / "synthetic" / "policies.json"))
os.environ.setdefault("CORE_MOCK_PRODUCTS", str(ROOT / "data" / "policies" / "products.yaml"))

from schemathesis.specs.openapi.checks import positive_data_acceptance  # noqa: E402

from claimpilot_core_mock.main import app  # noqa: E402

schema = schemathesis.openapi.from_asgi("/openapi.json", app)


@schema.parametrize()
@settings(max_examples=25, deadline=None, suppress_health_check=list(HealthCheck))
def test_api_matches_its_spec(case):
    # Business validations (unknown policy, totals that do not add up) reject schema-valid data on
    # purpose with field-level 422s, so the "positive data is accepted" check does not apply.
    case.call_and_validate(
        headers={"Idempotency-Key": "contract"}, excluded_checks=[positive_data_acceptance]
    )
