# GitHub to Nano Banana Infographic

Generate a data pipeline infographic from any GitHub repo using Gemini:

1. Gemini 3 Pro analyzes the repo and produces a JSON pipeline spec.
2. Nano Banana Pro (Gemini 3 Pro Image) converts that JSON into a 16:9 infographic.

---

## Setup

### 1. Clone this repo

```bash
git clone https://github.com/ArjunDivecha/GitHub-to-nanobanana-infographic
cd GitHub-to-nanobanana-infographic
```

### 2. Python environment

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure Gemini API key

Copy the example env file and edit:

```bash
cp .env.example .env
```

Then open `.env` and set:

```
GEMINI_API_KEY=your_real_api_key_here
```

---

## Usage

### Basic usage:

```bash
python repo2infographic.py https://github.com/owner/some-repo
```

This will:
- Clone the target repo into a temporary directory.
- Analyze the codebase and infer a data pipeline.
- Save a JSON spec to: `repo2infographic_output/pipeline.json`
- Generate a 16:9 infographic and save it to: `repo2infographic_output/pipeline.png`

### You can customize:

```bash
python repo2infographic.py \
  https://github.com/owner/some-repo \
  --out-dir my_output \
  --text-model gemini-3-pro-preview \
  --image-model gemini-3-pro-image-preview
```

### Keep cloned repo for debugging

Add `--keep-temp` if you want to inspect the cloned repo used for analysis:

```bash
python repo2infographic.py https://github.com/owner/some-repo --keep-temp
```

---

## How It Works

1. **Clone**
   The script clones the target GitHub repo into a temporary directory.

2. **Build Context**
   It walks the repo, selects up to 40 relevant files (`.py`, `.js`, configs, etc.) and builds a textual context (file list + truncated contents).

3. **Text Model (Pipeline JSON)**
   It sends a structured prompt and the repo context to Gemini 3 Pro (default `gemini-3-pro-preview`), which returns a JSON object describing:
   - `repo_name`
   - `repo_summary`
   - `pipeline_overview`
   - `phases` and `steps` (with `source_nodes`, `process_script`, `target_nodes`, `description`)

4. **Image Model (Infographic)**
   It feeds that JSON into Nano Banana Pro (`gemini-3-pro-image-preview`) with layout instructions:
   - Phases as horizontal swimlanes.
   - Steps as labeled boxes.
   - Arrows representing flow between steps.

5. **Outputs**
   - `pipeline.json` – canonical pipeline spec.
   - `pipeline.png` – infographic ready for slides, docs, etc.

---

## Notes & Limitations

- Works best on small–medium repos with clear data-processing pipelines.
- For very large monorepos, you may want to:
  - Increase `max_files` / `max_chars_per_file` in `repo2infographic.py`.
  - Add include/exclude patterns for specific directories.
- The models may occasionally misinterpret edge cases; treat the output as a draft diagram you can refine.

---

## License

MIT (or whatever you prefer).
