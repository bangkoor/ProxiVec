def classFactory(iface):
    """Load ProxiVec plugin."""
    from .proxivec_plugin import ProxiVecPlugin

    return ProxiVecPlugin(iface)
