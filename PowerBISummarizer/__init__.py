import matplotlib.pyplot as plt
def classFactory(iface):
    from .data_summarizer import PowerBISummarizer
    return PowerBISummarizer(iface)
