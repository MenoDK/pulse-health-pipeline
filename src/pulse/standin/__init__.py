"""Stand-ins for the two systems this pipeline talks to: a source registry and a national gateway.

They exist so the whole pipeline can run, and fail on purpose, on a laptop. They hold their state in memory, they
serve fictitious data, and their `/control` endpoints exist only when `STANDIN_CONTROL` is set.
"""
