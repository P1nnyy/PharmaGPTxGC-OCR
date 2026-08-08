"""Invoice ingestion and presentation.

Holds the orchestration that used to sit inline in the upload route handlers:
validating an upload, running it through an extraction engine, and persisting
the result to object storage and the graph.
"""
