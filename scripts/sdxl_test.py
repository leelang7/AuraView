"""SDXL turbo 한 장 테스트 — diffusers 직접 호출.

GPU: RTX 4070 SUPER 12GB / SDXL turbo (캐시 보유) / 4 steps.
출력: docs/captures/sdxl_test_01.png (1024x1024)
"""
from __future__ import annotations

import sys
from pathlib import Path

import torch
from diffusers import AutoPipelineForText2Image


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "captures" / "sdxl_test_01.png"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("[SDXL] loading SDXL turbo (fp16, local cache only) ...")
    import os
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    pipe = AutoPipelineForText2Image.from_pretrained(
        "stabilityai/sdxl-turbo",
        torch_dtype=torch.float16,
        variant="fp16",
        local_files_only=True,
    )
    pipe.to("cuda")
    # 메모리 절약
    pipe.enable_attention_slicing()

    prompt = (
        "Cinematic photograph of a Korean urban intersection at dusk, "
        "rainy wet asphalt reflecting traffic signal red, "
        "large truck partially obscuring crosswalk, "
        "young pedestrian crossing in foreground rain, "
        "Tesla-style HUD overlay on a smartphone in driver's view showing "
        "cyan warning arc — 'AuraView 3.38s 사전 경고', "
        "moody color grading, photorealistic, 8k, hyperdetailed, "
        "deep blue and amber cinema palette, ARRI Alexa film grain"
    )
    negative = (
        "cartoon, low quality, blurry, watermark, logo, deformed faces, "
        "extra fingers, jpeg artifacts, oversaturated"
    )

    print(f"[SDXL] generating 1024x1024 (4 steps) ...")
    image = pipe(
        prompt=prompt,
        negative_prompt=negative,
        num_inference_steps=4,        # turbo: 1~4 steps
        guidance_scale=0.0,            # turbo: 0 권장
        width=1024,
        height=1024,
    ).images[0]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT)
    size_kb = OUT.stat().st_size / 1024
    print(f"[OK] {OUT} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
