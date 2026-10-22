# Deploying the demo on Render (free)

The demo is `app.py`, a Gradio app. `render.yaml` describes it as a free Render
web service, so deploying is a few clicks.

1. Sign in at [render.com](https://render.com) with GitHub.
2. **New > Blueprint**, pick `DA7016_Auto_Assessment_System`, branch `main`, and apply.
3. Open the `red-ink-grader` service, **Environment**, and fill in the keys
   marked "sync: false": `OPENROUTER_API_KEY`, `BODHAN_OCR_API_KEY`,
   `BODHAN_TRANSLATE_API_KEY`, and optionally `GEMINI_API_KEY`.
4. Wait for the build (about 5 minutes) and open the `onrender.com` link.

## What it costs

- Render's free plan costs nothing. The service sleeps after 15 minutes
  without visitors and takes about a minute to wake, so open the link a
  minute before a demo.
- Each sheet marked with the LLM grader makes about 15 to 25 calls to
  `google/gemini-2.5-flash` on OpenRouter: a few cents a sheet (measured: see the README).
- A scanned page read by Bodhan IndicOCR costs about Rs 0.20. Typed `.txt`
  sheets cost nothing to read.
- Guards: `OPENROUTER_BUDGET_USD` and `BODHAN_BUDGET_INR` stop paid calls at
  those totals, and `AUTOASSESS_DEMO_DAILY_SHEETS` caps LLM-marked sheets per
  day (after that the free lexical baseline marks them and the page says so).
  The guards' ledgers live in `/tmp`, which Render clears on each restart, so
  also keep an eye on the OpenRouter dashboard.

## Switching the model

Set `AUTOASSESS_LLM_PROVIDER=gemini` to use the free Gemini key instead, but
not for real students' sheets: Google's free tier may use prompts for training.
For real sheets set `AUTOASSESS_REAL_SHEETS=1`, which refuses the free tier.
