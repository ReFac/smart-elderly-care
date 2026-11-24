"""Turn a single, local observation into an unsigned hourly cough-candidate count."""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import wave
import zipfile

MODEL_SHA256 = "4d8b4a53282dc83ef04e3e7dbc4fbc98082e34e44ed798e16c3a0cdd4c584faf"
SAMPLE_RATE = 16000
WINDOW = 15600
HOP = 7680


def count_clusters(scores, threshold):
    """Count contiguous positive windows once, independent of window overlap."""
    active = False
    count = 0
    for score in scores:
        positive = score >= threshold
        if positive and not active:
            count += 1
        active = positive
    return count


def load_scorer(model):
    import numpy as np
    from ai_edge_litert.interpreter import Interpreter

    with model.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != MODEL_SHA256:
            raise ValueError(
                "请选择官方 MediaPipe YAMNet float32 v1 权重，文件校验不符"
            )
    with zipfile.ZipFile(model) as archive:
        labels = archive.read("yamnet_label_list.txt").decode().splitlines()
    cough = labels.index("Cough")
    interpreter = Interpreter(model_path=str(model), num_threads=1)
    interpreter.allocate_tensors()
    source = interpreter.get_input_details()[0]["index"]
    target = interpreter.get_output_details()[0]["index"]

    def score(raw):
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
        if samples.size < WINDOW:
            samples = np.pad(samples, (0, WINDOW - samples.size))
        interpreter.set_tensor(source, samples)
        interpreter.invoke()
        return float(interpreter.get_tensor(target)[0, cough])

    return score


def observe(handle, start, threshold, scorer):
    if not 0 < threshold < 1:
        raise ValueError("识别阈值须在 0 与 1 之间")
    frames = handle.getnframes()
    if (handle.getnchannels(), handle.getsampwidth(), handle.getframerate()) != (
        1,
        2,
        SAMPLE_RATE,
    ):
        raise ValueError("音频须为单声道、16 kHz、16 位 PCM WAV")
    minute = SAMPLE_RATE * 60
    if start.second or start.microsecond or frames < minute or frames % minute:
        raise ValueError("请使用完整分钟的一段连续观察，并填写精确到分钟的开始时间")
    minutes = frames // minute
    if start.minute + minutes > 60:
        raise ValueError("请按自然小时拆分，以便与历史相同时段比较")

    def scores():
        for offset in range(0, frames, HOP):
            handle.setpos(offset)
            expected = min(WINDOW, frames - offset)
            raw = handle.readframes(expected)
            if len(raw) != expected * 2:
                raise ValueError("WAV 内容不完整")
            yield scorer(raw)
            if offset + WINDOW >= frames:
                return

    return {
        "day": start.date().isoformat(),
        "hour": start.hour,
        "count": count_clusters(scores(), threshold),
        "observedMinutes": minutes,
        "source": "yamnet",
        "reviewed": False,
        "threshold": threshold,
        "modelSha256": MODEL_SHA256,
    }


def main():
    parser = argparse.ArgumentParser(
        description="在本机识别咳嗽候选片段，输出待复核计数"
    )
    parser.add_argument("audio", type=Path, help="已取得授权的连续 WAV 录音")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--start", required=True, help="北京时间 YYYY-MM-DDTHH:MM")
    parser.add_argument(
        "--threshold", type=float, default=0.5, help="候选筛选分数，默认 0.5"
    )
    args = parser.parse_args()
    try:
        start = datetime.strptime(args.start, "%Y-%m-%dT%H:%M")
        with wave.open(str(args.audio), "rb") as handle:
            result = observe(handle, start, args.threshold, load_scorer(args.model))
    except ImportError:
        parser.exit(2, "当前 Python 环境需要安装 ai-edge-litert 和 numpy。\n")
    except (ValueError, OSError, wave.Error, EOFError) as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
