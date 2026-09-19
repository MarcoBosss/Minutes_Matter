#!/usr/bin/env python3
"""
Minutes Matter - Gemini Risk Analyzer

Reads:
- environment_state.json
- optional downloaded images
- optional historical JSON snapshots

Writes risk_assessment.json in this exact shape:

{
  "observations": {
    "weather": {...},
    "seismic": {...},
    "river": {...}
  },
  "gemini": {
    "risk_level": "WATCH",
    "confidence": 78,
    "reasoning": "...",
    "signals": [...]
  }
}
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel, Field

load_dotenv()


# ---------------------------------------------------------------------------
# Gemini structured output
# ---------------------------------------------------------------------------

class RiskAssessment(BaseModel):
    risk_level: Literal["NORMAL", "WATCH", "WARNING", "CRITICAL"]

    confidence: int = Field(
        ge=0,
        le=100,
        description="Confidence percentage from 0 to 100."
    )

    reasoning: str = Field(
        description=(
            "Briefly explain whether the combination of observations represents "
            "meaningful deterioration, including reinforcing signals, conflicting "
            "evidence, uncertainty, and why this risk level was selected."
        )
    )

    signals: list[str] = Field(
        default_factory=list,
        description=(
            "The most important evidence affecting the assessment. Include "
            "reinforcing and conflicting observations where relevant."
        )
    )


SYSTEM_INSTRUCTIONS = """
You are the environmental reasoning engine for a student prototype called
Minutes Matter.

Determine whether the COMBINATION of supplied environmental observations
represents a meaningful deterioration in conditions.

Consider:
- which independent signals reinforce one another
- which evidence conflicts with deterioration
- whether observations show a trend rather than an isolated anomaly
- whether important evidence is missing or uncertain
- whether visual changes in supplied images support or weaken the assessment

Choose exactly one risk level:

NORMAL
No meaningful abnormal or deteriorating signals are supported.

WATCH
There are concerning observations, but evidence is weak, incomplete, isolated,
or not yet strongly converging.

WARNING
Multiple independent observations reinforce one another and support meaningful
deterioration requiring prompt human review and increased monitoring.

CRITICAL
Strong, converging, time-sensitive evidence supports a potentially dangerous
environmental situation requiring immediate human escalation.

Rules:
- Do not claim to predict the exact time or location of a disaster.
- Do not invent measurements.
- Do not treat unavailable data as evidence of safety.
- A single weak signal should not produce CRITICAL.
- Prefer trends over isolated measurements.
- Prefer agreement between independent sources.
- Explain important conflicts in the reasoning.
- If there is insufficient temporal evidence, say so in the reasoning.
- Never assume two sources refer to the same geographic location just because
  they were supplied together.
- If a camera is geographically separate from the monitoring target, DO NOT
  use that image as direct evidence for the target's risk level. You may still
  describe that mismatch in the reasoning.
- Base the assessment only on supplied evidence.
- This is a prototype decision-support system, not an official emergency
  warning service.

Output requirements:
- confidence must be an integer from 0 to 100
- reasoning should be concise but informative
- signals should contain the most important evidence only
"""


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def find_images(path: Optional[Path], max_images: int = 3) -> list[Path]:
    if path is None:
        return []

    if not path.exists():
        raise FileNotFoundError(f"Image path not found: {path}")

    if path.is_file():
        return [path]

    allowed = {".jpg", ".jpeg", ".png", ".webp"}

    images = [
        p for p in path.iterdir()
        if p.is_file()
        and p.suffix.lower() in allowed
        and not p.stem.endswith("_latest")
    ]

    # Oldest -> newest among the newest N images.
    images.sort(key=lambda p: p.stat().st_mtime)
    return images[-max_images:]


def load_history(
    history_dir: Optional[Path],
    max_history: int = 6,
) -> list[dict]:
    if history_dir is None:
        return []

    if not history_dir.exists():
        raise FileNotFoundError(f"History directory not found: {history_dir}")

    paths = sorted(
        history_dir.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
    )[-max_history:]

    history = []

    for path in paths:
        data = load_json(path)
        history.append({
            "filename": path.name,
            "generated_at": data.get("generated_at"),
            "target": data.get("target"),
            "observations_for_gemini": data.get(
                "observations_for_gemini",
                data,
            ),
        })

    return history


def encode_image(path: Path) -> dict:
    mime_type, _ = mimetypes.guess_type(path.name)

    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/jpeg"

    return {
        "type": "image",
        "data": base64.b64encode(path.read_bytes()).decode("utf-8"),
        "mime_type": mime_type,
    }


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def build_prompt(
    environment: dict,
    history: list[dict],
    image_paths: list[Path],
) -> str:
    sources = environment.get("sources") or {}

    source_metadata = {}

    for name, value in sources.items():
        if not isinstance(value, dict):
            continue

        source_metadata[name] = {
            "status": value.get("status"),
            "retrieved_at": value.get("retrieved_at"),
            "note": value.get("note"),
        }

        # Preserve camera location metadata so Gemini can detect
        # geographic mismatches.
        if name == "foto_webcam_glacier":
            source_metadata[name]["data"] = value.get("data")

    evidence = {
        "monitoring_target": environment.get("target", {}),
        "current_observations": environment.get(
            "observations_for_gemini",
            environment,
        ),
        "source_status_and_metadata": source_metadata,
        "historical_observations_oldest_to_newest": history,
        "supplied_images": [
            {
                "sequence": i + 1,
                "filename": path.name,
                "note": (
                    "When multiple images are supplied, they are ordered "
                    "oldest to newest."
                ),
            }
            for i, path in enumerate(image_paths)
        ],
    }

    return (
        SYSTEM_INSTRUCTIONS
        + "\n\nENVIRONMENTAL EVIDENCE:\n"
        + json.dumps(
            evidence,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
        + "\n\nReturn only the structured risk assessment."
    )


# ---------------------------------------------------------------------------
# Gemini Interactions API
# ---------------------------------------------------------------------------

def analyze(
    environment: dict,
    image_paths: list[Path],
    history: list[dict],
    model: str,
    retries: int = 3,
) -> RiskAssessment:
    if not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to the repo-root .env file."
        )

    client = genai.Client()

    interaction_input = [
        {
            "type": "text",
            "text": build_prompt(environment, history, image_paths),
        }
    ]

    for image_path in image_paths:
        interaction_input.append(encode_image(image_path))

    last_error = None

    for attempt in range(1, retries + 1):
        try:
            interaction = client.interactions.create(
                model=model,
                input=interaction_input,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": RiskAssessment.model_json_schema(),
                },
            )

            if not interaction.output_text:
                raise RuntimeError("Gemini returned no output text.")

            return RiskAssessment.model_validate_json(
                interaction.output_text
            )

        except Exception as exc:
            last_error = exc

            if attempt == retries:
                break

            wait_seconds = 2 ** (attempt - 1)
            print(
                f"Gemini request failed "
                f"(attempt {attempt}/{retries}): {exc}"
            )
            print(f"Retrying in {wait_seconds} second(s)...")
            time.sleep(wait_seconds)

    raise RuntimeError(
        f"Gemini request failed after {retries} attempts: {last_error}"
    )


# ---------------------------------------------------------------------------
# Final output
# ---------------------------------------------------------------------------

def build_output(
    environment: dict,
    assessment: RiskAssessment,
) -> dict:
    observations = environment.get(
        "observations_for_gemini",
        {}
    )

    return {
        "observations": {
            "weather": observations.get("weather", {}),
            "seismic": observations.get("seismic", {}),
            "river": observations.get("river", {}),
        },
        "gemini": {
            "risk_level": assessment.risk_level,
            "confidence": assessment.confidence,
            "reasoning": assessment.reasoning,
            "signals": assessment.signals,
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Analyze Minutes Matter environmental JSON and images "
            "with Gemini and write risk_assessment.json."
        )
    )

    parser.add_argument(
        "--json",
        required=True,
        help="Path to environment_state.json",
    )

    parser.add_argument(
        "--images",
        default=None,
        help="Image file or folder containing downloaded images",
    )

    parser.add_argument(
        "--history-dir",
        default=None,
        help="Optional folder containing historical environment JSON snapshots",
    )

    parser.add_argument(
        "--output",
        default="risk_assessment.json",
        help="Output JSON file",
    )

    parser.add_argument(
        "--model",
        default=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        help="Gemini model name",
    )

    parser.add_argument(
        "--max-images",
        type=int,
        default=3,
    )

    parser.add_argument(
        "--max-history",
        type=int,
        default=6,
    )

    args = parser.parse_args()

    environment = load_json(Path(args.json))

    image_paths = find_images(
        Path(args.images) if args.images else None,
        max_images=args.max_images,
    )

    history = load_history(
        Path(args.history_dir) if args.history_dir else None,
        max_history=args.max_history,
    )

    print("Minutes Matter - Gemini Risk Analyzer")
    print("-------------------------------------")
    print(f"Environment JSON: {args.json}")
    print(f"Images:           {len(image_paths)}")
    print(f"History snapshots:{len(history)}")
    print(f"Model:            {args.model}")
    print()

    assessment = analyze(
        environment=environment,
        image_paths=image_paths,
        history=history,
        model=args.model,
    )

    result = build_output(
        environment=environment,
        assessment=assessment,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("Assessment")
    print("----------")
    print(f"Risk level: {assessment.risk_level}")
    print(f"Confidence: {assessment.confidence}%")
    print()
    print(assessment.reasoning)
    print()
    print(f"Wrote: {output_path.resolve()}")


if __name__ == "__main__":
    main()
