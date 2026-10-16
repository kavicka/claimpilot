"""Extraction output schemas: every field becomes value + quote + page.

The quote is the exact text the model read the value from; grounding matches it back to a parsed
block to get the bounding box, and a quote that matches nothing marks the value as ungrounded.
"""

import typing
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field, create_model

from claimpilot_core.domain import DocType
from claimpilot_core.schemas.documents import SCHEMAS


class GroundedValue(BaseModel):
    value: str | None = Field(description="The value exactly as printed, or null if absent")
    quote: str | None = Field(description="The exact text on the page that contains the value")
    page: int | None = Field(description="Page number where the quote is")


class GroundedList(BaseModel):
    values: list[str] = Field(description="Every value, exactly as printed")
    quote: str | None = Field(description="The exact text on the page that contains them")
    page: int | None = Field(description="Page number")


def _list_item_model(item: type[BaseModel]) -> type[BaseModel]:
    fields: dict[str, Any] = {
        name: (str | None, Field(description=f.description or name))
        for name, f in item.model_fields.items()
    }
    fields["quote"] = (str | None, Field(description="The exact row or line on the page"))
    fields["page"] = (int | None, Field(description="Page number"))
    return create_model(f"Grounded{item.__name__}", **fields)


def _is_list_of_models(ann: Any) -> type[BaseModel] | None:
    if typing.get_origin(ann) is list:
        (arg,) = typing.get_args(ann)
        if isinstance(arg, type) and issubclass(arg, BaseModel):
            return arg
    return None


@lru_cache
def grounded_model(doc_type: DocType) -> type[BaseModel]:
    return grounded_schema(SCHEMAS[doc_type])


@lru_cache
def grounded_schema(base: type[BaseModel]) -> type[BaseModel]:
    """Any field set (claim documents, invoice headers) as value + quote + page per field."""
    fields: dict[str, Any] = {}
    for name, f in base.model_fields.items():
        item = _is_list_of_models(f.annotation)
        if item is not None:
            fields[name] = (list[_list_item_model(item)], Field(description=f.description or name))
        elif typing.get_origin(f.annotation) is list:
            fields[name] = (GroundedList, Field(description=f.description or name))
        else:
            fields[name] = (GroundedValue, Field(description=f.description or name))
    return create_model(f"{base.__name__}Extraction", **fields)


def field_guide(doc_type: DocType) -> str:
    """Field names and descriptions for the prompt."""
    return schema_guide(SCHEMAS[doc_type])


def schema_guide(base: type[BaseModel]) -> str:
    lines = []
    for name, f in base.model_fields.items():
        item = _is_list_of_models(f.annotation)
        if item is not None:
            sub = ", ".join(item.model_fields)
            lines.append(f"- {name} (list, one entry per row with {sub}): {f.description or ''}")
        else:
            lines.append(f"- {name}: {f.description or ''}")
    return "\n".join(lines)
