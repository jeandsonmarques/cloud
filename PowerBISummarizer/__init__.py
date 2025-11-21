import matplotlib.pyplot as plt
from . import resources_rc  # noqa: F401
def classFactory(iface):
    from .data_summarizer import PowerBISummarizer
    return PowerBISummarizer(iface)
