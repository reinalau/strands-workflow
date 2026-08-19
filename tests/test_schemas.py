"""Tests for src/models/schemas.py"""

import pytest
from pydantic import ValidationError

from src.models.schemas import DiscoveryMeetingInput

VALID_PAYLOAD = dict(
    company_name="Acme Corp",
    known_challenges="Legacy systems",
    stakeholders="Jane (CTO)",
    raw_meeting_notes="Discussed migration timeline.",
)


def test_valid_input_parses():
    obj = DiscoveryMeetingInput(**VALID_PAYLOAD)
    assert obj.company_name == "Acme Corp"


@pytest.mark.parametrize("missing_field", list(VALID_PAYLOAD.keys()))
def test_missing_required_field_raises(missing_field):
    payload = VALID_PAYLOAD.copy()
    del payload[missing_field]
    with pytest.raises(ValidationError):
        DiscoveryMeetingInput(**payload)


@pytest.mark.parametrize("empty_field", list(VALID_PAYLOAD.keys()))
def test_empty_string_field_raises(empty_field):
    payload = VALID_PAYLOAD.copy()
    payload[empty_field] = ""
    with pytest.raises(ValidationError):
        DiscoveryMeetingInput(**payload)
