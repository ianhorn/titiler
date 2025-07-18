"""telemetry tests"""

import os

import pytest
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from starlette.testclient import TestClient

from titiler.core import telemetry
from titiler.core.factory import TilerFactory

TEST_URL = f"file://{os.path.join(os.path.dirname(__file__), 'fixtures', 'cog.tif')}"
TEST_Z, TEST_X, TEST_Y = 8, 84, 47


@pytest.fixture
def telemetry_disabled(monkeypatch):
    """Fixture to simulate OTel being disabled by monkeypatching the tracer."""
    monkeypatch.setattr("titiler.core.telemetry.tracer", None)
    monkeypatch.setattr("titiler.core.telemetry.factory_trace.decorator_enabled", False)


@pytest.fixture
def memory_exporter():
    """Fixture to configure an in-memory exporter for capturing spans."""
    tracer_provider = TracerProvider()
    exporter = InMemorySpanExporter()
    processor = SimpleSpanProcessor(exporter)
    tracer_provider.add_span_processor(processor)

    original_provider = trace.get_tracer_provider()
    trace.set_tracer_provider(tracer_provider)

    yield exporter

    exporter.shutdown()
    trace.set_tracer_provider(original_provider)


def test_tracing_disabled_noop(telemetry_disabled):
    """Test that the application works correctly when OTel is not installed."""
    assert not telemetry.tracer
    assert not telemetry.factory_trace.decorator_enabled

    app = FastAPI()
    tiler = TilerFactory(router_prefix="cog")
    app.include_router(tiler.router, prefix="/cog")
    client = TestClient(app)

    response = client.get(
        f"/cog/tiles/WebMercatorQuad/{TEST_Z}/{TEST_X}/{TEST_Y}.png",
        params={
            "url": TEST_URL,
        },
    )
    assert response.status_code == 200


def test_tracing_enabled_but_not_available_warning(telemetry_disabled):
    """Test that enabling telemetry without the decorator enabled emits a warning."""
    assert not telemetry.tracer
    assert not telemetry.factory_trace.decorator_enabled

    with pytest.warns(match="tracing is not available"):
        _ = TilerFactory(router_prefix="cog", enable_telemetry=True)


def test_tracing_enabled_success_path(memory_exporter):
    """Test that spans are correctly created on a successful request."""
    assert telemetry.tracer
    assert telemetry.factory_trace.decorator_enabled

    app = FastAPI()
    tiler = TilerFactory(router_prefix="cog", enable_telemetry=True)
    app.include_router(tiler.router, prefix="/cog")
    client = TestClient(app)

    response = client.get(
        f"/cog/tiles/WebMercatorQuad/{TEST_Z}/{TEST_X}/{TEST_Y}.png",
        params={
            "url": TEST_URL,
        },
    )
    assert response.status_code == 200

    finished_spans = memory_exporter.get_finished_spans()
    assert len(finished_spans) == 1

    span = next(filter(lambda x: x.name == "TilerFactory.tile", finished_spans), None)
    assert span
    assert span.status.status_code == StatusCode.OK
