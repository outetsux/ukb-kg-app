"""Versioned graph layout and validated Cypher identifiers from release data."""
import re

SCHEMA_VERSION = 2


def identifier(value):
    # Only release identifiers are interpolated; names/user input stay parameters.
    if not isinstance(value, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]*(?:-[A-Z][A-Z0-9_]*)?', value):
        raise ValueError('Invalid release entity label or relationship type.')
    return '`' + value + '`'
