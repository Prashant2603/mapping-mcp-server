You are an expert backend engineer and Model Context Protocol (MCP) implementer with strong experience in:

Python (3.10+)
RAG systems (retrieval-augmented generation)
Vector databases (e.g., Chroma, FAISS, Qdrant)
Designing tools/resources for LLM orchestration (e.g., MCP, tool-calling)


Goal
Build a Python MCP server that:

Runs on localhost:8000
Implements a RAG layer over a local folder structure
Indexes all relevant files into a vector database
Exposes MCP tools that allow an LLM (via a Copilot connector) to:

Generate new mapping sets (in XML format)
Explore and query existing mapping sets
Understand and use a custom function library (via its README/docs)



I will later plug this MCP into a Copilot connector. Your job is to design and implement the server and tools so that any LLM using MCP can retrieve the right context and generate mapping sets reliably.

Domain & Use Case
Concept: Mapping Set

A mapping set is an XML file that describes how to convert Target A into Target B.
The mapping uses a set of functions defined in my custom function library.
Files in this ecosystem can be in XML / CSV / JSON formats.

Folder Structure
Assume a root folder (configurable) with 3 main subfolders:

formats/

Contains format files describing schemas/structures for inputs and outputs.
Formats can be XML / CSV / JSON.


mapping_sets/

Contains sample mapping set files (primarily XML).
These are real examples of how Target A → Target B mappings are written using my custom functions.


functions_docs/

Contains README / documentation files describing the functions available in my custom library.
These can be markdown, text, or similar.
The content explains function names, parameters, behavior, and examples.



The MCP server should index everything in these folders into a vector database for semantic search.

RAG Behavior Requirements
Implement a RAG layer with the following behavior:

Startup Indexing

On server startup:

Recursively scan the configured root directory.
Load and index:

All files under formats/
All files under mapping_sets/
All files under functions_docs/


For each file, store:

File path
File type (format / mapping_set / functions_doc)
File extension (xml, csv, json, md, txt, etc.)
Content (as text)


Chunk documents intelligently for semantic search (e.g., by sections, tags, or size).




Vector Database

Use a local vector database that is easy to run without external services (e.g., Chroma or FAISS).
Use a common text-embedding model (e.g., via sentence-transformers in Python).
Design the code so the embedding model and vector DB can be swapped/configured easily.


Retrieval

Provide a generic retrieval function that:

Accepts a natural language query and optional filters (e.g., by folder type: formats, mapping_sets, functions_docs).
Returns the most relevant chunks with metadata.




LLM-Oriented Results

Retrieval responses should be LLM-friendly, e.g.:

source_type (format | mapping_set | functions_doc)
file_path
snippet (plain text or XML/JSON/etc. fragment)
Optional score






MCP API / Tools Design
Design the MCP server to expose clear tools that an LLM can call. At a minimum, include tools like:

list_formats

Purpose: List all known format files and basic info.
Inputs: Optional filter (e.g., by file extension).
Outputs: Array of objects with:

name
file_path
extension
short_description (if derivable from content)




list_mapping_sets

Purpose: List all mapping sets available.
Outputs: Array of objects with:

name
file_path
source_target_info (e.g., TargetA → TargetB if you can infer from XML)
summary (short text summary if possible)




get_mapping_set_details

Purpose: Get the full content of a specific mapping set by name or path.
Inputs: mapping_set_id or file_path.
Outputs:

Raw content (XML or other)
Optional parsed metadata (e.g., target systems, version).




search_docs

Purpose: Generic semantic search over all indexed content.
Inputs:

query (string)
Optional source_type filter (format, mapping_set, functions_doc)
Optional top_k


Outputs:

Array of search results with:

source_type
file_path
snippet
score






search_functions

Purpose: Semantic search focused only on function documentation (under functions_docs/).
Inputs: query, optional top_k.
Outputs: Similar to search_docs, but limited to functions docs.


generate_mapping_context

Purpose: Prepare all relevant context needed for an LLM to generate a new mapping set (XML) from Target A to Target B.
Inputs:

source_format (string identifier)
target_format (string identifier)
Optional natural-language description of the mapping request.


Behavior:

Use semantic search to:

Find the most relevant formats for the given source/target.
Find similar existing mapping sets (so the LLM can use them as patterns).
Find relevant functions from the function documentation.


Return a JSON object that includes:

relevant_formats (with snippets + file paths)
similar_mapping_sets (with key snippets + file paths)
relevant_functions (summaries/snippets + file paths)
A suggested XML skeleton/template for the new mapping set (without making assumptions that require domain knowledge you cannot infer).




Note: This tool should not call another LLM. It simply gathers and structures context so that the main LLM (using MCP) can generate the final XML mapping set.



Feel free to propose additional tools if they make the LLM–MCP interaction cleaner or more powerful.

Technical & Architectural Requirements

Language & Framework

Use Python 3.10+.
Implement the MCP server logic with a simple, well-supported framework (e.g., FastAPI or similar) while respecting MCP conventions (tools, schemas, JSON-based I/O).
Expose the server on port 8000.


Code Structure

Organize code into clear modules, for example:

main.py – entrypoint, server startup.
mcp_server.py – MCP server & tool registration.
rag_index.py – indexing & retrieval logic, vector DB setup.
models.py – Pydantic models / dataclasses for request/response schemas.
config.py – configuration (root folder path, DB path, embedding model name, etc.).


Use type hints everywhere and docstrings for public functions.


Configuration

Allow configuring:

Root data directory (where formats/, mapping_sets/, functions_docs/ live).
Vector DB persistence location.
Embedding model name.


Provide reasonable defaults (e.g., ./data, ./vector_store).


Error Handling & Robustness

Handle missing folders or files gracefully (e.g., log warnings instead of crashing).
Validate tool inputs and return clear error messages for invalid parameters.


Documentation

Provide:

A short README-style explanation (in comments or a separate string) describing:

How to install dependencies.
How to run the server.
How the MCP tools are meant to be used by an LLM.






Testing / Examples

Include at least:

Example code snippet or pseudo-calls showing how each MCP tool would be invoked and what kind of JSON response it returns.
A small in-code example of a mock folder structure (even as comments) to illustrate usage.






Output Expectations

Provide the full Python code for the MCP server, split into logical files (you can show them one after another with clear file names like # file: main.py).
Ensure the code is runnable end-to-end, with:

Server startup
Indexing on startup
Working MCP tools as defined above.


At the end, include a short “How to run & test” section, including:

Installation steps (e.g., pip install ...).
Command to start the server.
Example MCP tool calls (with example JSON request/response).



If anything in the requirements is ambiguous or you see a better design for LLM–MCP interaction in this context, first explain your proposed design and ask any clarifying questions before you start writing code.

