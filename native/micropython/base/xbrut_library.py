"""Small offline library model for the portrait interaction checkpoint."""
import os
from xbrut_paths import DOCUMENTS_PATH


class Library:
    PROJECT_NAME = "xViewer"
    PROJECT_VERSION = "0.1.0"

    def __init__(self, path=DOCUMENTS_PATH):
        self.path = path

    def home(self, ui, focus=0):
        try:
            names = sorted(name for name in os.listdir(self.path) if name.lower().endswith((".xtc", ".xth")))
        except OSError:
            names = []
        ui.document_grid(self.PROJECT_NAME, [(name, name) for name in names], focus)
