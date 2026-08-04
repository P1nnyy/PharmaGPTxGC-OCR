"""Repositories: the only place Cypher is written.

Each module owns the queries for one slice of the graph and returns plain
dicts. Nothing above this layer should know Neo4j exists.
"""
