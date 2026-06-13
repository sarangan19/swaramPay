#!/usr/bin/env python3
"""
VaaniPay Voice Biometrics — Backend Comparison Test
====================================================
Tests resemblyzer vs SpeechBrain ECAPA-TDNN on the same audio samples.
Also simulates Twilio's 8kHz telephony codec degradation so you know
what accuracy to expect in production.

QUICK START
-----------
1. Record yourself saying 3 phrases (enrollment samples):
     enroll_1.wav  enroll_2.wav  enroll_3.wav

2. Record yourself saying a new phrase (positive / same speaker):
     positive_1.wav

3. Record someone ELSE saying a phrase (negative / different speaker):
     negative_1.wav

4. Run:
     python -m voice_biometrics.test_comparison \\
       --enroll enroll_1.wav enroll_2.wav enroll_3.wav \\
       --positive positive_1.wav \\
       --negative negative_1.wav \\
       --simulate-twilio

Alternatively, use --generate-test-audio to record directly from your mic:
     python -m voice_biometrics.test_comparison --generate-test-audio

INTERPRETING RESULTS
--------------------
  Score separation = avg_same_speaker_score - avg_diff_speaker_score
  Higher separation = cleaner decision boundary = easier to tune threshold

  Both backends report scores in [-1, 1] (cosine similarity),
  but their ABSOLUTE RANGES differ:
    - Resemblyzer:   same-speaker ~0.8–0.95, diff-speaker ~0.2–0.5
    - SpeechBrain:   same-speaker ~0.3–0.7,  diff-speaker ~-0.1–0.2
  Do NOT compare thresholds across backends — only compare separations.
"""

import argparse
import os
import sys
import time
import tempfile
import json
from pathlib import Path

import numpy as np


# ─── Twilio Codec Simulation ────────────────────────────────────────────────

def simulate_twilio_codec(input_path: str, output_path: str):
    """
    Simulates Twilio's telephony codec:
      1. Resample input to 8kHz (Twilio's actual sample rate)
      2. Re-save at 8kHz (this IS what Twilio delivers to your webhook)
    Note: we keep it at 8kHz rather than upsampling back to 16kHz,
    because that's what backends will actually receive from Twilio WAV URLs.
    """
    try:
        import soundfile as sf
        import scipy.signal
    except ImportError:
        print("  ⚠️  Install soundfile and scipy for --simulate-twilio: pip install soundfile scipy")
        return input_path

    data, sr = sf.read(input_path)
    if sr == 8000:
        import shutil
        shutil.copy(input_path, output_path)
        return output_path

    # Downsample to 8kHz
    n_samples = int(len(data) * 8000 / sr)
    data_8k = scipy.signal.resample(data, n_samples)
    sf.write(output_path, data_8k, 8000)
    return output_path


# ─── Mic Recording Helper ───────────────────────────────────────────────────

def record_from_mic(output_path: str, duration: int = 5, prompt: str = "Speak now"):
    """Record `duration` seconds from the default microphone."""
    try:
        import sounddevice as sd
        import soundfile as sf
    except ImportError:
        print("Install sounddevice to record from mic: pip install sounddevice soundfile")
        sys.exit(1)

    sr = 16000
    print(f"  🎙️  {prompt} ({duration}s)... ", end="", flush=True)
    audio = sd.rec(int(duration * sr), samplerate=sr, channels=1, dtype="float32")
    sd.wait()
    sf.write(output_path, audio, sr)
    print("done.")
    return output_path


def generate_test_audio(outdir: str = "test_audio") -> dict:
    """
    Interactive recording session to generate test audio from mic.
    Returns dict with paths to all recorded files.
    """
    os.makedirs(outdir, exist_ok=True)
    print("\n🎤 RECORDING TEST AUDIO")
    print("  You'll record 3 enrollment samples, 1 positive, and 1 negative.")
    print("  For the negative sample, use a different person (or significantly change your voice).\n")

    paths = {"enroll": [], "positive": [], "negative": []}

    phrases = [
        "aaj mausam bahut achha hai",
        "mujhe apne ghar se pyaar hai",
        "hamaara desh bahut sundar hai",
    ]

    for i, phrase in enumerate(phrases, 1):
        input(f"  [Enrollment {i}/3] Say: '{phrase}'  (press Enter when ready)")
        p = os.path.join(outdir, f"enroll_{i}.wav")
        record_from_mic(p, duration=5)
        paths["enroll"].append(p)

    input("\n  [Positive] Say any new phrase (same person, press Enter when ready)")
    p = os.path.join(outdir, "positive_1.wav")
    record_from_mic(p, duration=5, prompt="Say your new phrase now")
    paths["positive"].append(p)

    print("\n  [Negative] NOW USE A DIFFERENT PERSON or significantly change your voice.")
    input("  Say any phrase (press Enter when ready)")
    p = os.path.join(outdir, "negative_1.wav")
    record_from_mic(p, duration=5, prompt="Different speaker — say any phrase")
    paths["negative"].append(p)

    print(f"\n  ✅ Audio saved to ./{outdir}/")
    return paths


# ─── Backend Test Runners ────────────────────────────────────────────────────

def run_resemblyzer(enroll_paths, positive_paths, negative_paths) -> dict:
    print("\n" + "─" * 52)
    print("📦  RESEMBLYZER  (d-vectors, local)")
    print("─" * 52)

    try:
        from voice_biometrics.resemblyzer_backend import ResemblyzerBackend
        backend = ResemblyzerBackend()
    except ImportError as e:
        print(f"  ⚠️  Skipped — {e}")
        return None

    # Enrollment
    t0 = time.perf_counter()
    model = backend.enroll(enroll_paths)
    enroll_ms = (time.perf_counter() - t0) * 1000
    print(f"  Enrolled on {len(enroll_paths)} sample(s) in {enroll_ms:.0f}ms")

    results = {"tp_scores": [], "tn_scores": [], "enroll_ms": enroll_ms}

    # Same-speaker tests (True Positives)
    print(f"\n  Same-speaker ({len(positive_paths)} sample(s)):")
    for path in positive_paths:
        r = backend.verify_timed(model, path)
        results["tp_scores"].append(r["score"])
        label = "✅ AUTHENTICATED" if r["authenticated"] else "❌ REJECTED (false reject)"
        print(f"    {Path(path).name:25s}  score={r['score']:+.4f}  {r['latency_ms']:.0f}ms  {label}")

    # Different-speaker tests (True Negatives)
    print(f"\n  Diff-speaker ({len(negative_paths)} sample(s)):")
    for path in negative_paths:
        r = backend.verify_timed(model, path)
        results["tn_scores"].append(r["score"])
        label = "✅ REJECTED" if not r["authenticated"] else "❌ ACCEPTED (false accept!)"
        print(f"    {Path(path).name:25s}  score={r['score']:+.4f}  {r['latency_ms']:.0f}ms  {label}")

    return results


def run_speechbrain(enroll_paths, positive_paths, negative_paths) -> dict:
    print("\n" + "─" * 52)
    print("🧠  SPEECHBRAIN  (ECAPA-TDNN, HuggingFace)")
    print("─" * 52)

    try:
        from voice_biometrics.speechbrain_backend import SpeechBrainBackend
        backend = SpeechBrainBackend()
    except ImportError as e:
        print(f"  ⚠️  Skipped — {e}")
        return None

    t0 = time.perf_counter()
    model = backend.enroll(enroll_paths)
    enroll_ms = (time.perf_counter() - t0) * 1000
    print(f"  Enrolled on {len(enroll_paths)} sample(s) in {enroll_ms:.0f}ms")

    results = {"tp_scores": [], "tn_scores": [], "enroll_ms": enroll_ms}

    print(f"\n  Same-speaker ({len(positive_paths)} sample(s)):")
    for path in positive_paths:
        r = backend.verify_timed(model, path)
        results["tp_scores"].append(r["score"])
        label = "✅ AUTHENTICATED" if r["authenticated"] else "❌ REJECTED (false reject)"
        print(f"    {Path(path).name:25s}  score={r['score']:+.4f}  {r['latency_ms']:.0f}ms  {label}")

    print(f"\n  Diff-speaker ({len(negative_paths)} sample(s)):")
    for path in negative_paths:
        r = backend.verify_timed(model, path)
        results["tn_scores"].append(r["score"])
        label = "✅ REJECTED" if not r["authenticated"] else "❌ ACCEPTED (false accept!)"
        print(f"    {Path(path).name:25s}  score={r['score']:+.4f}  {r['latency_ms']:.0f}ms  {label}")

    return results


# ─── Summary ─────────────────────────────────────────────────────────────────

def print_summary(resemblyzer_results, speechbrain_results, twilio_simulated: bool):
    print("\n" + "=" * 52)
    print("📊  SUMMARY")
    if twilio_simulated:
        print("    (with Twilio 8kHz codec simulation)")
    print("=" * 52)

    rows = [
        ("Resemblyzer", resemblyzer_results),
        ("SpeechBrain ECAPA-TDNN", speechbrain_results),
    ]

    best = None
    best_sep = -999

    for name, r in rows:
        if r is None:
            print(f"\n  {name}: not available")
            continue

        tp = r["tp_scores"]
        tn = r["tn_scores"]
        avg_tp = np.mean(tp) if tp else float("nan")
        avg_tn = np.mean(tn) if tn else float("nan")
        sep = avg_tp - avg_tn
        suggested_threshold = (avg_tp + avg_tn) / 2 if tp and tn else float("nan")

        print(f"\n  {name}")
        print(f"    Avg same-speaker score : {avg_tp:+.4f}")
        print(f"    Avg diff-speaker score : {avg_tn:+.4f}")
        print(f"    Score separation       : {sep:+.4f}   ← higher is better")
        print(f"    Suggested threshold    : {suggested_threshold:+.4f}")
        print(f"    Enrollment time        : {r['enroll_ms']:.0f}ms")

        if sep > best_sep:
            best_sep = sep
            best = name

    if best:
        print(f"\n  🏆  Better backend for this audio: {best}  (separation={best_sep:+.4f})")

    print()


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Compare resemblyzer vs SpeechBrain for VaaniPay voice auth",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--enroll", nargs="+", metavar="FILE",
                        help="Enrollment audio files (same speaker, 3+ recommended)")
    parser.add_argument("--positive", nargs="+", metavar="FILE",
                        help="Verification audio from the SAME speaker")
    parser.add_argument("--negative", nargs="+", metavar="FILE",
                        help="Verification audio from a DIFFERENT speaker")
    parser.add_argument("--simulate-twilio", action="store_true",
                        help="Downsample audio to 8kHz to simulate Twilio's telephony codec")
    parser.add_argument("--backend", choices=["resemblyzer", "speechbrain", "both"],
                        default="both", help="Which backend(s) to test (default: both)")
    parser.add_argument("--generate-test-audio", action="store_true",
                        help="Record test audio from your microphone interactively")
    args = parser.parse_args()

    # --- Interactive mic recording mode ---
    if args.generate_test_audio:
        audio_paths = generate_test_audio()
        args.enroll = audio_paths["enroll"]
        args.positive = audio_paths["positive"]
        args.negative = audio_paths["negative"]

    if not args.enroll or not args.positive or not args.negative:
        parser.print_help()
        sys.exit(1)

    # Validate files exist
    all_files = args.enroll + args.positive + args.negative
    missing = [f for f in all_files if not os.path.exists(f)]
    if missing:
        for f in missing:
            print(f"❌ File not found: {f}")
        sys.exit(1)

    enroll_paths = args.enroll
    positive_paths = args.positive
    negative_paths = args.negative

    print(f"\n🎤  Enrollment samples : {len(enroll_paths)}")
    print(f"✅  Same-speaker tests : {len(positive_paths)}")
    print(f"❌  Diff-speaker tests : {len(negative_paths)}")

    # --- Twilio simulation ---
    tmpdir = None
    twilio_simulated = False
    if args.simulate_twilio:
        print("\n📞  Simulating Twilio 8kHz codec...")
        tmpdir = tempfile.mkdtemp(prefix="vaanipay_test_")

        def degraded(paths, prefix):
            out = []
            for p in paths:
                dest = os.path.join(tmpdir, f"{prefix}_{Path(p).name}")
                simulate_twilio_codec(p, dest)
                out.append(dest)
            return out

        enroll_paths = degraded(enroll_paths, "enroll")
        positive_paths = degraded(positive_paths, "pos")
        negative_paths = degraded(negative_paths, "neg")
        twilio_simulated = True
        print(f"  Degraded files written to {tmpdir}")

    # --- Run tests ---
    resemblyzer_results = None
    speechbrain_results = None

    if args.backend in ("resemblyzer", "both"):
        resemblyzer_results = run_resemblyzer(enroll_paths, positive_paths, negative_paths)

    if args.backend in ("speechbrain", "both"):
        speechbrain_results = run_speechbrain(enroll_paths, positive_paths, negative_paths)

    print_summary(resemblyzer_results, speechbrain_results, twilio_simulated)

    # Save raw results to JSON for further analysis
    results_path = "voice_biometrics_results.json"
    with open(results_path, "w") as f:
        json.dump({
            "twilio_simulated": twilio_simulated,
            "n_enrollment_samples": len(args.enroll),
            "resemblyzer": resemblyzer_results,
            "speechbrain": speechbrain_results,
        }, f, indent=2)
    print(f"  Raw scores saved to {results_path}")


if __name__ == "__main__":
    main()
