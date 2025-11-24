#!/usr/bin/env python
import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image  # noqa: F401 (required for as_image() to work internally)


# ---------- Configuration ----------

DEFAULT_TEXT_MODEL = "gemini-2.5-pro"
DEFAULT_IMAGE_MODEL = "nano-banana-pro-preview"


# ---------- Prompt Templates ----------

def build_text_model_prompt(repo_url: str) -> str:
    """
    Build the full prompt for the text model (Gemini) to produce the JSON pipeline spec.
    """
    instructions = f"""
You are a Principal Systems Architect. Your task is to analyze the GitHub repository at:
{repo_url}

Use the URL context tool to fetch and analyze the ENTIRE codebase. You must understand the ACTUAL execution flow, not just guess based on file names.

CRITICAL INSTRUCTIONS FOR ANALYSIS:
1. **Identify Entry Points**: Find the main entry point (e.g., `main.py`, `app.py`, `cli.py`, `Dockerfile`, `manage.py`). Start your analysis there.
2. **Trace Execution**: Follow the code execution path. Who calls whom? Where does data go?
3. **Detect Data Movement**: Look for:
   - File I/O (read/write)
   - API Calls (requests, fetch)
   - Database interactions (SQL, ORM)
   - Major function arguments and return values (data passing)
4. **Handle Different Architectures**:
   - If it's a **Script/ETL**: Trace file -> script -> file.
   - If it's a **Web App/API**: Trace Request -> Router -> Controller -> Service -> Database -> Response.
   - If it's a **CLI**: Trace Command -> Handler -> Logic -> Output.
   - If it's a **Chatbot**: Trace User Input -> Message Handler -> LLM Client -> Response.

SPECIAL FOCUS: LOGIC & CONTROL FLOW
- **Decision Nodes**: Look for `if/else` logic that fundamentally changes the data flow (e.g., "If mode is 'Hybrid', do X, else do Y"). Represent these as distinct steps or notes.
- **Feedback Loops**: Look for processes that loop back or retry (e.g., "If verification fails, rewrite answer"). Explicitly mention this in the step description.
- **External Services**: Explicitly identify and label API calls to external services (e.g., "OpenAI API", "Anthropic API", "CourtListener API", "Google GenAI").

HIGH-LEVEL OBJECTIVE
- Discover how data flows through this repository.
- Describe the end-to-end pipeline as a set of ordered phases and steps.
- Output a single JSON object that follows the schema below, with NO extra commentary.

PHASE MODEL
Assign every step to exactly ONE high-level phase from this fixed list (map your findings to the closest fit):
  1. Ingestion (User Input, API Requests, Loading Config/Data)
  2. Cleaning & Normalization (Validation, Parsing, Pre-processing)
  3. Feature Engineering (Data Transformation, Embedding Generation, RAG Retrieval)
  4. Modeling / Computation (Core Logic, LLM Calls, Inference, Business Rules)
  5. Optimization / Post-Processing (Formatting, Filtering, Ranking, Verification Loops)
  6. Reporting / Export (Saving to DB, Writing Files, API Response, UI Display)

Use the following format for phase_name:
  "1. Ingestion", "2. Cleaning & Normalization", etc.

JSON SCHEMA
Your output MUST be a single JSON object with this structure:

- repo_name: short string.
- repo_summary: 1–3 sentences describing what this repo does.
- pipeline_overview: 1–2 sentences summarizing the data pipeline.
- phases: an array of phase objects, ordered by execution.
  - Each phase object:
    - phase_id: string like "1", "2", ...
    - phase_name: string like "1. Ingestion".
    - phase_purpose: one-sentence explanation of the phase.
    - steps: array of step objects, ordered by execution within the phase.
      - Each step object:
        - step_id: string like "1.1", "1.2", "2.1", etc.
        - label: very short human-readable name to show inside a box.
        - source_nodes: array of inputs (files, API endpoints, user input, databases).
        - process_script: the script or module executing the logic (e.g., "main.py", "utils.py").
        - target_nodes: array of outputs (files, API responses, UI updates, databases).
        - description: concise summary (5–10 words) of what the step does.
        - notes (optional): any important nuance, assumptions, or decision logic (e.g., "Only if mode=Hybrid").

RULES AND CONSTRAINTS
- Use ONLY files/modules that exist in this repository.
- Be specific about "source_nodes" and "target_nodes". If it's a variable or in-memory object, you can name it (e.g., "DataFrame", "User Prompt").
- Do NOT invent imaginary files.
- Capture the true logical pipeline order.
- If a step is "Run Analysis", the source might be "Cleaned Data" and target might be "Report".

OUTPUT FORMAT (IMPORTANT)
- Respond with VALID JSON ONLY.
- Do not wrap the JSON in backticks.
- Do not include any explanation, prose, or comments.
- The response must be directly parseable as JSON.
"""
    return instructions


def build_image_model_prompt(pipeline_json: dict, repo_url: str) -> str:
    """
    Build the full prompt for the image model (Nano Banana Pro) to create the infographic.
    """
    json_block = json.dumps(pipeline_json, indent=2)
    instructions = f"""
You are an expert data visualization designer using Nano Banana Pro (Gemini 3 Pro Image).
Your task is to turn a JSON specification of a codebase's data pipeline into a clear,
modern 16:9 infographic.

REPOSITORY CONTEXT
You have access to the original repository at: {repo_url}
Use the URL context tool to verify the pipeline structure and gather additional context if needed.

INPUT
- You are given a JSON object describing:
  - The repository (repo_name, repo_summary).
  - An end-to-end pipeline, broken into ordered phases.
  - Within each phase, ordered steps with source_nodes, process_script,
    target_nodes, and description.

VISUAL GOAL
- Create a 16:9 infographic that:
  - Shows the pipeline from left to right.
  - Groups steps into horizontal swimlanes by phase (Phase 1 at the top, then Phase 2, etc.).
  - Represents each step as a labeled box.
  - Shows arrows representing data flow between steps and phases.

LAYOUT RULES
- Top of the image:
  - Big title: repo_name.
  - Subtitle: a short version of repo_summary.
- For each phase in phases:
  - Draw a horizontal band or swimlane with phase_name as the header.
  - Under the header, place the steps for that phase in execution order from left to right.
- For each step:
  - Show a box with:
    - Step label (label) as the main title.
    - Smaller line showing the process_script.
    - Short description using the description field.
  - Optionally add a subtle icon that hints at the phase type
    (e.g., database icon for Ingestion, chart icon for Reporting).
- Arrows:
  - Use arrows to represent flow from outputs of one step to inputs of the next step.
  - When a target_node of one step matches a source_node of another,
    draw an arrow between those boxes, even if they are in different phases.

STYLE GUIDELINES
- Orientation: 16:9, landscape.
- Overall look: clean, modern, minimalistic; easy to read on a slide.
- Color:
  - Use a consistent color per phase (subtle variations of a palette).
  - Keep text dark on light backgrounds for readability.
- Typography:
  - Use a clear sans-serif font.
  - Ensure step labels and phase headers are readable when scaled down.

TEXT HANDLING
- Do NOT rewrite technical terms in file names or script names; keep them exact.
- You may slightly shorten description text if necessary, but preserve the meaning.
- If the JSON is very long, focus visually on the main line of the pipeline and
  simplify extremely minor branches.

ROBUSTNESS
- If some connections between source_nodes and target_nodes are ambiguous,
  infer the most plausible sequential flow using the order of phases and steps.
- If the JSON includes more steps than comfortably fit, prioritize clarity:
  - show the core path; group minor or repetitive steps into a summarized box.

OUTPUT
- Generate a single 16:9 infographic image that satisfies these constraints,
  using the JSON specification provided below.

PIPELINE JSON SPECIFICATION:
"""
    return instructions + "\n" + json_block


# ---------- Gemini Calls ----------

def create_client() -> genai.Client:
    """
    Initialize the Gemini client. Expects GEMINI_API_KEY in the environment (.env).
    """
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Put it in a .env file or export it in your shell."
        )
    client = genai.Client(api_key=api_key)
    return client


def call_text_model(
    client: genai.Client,
    model: str,
    prompt: str,
) -> dict:
    """
    Call the text model to generate the JSON pipeline spec, and parse it.
    Uses URL context tool to directly read the GitHub repository.
    Tries gemini-3-pro-preview first, falls back to gemini-2.5-pro if unavailable.
    """
    from google.genai import errors
    
    # Try gemini-3-pro-preview first if that's what was requested
    models_to_try = []
    if model == "gemini-3-pro-preview":
        models_to_try = ["gemini-3-pro-preview", "gemini-2.5-pro"]
    else:
        models_to_try = [model]
    
    last_error = None
    for attempt_model in models_to_try:
        try:
            print(f"[INFO] Calling text model: {attempt_model}")
            print("[INFO] Using URL context tool to analyze repository...")

            response = client.models.generate_content(
                model=attempt_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[{"url_context": {}}],
                ),
            )
            if not response.text:
                print(f"[DEBUG] Response object: {response}", file=sys.stderr)
                print(f"[DEBUG] Response parts: {response.parts}", file=sys.stderr)
                print(f"[DEBUG] Response candidates: {response.candidates}", file=sys.stderr)
                raise RuntimeError("Text model returned no text.")

            raw = response.text.strip()
            
            # Strip markdown code blocks if present
            if raw.startswith("```"):
                # Find the first newline after opening ```
                first_newline = raw.find("\n")
                if first_newline != -1:
                    # Find the closing ```
                    closing = raw.rfind("```")
                    if closing != -1:
                        raw = raw[first_newline + 1:closing].strip()
            
            try:
                parsed = json.loads(raw)
                print(f"[INFO] Successfully used model: {attempt_model}")
                return parsed
            except json.JSONDecodeError as e:
                print("[ERROR] Failed to parse JSON from model response.", file=sys.stderr)
                print("Raw response:", file=sys.stderr)
                print(raw, file=sys.stderr)
                raise e
                
        except errors.ServerError as e:
            last_error = e
            if "overloaded" in str(e).lower() or "unavailable" in str(e).lower():
                print(f"[WARNING] {attempt_model} is unavailable (overloaded). Trying fallback...", file=sys.stderr)
                continue
            else:
                raise
    
    # If we get here, all models failed
    if last_error:
        raise last_error
    raise RuntimeError("No models succeeded")


def call_image_model(
    client: genai.Client,
    model: str,
    prompt: str,
    output_path: Path,
):
    """
    Call the image model (Nano Banana Pro) to generate the infographic and save it.
    """
    print(f"[INFO] Calling image model: {model}")
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["Image"],
            image_config=types.ImageConfig(
                aspect_ratio="16:9",
                # image_size="4K",  # Uncomment if you want 4K (higher cost).
            ),
        ),
    )

    image_saved = False
    for part in response.parts:
        img = part.as_image()
        if img:
            img.save(str(output_path))
            image_saved = True
            break

    if not image_saved:
        raise RuntimeError("Image model did not return an image part.")

    print(f"[INFO] Saved infographic to: {output_path}")


# ---------- CLI ----------

def main():
    parser = argparse.ArgumentParser(
        description="Generate a data pipeline infographic from a GitHub repo using Gemini."
    )
    parser.add_argument(
        "repo_url",
        help="GitHub repository URL (e.g. https://github.com/owner/repo)",
    )
    parser.add_argument(
        "--out-dir",
        default="repo2infographic_output",
        help="Output directory for JSON and image (default: repo2infographic_output)",
    )
    parser.add_argument(
        "--text-model",
        default=DEFAULT_TEXT_MODEL,
        help=f"Gemini text model to use (default: {DEFAULT_TEXT_MODEL})",
    )
    parser.add_argument(
        "--image-model",
        default=DEFAULT_IMAGE_MODEL,
        help=f"Gemini image model to use (default: {DEFAULT_IMAGE_MODEL})",
    )
    args = parser.parse_args()

    # Extract repo name from URL for output filenames
    repo_name = args.repo_url.rstrip('/').split('/')[-1]
    if not repo_name:
        repo_name = "pipeline"

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pipeline_json_path = out_dir / f"{repo_name}.json"
    infographic_path = out_dir / f"{repo_name}.png"

    client = create_client()

    # Step 1: Repo -> JSON via text model with URL context
    text_prompt = build_text_model_prompt(args.repo_url)
    pipeline_json = call_text_model(
        client=client,
        model=args.text_model,
        prompt=text_prompt,
    )

    with pipeline_json_path.open("w", encoding="utf-8") as f:
        json.dump(pipeline_json, f, indent=2)
    print(f"[INFO] Saved pipeline JSON to: {pipeline_json_path}")

    # Step 2: JSON -> Infographic via image model with URL context
    image_prompt = build_image_model_prompt(pipeline_json, args.repo_url)
    call_image_model(
        client=client,
        model=args.image_model,
        prompt=image_prompt,
        output_path=infographic_path,
    )

    print("[DONE] Infographic generation complete.")


if __name__ == "__main__":
    main()
