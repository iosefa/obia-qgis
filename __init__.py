"""OBIA Processing plugin. Scientific imports run only in the private engine."""


def classFactory(iface):
    from .obia_plugin import OBIAPlugin

    return OBIAPlugin(iface)
