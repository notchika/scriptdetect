# Scripture Detector

A FastAPI web app that detects scripture references in text or sermon transcripts.

## Detection types

| Type | Description |
|------|-------------|
| Direct Quote | Verbatim or near-verbatim scripture |
| Paraphrase | Reworded scripture with same meaning |
| Semantic Allusion | Language that echoes scripture themes |
| Story Reference | Biblical stories, events, characters |

## Setup

```bash
pip install -r requirements.txt
```

## Run

```bash
export ANTHROPIC_API_KEY=your_key_here
uvicorn main:app --reload --port 8000
```

Then open http://localhost:8000

## Integration with your transcription app

POST to `/detect` with JSON body:

```json
{
  "text": "Your transcribed text here"
}
```

Response:

```json
{
  "detections": [
    {
      "type": "direct_quote | paraphrase | semantic_allusion | story_reference",
      "reference": "John 3:16",
      "canonical_text": "For God so loved the world...",
      "detected_phrase": "phrase from the input",
      "confidence": "high | medium | low",
      "explanation": "Why this matches"
    }
  ],
  "summary": "Thematic summary"
}
```

## Keyboard shortcut

`Ctrl+Enter` / `Cmd+Enter` triggers detection from the textarea.