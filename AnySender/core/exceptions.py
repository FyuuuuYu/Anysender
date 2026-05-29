class AnySenderError(Exception):
    pass


class PluginLoadError(AnySenderError):
    pass


class PluginExecutionError(AnySenderError):
    pass


class ConfigValidationError(AnySenderError):
    pass


class TimeoutError(AnySenderError):
    pass
