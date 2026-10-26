"""Compatibility entry point for the Gradio lab: python app.py."""

import os

from autoassess.web.lab import *  # noqa: F403

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "7860")))  # noqa: F405
