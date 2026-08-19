"""Input schema for a discovery-meeting workflow run."""

from pydantic import BaseModel, Field


class DiscoveryMeetingInput(BaseModel):
    company_name: str = Field(..., min_length=1)
    known_challenges: str = Field(..., min_length=1)
    stakeholders: str = Field(..., min_length=1)
    raw_meeting_notes: str = Field(..., min_length=1)
