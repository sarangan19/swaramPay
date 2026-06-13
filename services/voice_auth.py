"""
Voice biometrics — SpeechBrain ECAPA-TDNN speaker embeddings (replaces resemblyzer,
which was producing too many false accepts/rejects on 8kHz Twilio audio).
"""
import torch
import torch.nn.functional as F
import torchaudio
import soundfile as sf
from speechbrain.inference.speaker import EncoderClassifier
from speechbrain.utils.fetching import LocalStrategy

_classifier = None


def load_classifier():
    """Load the ECAPA-TDNN model once. Call at startup (3-5s cold start)."""
    global _classifier
    if _classifier is None:
        _classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir="pretrained_models/spkrec-ecapa-voxceleb",
            local_strategy=LocalStrategy.COPY,
        )
    return _classifier


def get_embedding(audio_path: str):
    """Load an audio file, resample to 16kHz mono, return a speaker embedding as a list of floats."""
    classifier = load_classifier()
    data, sr = sf.read(audio_path, dtype="float32")
    signal = torch.from_numpy(data)
    if signal.ndim > 1:
        signal = signal.mean(dim=1)
    signal = signal.unsqueeze(0)
    if sr != 16000:
        signal = torchaudio.functional.resample(signal, sr, 16000)
    with torch.no_grad():
        embedding = classifier.encode_batch(signal)
    return embedding.squeeze().tolist()


def cosine_similarity(a, b) -> float:
    a = torch.tensor(a)
    b = torch.tensor(b)
    return float(F.cosine_similarity(a.unsqueeze(0), b.unsqueeze(0)).item())
