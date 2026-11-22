"""Models are substituted; persistence and HTTP handling use real libraries."""

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from src.pipeline import RAGPipeline


class FakeEmbeddingModel:
    def __init__(self):
        self.encoded = []

    def encode(self, texts, **kwargs):
        self.encoded.extend(texts)
        rows = []
        for text in texts:
            values = np.array(list(hashlib.sha256(text.encode()).digest()[:16]), dtype=float) + 1
            rows.append(values / np.linalg.norm(values))
        return np.array(rows)


@pytest.fixture
def pipeline_factory(tmp_path):
    created = []

    def factory():
        model = FakeEmbeddingModel()
        generator = MagicMock()
        generator.generate_answer.return_value = ("A supported answer [1].", [])
        router = MagicMock()
        router.route_query.return_value = "DIRECT_KNOWLEDGE"
        pipeline = RAGPipeline(
            data_dir=str(tmp_path / "data"), db_path=str(tmp_path / "chroma"),
            embedding_model=model, llm_generator=generator, router=router,
        )
        Path(pipeline.data_dir).mkdir(exist_ok=True)
        created.append(pipeline)
        return pipeline

    yield factory
    for pipeline in reversed(created):
        pipeline.close()


@pytest.fixture
def rag(pipeline_factory):
    return pipeline_factory()
