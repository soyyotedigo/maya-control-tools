import os


def load_stylesheet() -> str:
    qss = os.path.join(os.path.dirname(__file__), "controlme.qss")
    with open(qss, encoding="utf-8") as f:
        return f.read()
