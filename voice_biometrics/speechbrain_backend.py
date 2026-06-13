"""
SpeechBrain ECAPA-TDNN backend for VaaniPay voice biometrics.

How it works:
  - Uses the ECAPA-TDNN model (Enhanced Channels Attentive, Propagation and Aggregation TDNN)
  - Pre-trained on VoxCeleb 1+2 — best open-source speaker verification accuracy
  - EER of ~0.69–0.80% on VoxCeleb1 benchmark
  - Downloads ~80MB model from HuggingFace on first run, cached locally after that

Twilio note: ECAPA-TDNN expects 16kHz audio. Twilio delivers 8kHz.
This backend resamples automatically before inference.

Install: pip install speechbrain torchaudio
"""

import numpy as np
import time
import os
import tempfile
from typing import Optional

try:
    import torch
    import torchaudio
    import soundfile as sf
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

try:
    # speechbrain 0.5.x path
    from speechbrain.pretrained import SpeakerRecognition
    SPEECHBRAIN_AVAILABLE = True
    _IMPORT_PATH = "pretrained"
except ImportError:
    try:
        # speechbrain 1.x path
        from speechbrain.inference.speaker import SpeakerRecognition
        SPEECHBRAIN_AVAILABLE = True
        _IMPORT_PATH = "inference"
    except ImportError:
        SPEECHBRAIN_AVAILABLE = False
        _IMPORT_PATH = None


class SpeechBrainBackend:
    MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"
    TARGET_SR = 16000  # ECAPA-TDNN was trained on 16kHz

    # ECAPA-TDNN cosine similarity scores live in a different range than resemblyzer.
    # Measured on Twilio 8kHz-simulated audio: same-speaker ~0.65, different-speaker ~0.18,
    # separation ~0.47. This threshold is conservative for telephony audio.
    # Tune further with test_comparison.py against real Twilio recordings.
    DEFAULT_THRESHOLD = 0.25

    def __init__(self, savedir: str = "pretrained_models/spkrec-ecapa-voxceleb"):
        if not TORCH_AVAILABLE:
            raise ImportError("torch and torchaudio are not installed.\nRun: pip install torch torchaudio")
        if not SPEECHBRAIN_AVAILABLE:
            raise ImportError("speechbrain is not installed.\nRun: pip install speechbrain")

        os.makedirs(savedir, exist_ok=True)
        print(f"[SpeechBrain] Loading ECAPA-TDNN from {self.MODEL_SOURCE}...")
        print("[SpeechBrain] First run will download ~80MB model. Subsequent runs use cache.")

        self.model = SpeakerRecognition.from_hparams(
            source=self.MODEL_SOURCE,
            savedir=savedir,
            run_opts={"device": "cpu"},  # switch to "cuda" if GPU available
        )
        self.model.eval()

    def _load_and_resample(self, audio_path: str) -> torch.Tensor:
        """
        Load audio file and resample to 16kHz mono.
        Handles Twilio's 8kHz mulaw input.

        Uses soundfile rather than torchaudio.load() — newer torchaudio
        versions delegate .load() to torchcodec, which isn't installed here
        and raises at runtime.
        """
        data, sr = sf.read(audio_path)

        # Convert to mono
        if data.ndim > 1:
            data = data.mean(axis=1)

        waveform = torch.tensor(data, dtype=torch.float32).unsqueeze(0)

        # Resample to 16kHz if needed (Twilio delivers 8kHz)
        if sr != self.TARGET_SR:
            waveform = torchaudio.functional.resample(waveform, sr, self.TARGET_SR)

        return waveform

    def _get_embedding(self, audio_path: str) -> np.ndarray:
        waveform = self._load_and_resample(audio_path)
        with torch.no_grad():
            emb = self.model.encode_batch(waveform)
        # Shape: [1, 1, embedding_dim] → flatten to 1D
        return emb.squeeze().numpy()

    def get_embedding(self, audio_path: str) -> list:
        """Return embedding for a single audio file as a JSON-serialisable list."""
        return self._get_embedding(audio_path).tolist()

    def enroll(self, audio_paths: list) -> list:
        """
        Build a voice model from multiple enrollment recordings.

        Args:
            audio_paths: List of WAV/MP3 file paths (3+ recommended).
                         Handles any sample rate — resampled to 16kHz internally.

        Returns:
            Averaged ECAPA-TDNN embedding as a JSON-serialisable list.
            Store as user["voice_embedding_ecapa"] to distinguish from resemblyzer model.
        """
        if len(audio_paths) < 1:
            raise ValueError("Need at least 1 audio file to enroll")

        embeddings = [self._get_embedding(p) for p in audio_paths]
        voice_model = np.mean(embeddings, axis=0)
        return voice_model.tolist()

    def verify(
        self,
        stored_embedding: list,
        live_audio_path: str,
        threshold: Optional[float] = None,
    ) -> tuple:
        """
        Compare a live recording against a stored voice model.

        Args:
            stored_embedding: The list returned by enroll()
            live_audio_path:  Path to the live challenge-response recording
            threshold:        Cosine similarity cutoff (default: DEFAULT_THRESHOLD)
                              Note: ECAPA scores are NOT directly comparable to resemblyzer scores.

        Returns:
            (authenticated: bool, similarity_score: float)
        """
        if threshold is None:
            threshold = self.DEFAULT_THRESHOLD

        stored = np.array(stored_embedding)
        live_emb = self._get_embedding(live_audio_path)

        similarity = float(
            np.dot(stored, live_emb) / (np.linalg.norm(stored) * np.linalg.norm(live_emb))
        )
        return similarity >= threshold, similarity

    def verify_timed(self, stored_embedding: list, live_audio_path: str, threshold: Optional[float] = None) -> dict:
        """Same as verify() but also returns inference latency in ms."""
        t0 = time.perf_counter()
        authenticated, score = self.verify(stored_embedding, live_audio_path, threshold)
        latency_ms = (time.perf_counter() - t0) * 1000
        return {
            "authenticated": authenticated,
            "score": score,
            "latency_ms": round(latency_ms, 1),
            "threshold": threshold or self.DEFAULT_THRESHOLD,
            "backend": "speechbrain_ecapa",
        }
