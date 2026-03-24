"""Pydantic models for MCP tool request/response schemas."""

from pydantic import BaseModel


class SearchResult(BaseModel):
    source_type: str
    file_path: str
    snippet: str
    score: float


class FormatInfo(BaseModel):
    name: str
    file_path: str
    extension: str
    short_description: str


class MappingSetInfo(BaseModel):
    name: str
    file_path: str
    source_target_info: str
    summary: str


class MappingSetDetail(BaseModel):
    file_path: str
    raw_content: str
    metadata: dict


class MappingContext(BaseModel):
    relevant_formats: list[SearchResult]
    similar_mapping_sets: list[SearchResult]
    relevant_functions: list[SearchResult]
    xml_skeleton: str
