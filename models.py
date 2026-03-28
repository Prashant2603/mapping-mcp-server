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


class FullFileContent(BaseModel):
    file_path: str
    content: str


class MappingContext(BaseModel):
    source_format_query: str
    target_format_query: str
    reference_mapping_sets: list[FullFileContent]
    format_definitions: list[FullFileContent]
    relevant_functions: list[SearchResult]
    xml_skeleton: str
