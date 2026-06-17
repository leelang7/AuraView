"""SDXL turbo — pitch deck 5 hero shots batch.

각 1024x1024, ~1초/장. 출력: docs/captures/hero_*.png
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import torch
from diffusers import AutoPipelineForText2Image


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "captures"

HEROES = [
    ("hero_01_cover.png",
     "ultra cinematic photograph, Korean urban intersection at night, heavy rain, "
     "wet asphalt mirror reflection of cyan traffic signal, slick wet road surface, "
     "neon hangul shop signs blurred bokeh in distance, distant Tesla style sedan, "
     "moody navy and teal palette, hyperreal, ARRI Alexa shot, anamorphic lens flare"),

    ("hero_02_truck_occlusion.png",
     "first person driver POV through windshield in heavy rain, large dump truck "
     "directly ahead blocking view of intersection and traffic light, wet road, "
     "Korean street, pedestrian only partially visible through rain mist behind truck, "
     "tension thriller cinematography, dark moody color grade, photorealistic"),

    ("hero_03_schoolzone.png",
     "Korean elementary school zone in early morning soft golden light, "
     "children with yellow backpacks crossing crosswalk, slow speed limit sign, "
     "rear view of small sedan car braking gently, safe and warm atmosphere, "
     "photorealistic editorial photography style, fuji film stock look"),

    ("hero_04_v2v.png",
     "futuristic concept render, two cars on Korean highway sharing data via "
     "translucent cyan light arcs connecting them in midair, top down isometric view, "
     "minimalist clean style, glowing data packet visualization, "
     "dark gradient road background, sci-fi infographic aesthetic"),

    ("hero_05_data_fusion.png",
     "infographic concept render, central glowing AI brain node radiating cyan light, "
     "25 connected nodes around it representing public data sources, "
     "dark navy background, isometric clean tech aesthetic, "
     "glowing connection lines, halo glow, no text"),
]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print(f"[SDXL] loading pipeline ...")
    pipe = AutoPipelineForText2Image.from_pretrained(
        "stabilityai/sdxl-turbo",
        torch_dtype=torch.float16,
        variant="fp16",
        local_files_only=True,
    )
    pipe.to("cuda")
    pipe.enable_attention_slicing()

    OUT.mkdir(parents=True, exist_ok=True)
    NEG = "text, watermark, logo, blurry, low quality, deformed, jpeg artifacts, oversaturated"

    for fname, prompt in HEROES:
        print(f"[+] {fname}")
        img = pipe(
            prompt=prompt,
            negative_prompt=NEG,
            num_inference_steps=4,
            guidance_scale=0.0,
            width=1024,
            height=1024,
        ).images[0]
        out = OUT / fname
        img.save(out)
        kb = out.stat().st_size / 1024
        print(f"    → {kb:.1f} KB")

    print(f"\n[OK] 5 heroes generated → {OUT}")


if __name__ == "__main__":
    main()
