"""Embedding engine for CLAW.

Wraps sentence-transformers for encode/cosine_similarity and provides
sqlite-vec compatible storage via binary serialization.

Supports four embedding backends:
  1. OpenRouter API (OpenAI-compatible /v1/embeddings) — for models like
     perplexity/pplx-embed-v1-4b, google/gemini-embedding-2-preview, etc.
     Detected when model name contains a "/" (provider/model format).
  2. Gemini direct API (google.genai) — for gemini-embedding-* models
     called directly against Google's API (requires GOOGLE_API_KEY).
  3. Local deterministic hash embeddings — for zero-cost automation paths.
  4. Local sentence-transformers — for models like all-MiniLM-L6-v2.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import struct
import time
from typing import Optional

import numpy as np

from claw.core.config import EmbeddingsConfig
from claw.core.exceptions import ConfigError

logger = logging.getLogger("claw.embeddings")

# Lazy import — sentence-transformers is heavy and requires torch
_SentenceTransformer = None
_SENTENCE_TRANSFORMERS_AVAILABLE: bool | None = None

# Retry configuration for API calls (Gemini direct + OpenRouter)
_GEMINI_MAX_ATTEMPTS = 3
_GEMINI_BACKOFF_BASE = 2  # seconds: 2, 4, 8

_OPENROUTER_MAX_ATTEMPTS = 3
_OPENROUTER_BACKOFF_BASE = 2


def _get_sentence_transformer():
    global _SentenceTransformer, _SENTENCE_TRANSFORMERS_AVAILABLE
    if _SENTENCE_TRANSFORMERS_AVAILABLE is False:
        raise ImportError(
            "sentence-transformers is not installed. "
            "Install with: pip install 'claw[ml]'  "
            "Or use Gemini API embeddings (set embeddings.model to a gemini-embedding model in claw.toml)."
        )
    if _SentenceTransformer is None:
        try:
            from sentence_transformers import SentenceTransformer
            _SentenceTransformer = SentenceTransformer
            _SENTENCE_TRANSFORMERS_AVAILABLE = True
        except ImportError:
            _SENTENCE_TRANSFORMERS_AVAILABLE = False
            raise ImportError(
                "sentence-transformers is not installed. "
                "Install with: pip install 'claw[ml]'  "
                "Or use Gemini API embeddings (set embeddings.model to a gemini-embedding model in claw.toml)."
            )
    return _SentenceTransformer


def _is_retryable_gemini_error(exc: Exception) -> bool:
    """Return True if the exception is a transient Gemini/network error worth retrying."""
    # Network-level errors
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True

    # httpx transport errors (lazy check to avoid hard import)
    exc_module = type(exc).__module__ or ""
    if exc_module.startswith("httpx"):
        exc_name = type(exc).__name__
        if exc_name in (
            "ConnectError",
            "TimeoutException",
            "ReadTimeout",
            "WriteTimeout",
            "ConnectTimeout",
            "PoolTimeout",
            "NetworkError",
            "RemoteProtocolError",
        ):
            return True

    # google.genai.errors — ServerError covers all 5xx
    try:
        from google.genai.errors import ServerError, ClientError
        if isinstance(exc, ServerError):
            return True
        # ClientError with 429 (rate limit / resource exhausted)
        if isinstance(exc, ClientError) and getattr(exc, "code", None) == 429:
            return True
    except ImportError:
        pass

    # google.api_core.exceptions (may be raised by underlying transport)
    try:
        from google.api_core import exceptions as gapi_exc
        if isinstance(exc, (
            gapi_exc.TooManyRequests,
            gapi_exc.InternalServerError,
            gapi_exc.BadGateway,
            gapi_exc.ServiceUnavailable,
            gapi_exc.GatewayTimeout,
            gapi_exc.DeadlineExceeded,
        )):
            return True
    except ImportError:
        pass

    return False


class EmbeddingEngine:
    """Encodes text to vectors and provides similarity search utilities.

    Uses all-MiniLM-L6-v2 (384 dimensions) by default.
    Model is loaded lazily on first encode() call.
    """

    def __init__(self, config: Optional[EmbeddingsConfig] = None):
        self.config = config or EmbeddingsConfig()
        self.model_name = self.config.model
        self.dimension = self.config.dimension
        if self.config.required_model and self.model_name != self.config.required_model:
            raise ConfigError(
                f"Embeddings model '{self.model_name}' rejected; "
                f"required model is '{self.config.required_model}'"
            )
        self._model = None
        self._genai_client = None
        self._openrouter_client = None
        # OpenRouter: model name contains "/" (provider/model format) like
        # "perplexity/pplx-embed-v1-4b" or "google/gemini-embedding-2-preview"
        self._uses_openrouter = "/" in self.model_name and not self.model_name.startswith("mlx-")
        # Direct Gemini API: only if NOT routed through OpenRouter
        self._uses_gemini_api = (
            not self._uses_openrouter
            and (self.model_name.startswith("gemini-embedding") or self.model_name.startswith("models/gemini-embedding"))
        )
        self._uses_mlx = self.model_name.startswith("mlx-community/") or self.model_name.startswith("mlx-embeddings:")
        self._uses_hash = self.model_name in {
            "hash-embedding-384",
            "local-hash-embedding",
        }
        self._mlx_model = None

    @property
    def model(self):
        if self._uses_openrouter or self._uses_gemini_api or self._uses_mlx or self._uses_hash:
            return None
        if self._model is None:
            SentenceTransformer = _get_sentence_transformer()
            logger.info("Loading embedding model: %s", self.model_name)
            self._model = SentenceTransformer(self.model_name)
            logger.info("Embedding model loaded (%dD)", self.dimension)
        return self._model

    def _get_mlx_model(self):
        """Lazily load mlx-embeddings model (Apple Silicon only)."""
        if self._mlx_model is None:
            try:
                from mlx_embeddings import load as mlx_load
                model_id = self.model_name
                if model_id.startswith("mlx-embeddings:"):
                    model_id = model_id[len("mlx-embeddings:"):]
                logger.info("Loading MLX embedding model: %s", model_id)
                self._mlx_model = mlx_load(model_id)
                logger.info("MLX embedding model loaded (%dD)", self.dimension)
            except ImportError:
                raise ImportError(
                    "mlx-embeddings is not installed. "
                    "Install with: pip install 'claw[mlx]'"
                )
        return self._mlx_model

    def _embed_with_mlx(self, texts: list[str]) -> list[list[float]]:
        """Encode texts using mlx-embeddings (Apple Silicon)."""
        model = self._get_mlx_model()
        from mlx_embeddings import encode as mlx_encode
        embeddings = mlx_encode(model, texts)
        return [self._normalize_dimension(list(float(x) for x in v)) for v in embeddings]

    def _embed_with_hash(self, texts: list[str]) -> list[list[float]]:
        """Encode texts with deterministic local vectors for zero-cost routing."""
        vectors: list[list[float]] = []
        for text in texts:
            values: list[float] = []
            counter = 0
            seed = text.encode("utf-8", errors="replace")
            while len(values) < self.dimension:
                digest = hashlib.sha256(counter.to_bytes(4, "big") + seed).digest()
                values.extend((byte / 127.5) - 1.0 for byte in digest)
                counter += 1
            vec = values[: self.dimension]
            norm = float(np.linalg.norm(np.array(vec)))
            if norm > 0:
                vec = [value / norm for value in vec]
            vectors.append(vec)
        return vectors

    def _get_openrouter_client(self):
        """Lazily create an httpx client for OpenRouter embeddings API."""
        if self._openrouter_client is None:
            import httpx
            api_key = os.getenv(self.config.api_key_env, "")
            if not api_key:
                raise RuntimeError(
                    f"{self.config.api_key_env} is required for OpenRouter embeddings model '{self.model_name}'"
                )
            self._openrouter_client = httpx.Client(
                base_url="https://openrouter.ai/api/v1",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=60.0,
            )
            logger.info(
                "OpenRouter embedding client initialized (model=%s, dimension=%d)",
                self.model_name,
                self.dimension,
            )
        return self._openrouter_client

    def _embed_with_openrouter(self, texts: list[str]) -> list[list[float]]:
        """Embed texts via OpenRouter's OpenAI-compatible /v1/embeddings endpoint.

        Supports Matryoshka dimension reduction via the 'dimensions' parameter.
        Retries on transient errors with exponential backoff.
        """
        client = self._get_openrouter_client()

        body: dict = {
            "model": self.model_name,
            "input": texts if len(texts) > 1 else texts[0],
            "encoding_format": "float",
        }
        # Request specific dimensionality (Matryoshka reduction for pplx-embed,
        # output_dimensionality for Gemini — OpenRouter normalizes this).
        if self.dimension:
            body["dimensions"] = self.dimension

        text_preview = texts[0][:80] if texts else "<empty>"
        last_exc: Exception | None = None

        for attempt in range(1, _OPENROUTER_MAX_ATTEMPTS + 1):
            try:
                resp = client.post("/embeddings", json=body)
                resp.raise_for_status()
                data = resp.json()

                vectors = []
                for item in data.get("data", []):
                    emb = item.get("embedding", [])
                    vectors.append(self._normalize_dimension([float(v) for v in emb]))

                if not vectors:
                    raise RuntimeError(
                        f"OpenRouter embeddings response contained no vectors: {data}"
                    )
                return vectors

            except Exception as e:
                last_exc = e
                retryable = isinstance(e, (ConnectionError, TimeoutError, OSError))
                # Check for httpx-specific errors
                exc_module = type(e).__module__ or ""
                if exc_module.startswith("httpx"):
                    exc_name = type(e).__name__
                    if exc_name in ("ConnectError", "TimeoutException", "ReadTimeout",
                                    "WriteTimeout", "PoolTimeout", "NetworkError"):
                        retryable = True
                    # Retry on 429 and 5xx
                    if hasattr(e, "response") and hasattr(e.response, "status_code"):
                        sc = e.response.status_code
                        if sc == 429 or sc >= 500:
                            retryable = True

                if attempt < _OPENROUTER_MAX_ATTEMPTS and retryable:
                    backoff = _OPENROUTER_BACKOFF_BASE ** attempt
                    logger.warning(
                        "OpenRouter embed transient error (attempt %d/%d, "
                        "backoff %ds, text='%s...'): %s",
                        attempt, _OPENROUTER_MAX_ATTEMPTS, backoff,
                        text_preview, e,
                    )
                    time.sleep(backoff)
                    continue
                break

        raise RuntimeError(f"OpenRouter embeddings call failed: {last_exc}") from last_exc

    def _get_genai_client(self):
        if self._genai_client is None:
            api_key = os.getenv(self.config.api_key_env, "")
            if not api_key:
                raise RuntimeError(
                    f"{self.config.api_key_env} is required for Gemini embeddings model '{self.model_name}'"
                )
            from google import genai

            self._genai_client = genai.Client(
                api_key=api_key,
                http_options={"timeout": 30_000},  # 30s timeout to prevent CLOSE_WAIT hangs
            )
            logger.info(
                "Gemini embedding client initialized (model=%s, dimension=%d)",
                self.model_name,
                self.dimension,
            )
        return self._genai_client

    def _normalize_dimension(self, vec: list[float]) -> list[float]:
        if len(vec) == self.dimension:
            return vec
        if len(vec) > self.dimension:
            return vec[:self.dimension]
        if len(vec) < self.dimension:
            return vec + [0.0] * (self.dimension - len(vec))
        return vec

    @staticmethod
    def _extract_values_from_genai_response(resp: object) -> list[list[float]]:
        # SDK response shapes vary by endpoint/version:
        # - resp.embedding.values (single)
        # - resp.embeddings[i].values (batch)
        if hasattr(resp, "embeddings") and getattr(resp, "embeddings"):
            vectors = []
            for emb in getattr(resp, "embeddings"):
                values = getattr(emb, "values", None)
                if values is not None:
                    vectors.append([float(v) for v in values])
            if vectors:
                return vectors

        if hasattr(resp, "embedding") and getattr(resp, "embedding") is not None:
            emb = getattr(resp, "embedding")
            values = getattr(emb, "values", None)
            if values is not None:
                return [[float(v) for v in values]]

        return []

    def _embed_with_gemini(self, texts: list[str]) -> list[list[float]]:
        """Embed texts via Gemini API with retry and exponential backoff.

        Retries up to _GEMINI_MAX_ATTEMPTS times on transient errors
        (network failures, 429 rate-limit, 5xx server errors) with
        exponential backoff (2s, 4s, 8s).
        """
        client = self._get_genai_client()
        from google.genai import types

        embed_cfg = {
            "output_dimensionality": self.dimension,
        }
        if self.config.task_type:
            embed_cfg["task_type"] = self.config.task_type

        text_preview = texts[0][:80] if texts else "<empty>"
        last_exc: Exception | None = None

        for attempt in range(1, _GEMINI_MAX_ATTEMPTS + 1):
            try:
                resp = client.models.embed_content(
                    model=self.model_name,
                    contents=texts if len(texts) > 1 else texts[0],
                    config=types.EmbedContentConfig(**embed_cfg),
                )
                vectors = self._extract_values_from_genai_response(resp)
                if not vectors:
                    raise RuntimeError("Gemini embeddings response contained no vectors")
                return [self._normalize_dimension(v) for v in vectors]
            except Exception as e:
                last_exc = e
                if attempt < _GEMINI_MAX_ATTEMPTS and _is_retryable_gemini_error(e):
                    backoff = _GEMINI_BACKOFF_BASE ** attempt  # 2, 4, 8
                    logger.warning(
                        "Gemini embed_content transient error (attempt %d/%d, "
                        "backoff %ds, text='%s...'): %s",
                        attempt,
                        _GEMINI_MAX_ATTEMPTS,
                        backoff,
                        text_preview,
                        e,
                    )
                    time.sleep(backoff)
                    continue
                # Non-retryable or final attempt -- fall through
                if attempt >= _GEMINI_MAX_ATTEMPTS and _is_retryable_gemini_error(e):
                    logger.error(
                        "Gemini embed_content failed after %d attempts "
                        "(text='%s...'): %s",
                        _GEMINI_MAX_ATTEMPTS,
                        text_preview,
                        e,
                    )
                break

        raise RuntimeError(f"Gemini embeddings call failed: {last_exc}") from last_exc

    def close(self) -> None:
        """Release resources held by the embedding engine.

        Closes the Gemini genai.Client and/or OpenRouter httpx client
        to prevent CLOSE_WAIT socket leaks.
        """
        if self._openrouter_client is not None:
            try:
                self._openrouter_client.close()
            except Exception as e:
                logger.debug("EmbeddingEngine.close() OpenRouter client error: %s", e)
            finally:
                self._openrouter_client = None
                logger.debug("OpenRouter embedding client closed")

        if self._genai_client is not None:
            try:
                # google-genai Client wraps httpx; call close if available
                close_fn = getattr(self._genai_client, "close", None)
                if callable(close_fn):
                    close_fn()
                # Also close the internal httpx client if exposed
                _http = getattr(self._genai_client, "_client", None)
                if _http is not None:
                    close_fn2 = getattr(_http, "close", None)
                    if callable(close_fn2):
                        close_fn2()
            except Exception as e:
                logger.debug("EmbeddingEngine.close() ignoring error: %s", e)
            finally:
                self._genai_client = None
                logger.debug("Gemini genai client closed")

    def encode(self, text: str) -> list[float]:
        """Encode a single text string to a vector."""
        if self._uses_openrouter:
            clipped = text[:12000]
            return self._embed_with_openrouter([clipped])[0]
        if self._uses_gemini_api:
            clipped = text[:12000]
            return self._embed_with_gemini([clipped])[0]
        if self._uses_mlx:
            return self._embed_with_mlx([text])[0]
        if self._uses_hash:
            return self._embed_with_hash([text])[0]
        vec = self.model.encode(text, show_progress_bar=False)
        return vec.tolist()

    async def async_encode(self, text: str) -> list[float]:
        """Async wrapper around encode() — runs in a thread to avoid blocking the event loop."""
        return await asyncio.to_thread(self.encode, text)

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts to vectors."""
        if self._uses_openrouter:
            if not texts:
                return []
            clipped = [t[:12000] for t in texts]
            return self._embed_with_openrouter(clipped)
        if self._uses_gemini_api:
            if not texts:
                return []
            clipped = [t[:12000] for t in texts]
            return self._embed_with_gemini(clipped)
        if self._uses_mlx:
            if not texts:
                return []
            return self._embed_with_mlx(texts)
        if self._uses_hash:
            if not texts:
                return []
            return self._embed_with_hash(texts)
        vecs = self.model.encode(texts, show_progress_bar=False, batch_size=32)
        return [v.tolist() for v in vecs]

    @staticmethod
    def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
        """Compute cosine similarity between two vectors.

        Returns a value between -1 and 1 (1 = identical).
        """
        a = np.array(vec1)
        b = np.array(vec2)
        dot = np.dot(a, b)
        norm = np.linalg.norm(a) * np.linalg.norm(b)
        if norm == 0:
            return 0.0
        return float(dot / norm)

    @staticmethod
    def to_sqlite_vec(vec: list[float]) -> bytes:
        """Convert a float vector to sqlite-vec binary format (little-endian float32 array)."""
        return struct.pack(f"<{len(vec)}f", *vec)

    @staticmethod
    def from_sqlite_vec(data: bytes) -> list[float]:
        """Convert sqlite-vec binary format back to a float vector."""
        count = len(data) // 4
        return list(struct.unpack(f"<{count}f", data))
