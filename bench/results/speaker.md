# Owner-voice lock: synthetic bench (19 macOS voices, model 3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx)

Each voice is the owner once; every other voice is an impostor. Genuine trials: other sentences, another speaking rate, noise at 20 dB SNR. TTS voices are steadier than people: false rejects here are a floor.

| Trials | Genuine (mean, min) | Impostor (mean, max) | EER (at threshold) |
|---|---|---|---|
| sentences (2-4 s): 57 genuine, 1026 impostor | 0.70, 0.46 | 0.16, 0.69 | 1.9% (at 0.50) |
| short ("yes", "go ahead"): 38 genuine, 684 impostor | 0.48, 0.30 | 0.10, 0.53 | 2.7% (at 0.32) |

The daemon uses T_HIGH = 0.55 (alone, sentences) and T_LOW = 0.35 (a short word within a minute of a T_HIGH match on the same device profile).

| Threshold | Trials | False accept | False reject |
|---|---|---|---|
| 0.30 | sentences | 10.9% (112/1026) | 0.0% (0/57) |
| 0.30 | short | 3.7% (25/684) | 0.0% (0/38) |
| 0.35 (T_LOW) | sentences | 5.8% (60/1026) | 0.0% (0/57) |
| 0.35 (T_LOW) | short | 1.3% (9/684) | 5.3% (2/38) |
| 0.45 | sentences | 2.6% (27/1026) | 0.0% (0/57) |
| 0.45 | short | 0.3% (2/684) | 28.9% (11/38) |
| 0.50 | sentences | 2.0% (21/1026) | 1.8% (1/57) |
| 0.50 | short | 0.1% (1/684) | 63.2% (24/38) |
| 0.55 (T_HIGH) | sentences | 1.6% (16/1026) | 3.5% (2/57) |
| 0.55 (T_HIGH) | short | 0.0% (0/684) | 86.8% (33/38) |
| 0.60 | sentences | 0.9% (9/1026) | 8.8% (5/57) |
| 0.60 | short | 0.0% (0/684) | 94.7% (36/38) |
