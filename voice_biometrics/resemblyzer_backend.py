"""
Resemblyzer backend for VaaniPay voice biometrics.

How it works:
  - Generates a 256-dimensional d-vector embedding that summarises vocal characteristics
  - Enrollment: average 3+ embeddings from separate recordings to build a stable voice model
  - Verification: cosine similarity between stored model and live recording

Twilio note: Twilio delivers 8kHz mulaw audio. resemblyzer's preprocess_wav()
resamples automatically, so no manual resampling is needed here.

Install: pip install resemblyzer
"""

import numpy as np
import time
from typing import Optional

try:
    from resemblyzer import VoiceEncoder, preprocess_wav
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


class ResemblyzerBackend:
    # Cosine similarity threshold. Tuned for telephony (8kHz) audio.
    # Raise to ~0.82 in clean recording environments; lower to ~0.68 for noisy lines.
    DEFAULT_THRESHOLD = 0.75

    def __init__(self):
        if not AVAILABLE:
            raise ImportError(
                "resemblyzer is not installed.\n"
                "Run: pip install resemblyzer"
            )
        # Load once — encoder is ~17MB, CPU inference ~1000x real-time on modern hardware
        self.encoder = VoiceEncoder()

    def _load(self, audio_path: str) -> np.ndarray:
        """
        Load audio and apply resemblyzer's standard preprocessing:
        - Resamples to 16kHz regardless of input sample rate (handles Twilio's 8kHz)
        - Normalises volume
        - Trims silence from edges
        """
        return preprocess_wav(audio_path)

    def get_embedding(self, audio_path: str) -> list:
        """Return the 256-dim embedding for a single audio file."""
        wav = self._load(audio_path)
        emb = self.encoder.embed_utterance(wav)
        return emb.tolist()

    def enroll(self, audio_paths: list) -> list:
        """
        Build a voice model from multiple enrollment recordings.

        Args:
            audio_paths: List of WAV file paths (3+ recommended for stability).
                         Each should be the same person saying a different phrase.

        Returns:
            Averaged 256-dim embedding as a JSON-serialisable list.
            Store this in the user's profile: user["voice_embedding"] = result
        """
        if len(audio_paths) < 1:
            raise ValueError("Need at least 1 audio file to enroll")

        embeddings = []
        for path in audio_paths:
            wav = self._load(path)
            emb = self.encoder.embed_utterance(wav)
            embeddings.append(emb)

        # Average embedding is more robust than any single sample
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
            stored_embedding: The list returned by enroll(), from user["voice_embedding"]
            live_audio_path:  Path to the live challenge-response recording
            threshold:        Cosine similarity cutoff (default: DEFAULT_THRESHOLD)

        Returns:
            (authenticated: bool, similarity_score: float)
            similarity_score is always in [-1, 1]; higher = more likely same speaker
        """
        if threshold is None:
            threshold = self.DEFAULT_THRESHOLD

        stored = np.array(stored_embedding)
        wav = self._load(live_audio_path)
        live_emb = self.encoder.embed_utterance(wav)

        # Cosine similarity
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
            "backend": "resemblyzer",
        }
