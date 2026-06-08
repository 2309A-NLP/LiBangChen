from app.core.config import Settings
from app.services.embeddings import EmbeddingService


def test_embedding_service_uses_local_model_path(monkeypatch):
    captured: dict[str, object] = {}

    class FakeModel:
        def encode(
            self,
            texts,
            normalize_embeddings=True,
            batch_size=None,
            show_progress_bar=None,
        ):
            captured["batch_size"] = batch_size
            captured["show_progress_bar"] = show_progress_bar
            return [[0.1, 0.2, 0.3] for _ in texts]

    def fake_load_model(model_name: str, device: str):
        captured["model_name"] = model_name
        captured["device"] = device
        return FakeModel()

    monkeypatch.setattr(EmbeddingService, "_load_model", staticmethod(fake_load_model))

    service = EmbeddingService(
        Settings(
            embedding_model_name=r"E:\Role_playing system\Role_playing system\models\bge-m3",
            embedding_device="cpu",
            embedding_batch_size=48,
        )
    )
    vector = service.embed_query("test")

    assert captured["model_name"] == r"E:\Role_playing system\Role_playing system\models\bge-m3"
    assert captured["device"] == "cpu"
    assert captured["batch_size"] == 48
    assert captured["show_progress_bar"] is False
    assert vector == [0.1, 0.2, 0.3]
