from pydantic import BaseModel, ConfigDict, Field


class GHLContact(BaseModel):
    """The parts of a GoHighLevel contact we use. Aliases are GoHighLevel's field names."""

    # GoHighLevel sends many fields we do not need; ignore them.
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str | None = None
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    company_name: str | None = Field(default=None, alias="companyName")
