"""AI Baton: shared memory, project knowledge and usage for coding agents."""
from . import winenv

winenv.restore()  # Before any module reads the home folder (Codex starts Windows hooks with an empty environment).
