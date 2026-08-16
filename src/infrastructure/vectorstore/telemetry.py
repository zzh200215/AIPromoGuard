"""ChromaDB 遥测 no-op 实现：合规场景不向任何外部服务发送匿名数据。"""

from chromadb.telemetry.product import ProductTelemetryClient, ProductTelemetryEvent
from overrides import override


class NoopTelemetryClient(ProductTelemetryClient):
    @override
    def capture(self, event: ProductTelemetryEvent) -> None:
        return None
