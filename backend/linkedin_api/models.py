"""
Pydantic models for LinkedIn person / profile data.

Used by PersonScraper to return structured results.
"""

from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class Interest(BaseModel):
    name: str
    category: str
    linkedin_url: Optional[str] = None


class Contact(BaseModel):
    type: str
    value: str
    label: Optional[str] = None


class Experience(BaseModel):
    """Work experience."""
    position_title: Optional[str] = None
    institution_name: Optional[str] = None
    linkedin_url: Optional[str] = None
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    duration: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None


class Education(BaseModel):
    """Education entry."""
    institution_name: Optional[str] = None
    degree: Optional[str] = None
    linkedin_url: Optional[str] = None
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    description: Optional[str] = None


class Accomplishment(BaseModel):
    category: str
    title: str
    issuer: Optional[str] = None
    issued_date: Optional[str] = None
    credential_id: Optional[str] = None
    credential_url: Optional[str] = None
    description: Optional[str] = None


class PeopleSearchResult(BaseModel):
    """A single person from LinkedIn people search results."""
    name: str
    headline: Optional[str] = None
    location: Optional[str] = None
    linkedin_url: str

    def __repr__(self) -> str:
        return f"<PeopleSearchResult {self.name} | {self.headline} | {self.location}>"


class PeopleSearchResponse(BaseModel):
    """Full response from a people search query."""
    query_keywords: str
    query_location: Optional[str] = None
    results: List["PeopleSearchResult"] = Field(default_factory=list)
    total_pages_scraped: int = 0

    @property
    def total_results(self) -> int:
        return len(self.results)

    def to_dict(self) -> dict:
        return self.model_dump()

    def to_json(self, **kwargs) -> str:
        return self.model_dump_json(**kwargs)


class Person(BaseModel):
    """Full LinkedIn profile with all scraped sections."""

    linkedin_url: str
    name: Optional[str] = None
    location: Optional[str] = None
    about: Optional[str] = None
    open_to_work: bool = False
    experiences: List[Experience] = Field(default_factory=list)
    educations: List[Education] = Field(default_factory=list)
    interests: List[Interest] = Field(default_factory=list)
    accomplishments: List[Accomplishment] = Field(default_factory=list)
    contacts: List[Contact] = Field(default_factory=list)

    @field_validator("linkedin_url")
    @classmethod
    def validate_linkedin_url(cls, v: str) -> str:
        if "linkedin.com/in/" not in v:
            raise ValueError("Must be a valid LinkedIn profile URL (contains /in/)")
        return v

    def to_dict(self) -> dict:
        return self.model_dump()

    def to_json(self, **kwargs) -> str:
        return self.model_dump_json(**kwargs)

    @property
    def company(self) -> Optional[str]:
        if self.experiences:
            return self.experiences[0].institution_name
        return None

    @property
    def job_title(self) -> Optional[str]:
        if self.experiences:
            return self.experiences[0].position_title
        return None

    def __repr__(self) -> str:
        return (
            f"<Person {self.name}"
            f" | {self.job_title} @ {self.company}"
            f" | {self.location}"
            f" | exp={len(self.experiences)} edu={len(self.educations)}>"
        )
