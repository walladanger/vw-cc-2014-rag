import math
import unittest
import urllib.error
from unittest.mock import patch, MagicMock

from vag_pipeline.embeddings import OllamaEmbedder

class TestOllamaEmbedder(unittest.TestCase):
    def test_init_strips_trailing_slashes(self):
        embedder = OllamaEmbedder("http://localhost:11434/", "model")
        self.assertEqual(embedder.base_url, "http://localhost:11434")
        self.assertIsNone(embedder.dimension)

    def test_normalize_returns_unit_length_vector(self):
        vector = [1.0, 2.0, 3.0]
        normalized = OllamaEmbedder._normalize(vector)
        length = math.sqrt(sum(v * v for v in normalized))
        self.assertTrue(math.isclose(length, 1.0))

    def test_normalize_all_zeros(self):
        vector = [0.0, 0.0, 0.0]
        normalized = OllamaEmbedder._normalize(vector)
        self.assertEqual(normalized, [0.0, 0.0, 0.0])

    @patch.object(OllamaEmbedder, "_post")
    def test_embed_empty_list(self, mock_post):
        embedder = OllamaEmbedder("http://localhost", "model")
        result = embedder.embed([])
        self.assertEqual(result, [])
        mock_post.assert_not_called()

    @patch.object(OllamaEmbedder, "_post")
    def test_embed_success(self, mock_post):
        embedder = OllamaEmbedder("http://localhost", "model")
        mock_post.return_value = {"embeddings": [[1.0, 0.0, 0.0], [0.0, 2.0, 0.0]]}
        result = embedder.embed(["text1", "text2"])

        mock_post.assert_called_once_with("/api/embed", {"model": "model", "input": ["text1", "text2"]})
        self.assertEqual(result, [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        self.assertEqual(embedder.dimension, 3)

    @patch.object(OllamaEmbedder, "_post")
    def test_embed_fallback_on_httperror(self, mock_post):
        embedder = OllamaEmbedder("http://localhost", "model")

        def side_effect(route, body):
            if route == "/api/embed":
                raise urllib.error.HTTPError("url", 404, "Not Found", {}, None)
            if route == "/api/embeddings":
                return {"embedding": [0.0, 0.0, 1.0]}

        mock_post.side_effect = side_effect
        result = embedder.embed(["text1", "text2"])

        self.assertEqual(mock_post.call_count, 3) # 1 for /api/embed, 2 for /api/embeddings
        mock_post.assert_any_call("/api/embed", {"model": "model", "input": ["text1", "text2"]})
        mock_post.assert_any_call("/api/embeddings", {"model": "model", "prompt": "text1"})
        mock_post.assert_any_call("/api/embeddings", {"model": "model", "prompt": "text2"})

        self.assertEqual(result, [[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]])

    @patch.object(OllamaEmbedder, "_post")
    def test_embed_fallback_on_keyerror(self, mock_post):
        embedder = OllamaEmbedder("http://localhost", "model")

        def side_effect(route, body):
            if route == "/api/embed":
                return {} # Missing "embeddings" key
            if route == "/api/embeddings":
                return {"embedding": [1.0, 0.0, 0.0]}

        mock_post.side_effect = side_effect
        result = embedder.embed(["text1"])

        self.assertEqual(mock_post.call_count, 2)
        mock_post.assert_any_call("/api/embed", {"model": "model", "input": ["text1"]})
        mock_post.assert_any_call("/api/embeddings", {"model": "model", "prompt": "text1"})

        self.assertEqual(result, [[1.0, 0.0, 0.0]])

    @patch.object(OllamaEmbedder, "embed")
    def test_embed_batches(self, mock_embed):
        embedder = OllamaEmbedder("http://localhost", "model")
        mock_embed.side_effect = lambda batch: [["mocked"] for _ in batch]

        texts = ["t1", "t2", "t3", "t4", "t5"]
        results = list(embedder.embed_batches(texts, batch_size=2))

        self.assertEqual(len(results), 3)
        mock_embed.assert_any_call(["t1", "t2"])
        mock_embed.assert_any_call(["t3", "t4"])
        mock_embed.assert_any_call(["t5"])

    @patch.object(OllamaEmbedder, "embed")
    def test_embed_batches_empty(self, mock_embed):
        embedder = OllamaEmbedder("http://localhost", "model")
        results = list(embedder.embed_batches([], batch_size=2))
        self.assertEqual(len(results), 0)
        mock_embed.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_post_builds_url_sends_json(self, mock_urlopen):
        embedder = OllamaEmbedder("http://localhost", "model", timeout=123)

        mock_response = MagicMock()
        mock_response.read.return_value = b'{"status": "ok"}'

        mock_context_manager = MagicMock()
        mock_context_manager.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_context_manager

        result = embedder._post("/api/test", {"key": "value"})

        self.assertEqual(result, {"status": "ok"})
        mock_urlopen.assert_called_once()
        request_arg = mock_urlopen.call_args[0][0]

        self.assertEqual(request_arg.full_url, "http://localhost/api/test")
        self.assertEqual(request_arg.data, b'{"key": "value"}')
        self.assertEqual(request_arg.headers.get("Content-type"), "application/json")
        self.assertEqual(mock_urlopen.call_args[1]["timeout"], 123)

if __name__ == "__main__":
    unittest.main()
