"""Sentence encoder for the neural brain (task N1): multilingual-e5-small through ONNX Runtime, with no PyTorch.

e5 wants a ``query: `` prefix on every input and mean pooling over the last hidden state; the vectors are
unit length. The model is downloaded once into the Hugging Face cache and never committed:

    python -m chanakya.neural.encoder --download

Tests use ``FakeEncoder``, which needs no download and no network.
"""

import argparse
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

MODEL = "intfloat/multilingual-e5-small"
FILES = ("onnx/model.onnx", "onnx/tokenizer.json")
MAX_TOKENS = 128


def model_files(download: bool = False) -> dict[str, Path] | None:
    """Paths of the cached model files, or None when they are missing (or ``download`` fetches them)."""
    try:
        from huggingface_hub import hf_hub_download

        return {name: Path(hf_hub_download(MODEL, name, local_files_only=not download)) for name in FILES}
    except Exception as error:  # noqa: BLE001 - missing library, cache or network all mean "no model"
        logger.info("encoder model unavailable: %s", type(error).__name__)
        return None


class OnnxEncoder:
    """e5-small on ONNX Runtime: text in, unit-length 384-number vectors out."""

    def __init__(self, files: dict[str, Path]):
        import onnxruntime
        from tokenizers import Tokenizer

        self.session = onnxruntime.InferenceSession(str(files["onnx/model.onnx"]), providers=["CPUExecutionProvider"])
        self.inputs = {item.name for item in self.session.get_inputs()}
        self.tokenizer = Tokenizer.from_file(str(files["onnx/tokenizer.json"]))
        self.tokenizer.enable_truncation(MAX_TOKENS)
        self.tokenizer.enable_padding()
        self.name = MODEL

    def encode(self, texts: list[str]) -> np.ndarray:
        """One unit-length row per text."""
        batch = self.tokenizer.encode_batch([f"query: {text}" for text in texts])
        ids = np.array([item.ids for item in batch], dtype=np.int64)
        mask = np.array([item.attention_mask for item in batch], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = self.session.run(None, feed)[0]
        pooled = (hidden * mask[..., None]).sum(axis=1) / mask.sum(axis=1, keepdims=True)
        return pooled / np.linalg.norm(pooled, axis=1, keepdims=True)


class FakeEncoder:
    """Deterministic stand-in for tests: the Strategy Forest's hashed trigram vectors."""

    name = "fake-trigram"

    def encode(self, texts: list[str]) -> np.ndarray:
        from chanakya.brain.forest.forest import embed

        return np.array([embed(text) for text in texts], dtype=np.float64)


def load_encoder() -> OnnxEncoder | None:
    """The real encoder when its libraries and cached files are present, otherwise None."""
    files = model_files()
    if files is None:
        return None
    try:
        return OnnxEncoder(files)
    except ImportError as error:
        logger.info("encoder libraries missing: %s", error)
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Download or check the neural brain's encoder.")
    parser.add_argument("--download", action="store_true", help="Fetch the ONNX model into the Hugging Face cache")
    args = parser.parse_args()
    if args.download and model_files(download=True) is None:
        raise SystemExit("download failed; check the network and requirements-neural.txt")
    encoder = load_encoder()
    if encoder is None:
        raise SystemExit(f"{MODEL} is not available; run with --download")
    vectors = encoder.encode(["kiraya kitna hai?", "What is the monthly rent?"])
    print(f"{MODEL} ready: {vectors.shape[1]} dimensions, similarity of two rent questions {vectors[0] @ vectors[1]:.2f}")


if __name__ == "__main__":
    main()
