"""Small pgvector SQLAlchemy adapter; SQLite metadata uses JSON in tests."""
import json
import math
from sqlalchemy.types import UserDefinedType
from sqlalchemy.dialects.postgresql.base import ischema_names


DIMENSIONS = 384


def validate_vector(value):
    result = [float(item) for item in value]
    if len(result) != DIMENSIONS or not all(math.isfinite(item) for item in result) or not any(result):
        raise ValueError("Expected a finite nonzero 384-dimensional embedding.")
    return result


class Vector(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions=384):
        self.dimensions = int(dimensions)

    def get_col_spec(self, **kwargs):
        return f"public.VECTOR({self.dimensions})"

    def bind_processor(self, dialect):
        return lambda value: json.dumps(validate_vector(value)) if value is not None else None

    def result_processor(self, dialect, coltype):
        return lambda value: json.loads(value) if isinstance(value, str) else value


ischema_names.setdefault("vector", Vector)
