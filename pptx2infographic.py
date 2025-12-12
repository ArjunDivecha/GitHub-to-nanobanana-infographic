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
from pptx import Presentation


# ---------- Configuration ----------

DEFAULT_TEXT_MODEL = "gemini-2.5-pro"
DEFAULT_IMAGE_MODEL = "nano-banana-pro-preview"


# ---------- PowerPoint Extraction ----------

def extract_text_from_pptx(pptx_path: Path) -> dict:
    """
    Extract all text content from a PowerPoint presentation.
    Returns a dictionary with:
    - file_name: name of the pptx file
    - slides: list of slide dictionaries with title and content
    - full_text: concatenated text from all slides
    """
    prs = Presentation(str(pptx_path))

    slides_data = []
    full_text_parts = []

    for slide_num, slide in enumerate(prs.slides, 1):
        slide_title = ""
        slide_content = []

        # Extract text from all shapes
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                text = shape.text.strip()
                # Try to identify if this is a title
                if hasattr(shape, "placeholder_format") and shape.is_placeholder:
                    if shape.placeholder_format.type == 1:  # Title placeholder
                        slide_title = text
                    else:
                        slide_content.append(text)
                else:
                    # First text shape is often the title
                    if not slide_title and len(slide_content) == 0:
                        slide_title = text
                    else:
                        slide_content.append(text)

        if not slide_title:
            slide_title = f"Slide {slide_num}"

        slide_info = {
            "slide_number": slide_num,
            "title": slide_title,
            "content": slide_content
        }
        slides_data.append(slide_info)

        # Build full text
        full_text_parts.append(f"=== Slide {slide_num}: {slide_title} ===")
        for content in slide_content:
            full_text_parts.append(content)
        full_text_parts.append("")  # Empty line between slides

    return {
        "file_name": pptx_path.name,
        "slides": slides_data,
        "full_text": "\n".join(full_text_parts)
    }


# ---------- Prompt Templates ----------

def build_section_analysis_prompt(pptx_data: dict) -> str:
    """
    Build a prompt to analyze the presentation and determine how many infographics to create.
    """
    instructions = f"""
You are a presentation analyst. Your task is to analyze a PowerPoint presentation and determine how many distinct infographics should be created from it.

PRESENTATION: {pptx_data['file_name']}

The presentation contains {len(pptx_data['slides'])} slides with the following content:

{pptx_data['full_text']}

ANALYSIS TASK:
Examine the presentation and identify distinct workflows, pipelines, or process flows that should each have their own infographic.

CRITERIA FOR SEPARATING INTO MULTIPLE INFOGRAPHICS:
- Different workflows or processes (e.g., "Data Ingestion Pipeline" vs "Reporting Pipeline")
- Distinct systems or components (e.g., "Frontend Flow" vs "Backend Flow")
- Separate use cases or scenarios (e.g., "User Registration" vs "User Login")
- Major topic changes that represent independent processes
- Slides that explicitly separate different workflows (e.g., section dividers)

CRITERIA FOR COMBINING INTO ONE INFOGRAPHIC:
- A single end-to-end workflow described across multiple slides
- Sequential steps in the same process
- Different phases of the same pipeline
- Related sub-processes that feed into each other

OUTPUT REQUIREMENTS:
Return a JSON object with this structure:
{{
  "presentation_name": "short name",
  "total_infographics": number (1 or more),
  "infographics": [
    {{
      "infographic_id": 1,
      "title": "concise title for this infographic",
      "slide_range": "e.g., '1-5' or '6-10'",
      "description": "1 sentence describing what this infographic will show",
      "slide_numbers": [1, 2, 3, 4, 5]
    }}
  ]
}}

IMPORTANT:
- If the presentation describes ONE cohesive workflow/pipeline, return total_infographics: 1
- If it contains MULTIPLE distinct workflows, create separate infographics for each
- slide_numbers should list all slide numbers (1-indexed) that belong to that infographic
- Respond with VALID JSON ONLY (no backticks, no explanations)
"""
    return instructions


def build_text_model_prompt(pptx_data: dict, slide_numbers: list = None, infographic_title: str = None) -> str:
    """
    Build the full prompt for the text model (Gemini) to produce the JSON pipeline spec
    from PowerPoint content.
    If slide_numbers is provided, only include those slides.
    """
    # Filter slides if specific slide numbers are provided
    if slide_numbers:
        filtered_slides = [s for s in pptx_data['slides'] if s['slide_number'] in slide_numbers]
        full_text_parts = []
        for slide in filtered_slides:
            full_text_parts.append(f"=== Slide {slide['slide_number']}: {slide['title']} ===")
            for content in slide['content']:
                full_text_parts.append(content)
            full_text_parts.append("")
        filtered_text = "\n".join(full_text_parts)
        slide_count = len(filtered_slides)
    else:
        filtered_text = pptx_data['full_text']
        slide_count = len(pptx_data['slides'])

    title_context = f"\nINFOGRAPHIC TITLE: {infographic_title}\n" if infographic_title else ""

    instructions = f"""
You are a Principal Systems Architect. Your task is to analyze a PowerPoint presentation and extract its workflow, process, or data pipeline structure.

PRESENTATION: {pptx_data['file_name']}
{title_context}
The following {slide_count} slides will be analyzed:

{filtered_text}

CRITICAL INSTRUCTIONS FOR ANALYSIS:
1. **Understand the Flow**: Analyze the slides to identify the main process, workflow, or data pipeline being described.
2. **Identify Phases**: Look for major stages or phases in the process (e.g., "Data Collection", "Processing", "Analysis", "Output").
3. **Extract Steps**: Within each phase, identify specific steps, actions, or transformations.
4. **Detect Data Movement**: Look for:
   - Input sources (files, APIs, user input, databases)
   - Processing steps (transformations, validations, computations)
   - Output destinations (files, dashboards, APIs, databases)
5. **Capture Logic**: Note any:
   - Decision points (if/then logic, branching)
   - Feedback loops (iterations, retries)
   - External services or dependencies

HIGH-LEVEL OBJECTIVE
- Discover the workflow or pipeline described in this presentation.
- Organize it as a set of ordered phases and steps.
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

- repo_name: short name for this infographic (use the infographic title if provided, otherwise the file name).
- repo_summary: 1–3 sentences describing what this workflow covers.
- pipeline_overview: 1–2 sentences summarizing the workflow/pipeline described.
- phases: an array of phase objects, ordered by execution.
  - Each phase object:
    - phase_id: string like "1", "2", ...
    - phase_name: string like "1. Ingestion".
    - phase_purpose: one-sentence explanation of the phase.
    - steps: array of step objects, ordered by execution within the phase.
      - Each step object:
        - step_id: string like "1.1", "1.2", "2.1", etc.
        - label: very short human-readable name to show inside a box.
        - source_nodes: array of inputs (files, APIs, user input, databases, slide references).
        - process_script: the tool, system, or module executing the logic (e.g., "Python Script", "ETL Tool", "Slide 3").
        - target_nodes: array of outputs (files, API responses, databases, next steps).
        - description: concise summary (5–10 words) of what the step does.
        - notes (optional): any important nuance, assumptions, or decision logic.

RULES AND CONSTRAINTS
- Extract information ONLY from the presentation content provided.
- Be specific about "source_nodes" and "target_nodes".
- Capture the logical flow/pipeline order as presented in the slides.
- If the presentation doesn't clearly describe a pipeline, infer a reasonable workflow structure.

OUTPUT FORMAT (IMPORTANT)
- Respond with VALID JSON ONLY.
- Do not wrap the JSON in backticks.
- Do not include any explanation, prose, or comments.
- The response must be directly parseable as JSON.
"""
    return instructions


def build_image_model_prompt(pipeline_json: dict, style: str = None) -> str:
    """
    Build the full prompt for the image model (Nano Banana Pro) to create the infographic.
    """
    json_block = json.dumps(pipeline_json, indent=2)

    # Build style instruction if provided
    style_instruction = ""
    if style:
        style_instruction = f"""

VISUAL STYLE REQUIREMENT
Create the infographic in a '{style}' visual style. Apply this style consistently across:
- Overall aesthetic and color palette
- Typography and text rendering
- Icons and visual elements
- Box designs and shapes
- Background and layout
- Arrows and connectors

Examples of how to interpret styles:
- 'lego': Bright primary colors, blocky shapes, toy-like 3D appearance, snap-together aesthetic
- 'ghibli': Hand-drawn feel, soft watercolor palette, whimsical organic shapes, Studio Ghibli anime aesthetic
- 'cyberpunk': Neon colors, dark background, glowing elements, futuristic tech aesthetic, grid patterns
- 'minimalist': Clean white/gray palette, thin lines, lots of whitespace, simple sans-serif fonts
- 'blueprint': Technical drawing style, blue background, white lines, grid paper, architectural feel
- 'hand-drawn': Sketchy lines, imperfect shapes, notebook paper feel, casual doodle aesthetic

Apply the '{style}' style thoughtfully to create a cohesive, visually striking infographic.
"""

    instructions = f"""
You are an expert data visualization designer using Nano Banana Pro (Gemini 3 Pro Image).
Your task is to turn a JSON specification of a workflow/pipeline into a clear,
modern 16:9 infographic.
{style_instruction}

INPUT
- You are given a JSON object describing:
  - A presentation name and summary.
  - An end-to-end pipeline/workflow, broken into ordered phases.
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
  - Big title: repo_name (the presentation name).
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
- Keep technical terms and file names exact.
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
            print("[INFO] Analyzing PowerPoint presentation...")

            response = client.models.generate_content(
                model=attempt_model,
                contents=prompt,
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
        description="Generate workflow/pipeline infographics from a PowerPoint file using Gemini."
    )
    parser.add_argument(
        "pptx_file",
        help="Path to PowerPoint (.pptx) file",
    )
    parser.add_argument(
        "--out-dir",
        default="pptx2infographic_output",
        help="Output directory for JSON and image (default: pptx2infographic_output)",
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
    parser.add_argument(
        "--style",
        default=None,
        help="Visual style for the infographic (e.g., 'lego', 'ghibli', 'cyberpunk', 'minimalist', 'blueprint', 'hand-drawn')",
    )
    args = parser.parse_args()

    # Validate pptx file exists
    pptx_path = Path(args.pptx_file)
    if not pptx_path.exists():
        print(f"[ERROR] File not found: {pptx_path}", file=sys.stderr)
        sys.exit(1)

    if not pptx_path.suffix.lower() == '.pptx':
        print(f"[ERROR] File must be a .pptx file: {pptx_path}", file=sys.stderr)
        sys.exit(1)

    # Extract base name for output files
    base_name = pptx_path.stem

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = create_client()

    # Step 1: Extract text from PowerPoint
    print(f"[INFO] Extracting text from: {pptx_path}")
    pptx_data = extract_text_from_pptx(pptx_path)
    print(f"[INFO] Extracted {len(pptx_data['slides'])} slides")

    # Step 2: Analyze presentation to determine how many infographics to create
    print("[INFO] Analyzing presentation structure...")
    analysis_prompt = build_section_analysis_prompt(pptx_data)
    analysis_result = call_text_model(
        client=client,
        model=args.text_model,
        prompt=analysis_prompt,
    )

    total_infographics = analysis_result.get('total_infographics', 1)
    infographics_spec = analysis_result.get('infographics', [])

    print(f"[INFO] Will generate {total_infographics} infographic(s)")

    # Save analysis results
    analysis_path = out_dir / f"{base_name}_analysis.json"
    with analysis_path.open("w", encoding="utf-8") as f:
        json.dump(analysis_result, f, indent=2)
    print(f"[INFO] Saved analysis to: {analysis_path}")

    # Step 3: Generate each infographic
    for spec in infographics_spec:
        infographic_id = spec['infographic_id']
        title = spec['title']
        slide_numbers = spec['slide_numbers']

        print(f"\n[INFO] ===== Generating Infographic {infographic_id}/{total_infographics}: {title} =====")
        print(f"[INFO] Using slides: {slide_numbers}")

        # Generate pipeline JSON for this section
        text_prompt = build_text_model_prompt(
            pptx_data,
            slide_numbers=slide_numbers,
            infographic_title=title
        )
        pipeline_json = call_text_model(
            client=client,
            model=args.text_model,
            prompt=text_prompt,
        )

        # Create safe filename from title
        safe_title = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in title)
        safe_title = safe_title.replace(' ', '_')

        # Save pipeline JSON
        pipeline_json_path = out_dir / f"{base_name}_{infographic_id:02d}_{safe_title}.json"
        with pipeline_json_path.open("w", encoding="utf-8") as f:
            json.dump(pipeline_json, f, indent=2)
        print(f"[INFO] Saved pipeline JSON to: {pipeline_json_path}")

        # Generate infographic image
        infographic_path = out_dir / f"{base_name}_{infographic_id:02d}_{safe_title}.png"
        image_prompt = build_image_model_prompt(pipeline_json, args.style)
        call_image_model(
            client=client,
            model=args.image_model,
            prompt=image_prompt,
            output_path=infographic_path,
        )

    print(f"\n[DONE] Generated {total_infographics} infographic(s) successfully.")


if __name__ == "__main__":
    main()
