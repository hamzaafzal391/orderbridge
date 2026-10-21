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
    email: str | None = None


class GHLCustomFieldValue(BaseModel):
    """One custom-field value on a deal. GoHighLevel names the field by id and leaves out
    fields that were never filled in."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    field_value: str | int | float | bool | None = Field(default=None, alias="fieldValue")


class GHLOpportunity(BaseModel):
    """The parts of a GoHighLevel opportunity (deal) we use."""

    model_config = ConfigDict(extra="ignore")

    id: str
    location_id: str = Field(alias="locationId")
    pipeline_id: str = Field(alias="pipelineId")
    status: str
    contact_id: str | None = Field(default=None, alias="contactId")
    # Absent (or null) when no custom field has a value.
    custom_fields: list[GHLCustomFieldValue] | None = Field(default=None, alias="customFields")


class GHLCustomFieldDefinition(BaseModel):
    """What a custom field is called: its id (used in deal values) and its stable key."""

    model_config = ConfigDict(extra="ignore")

    id: str
    field_key: str = Field(alias="fieldKey")
