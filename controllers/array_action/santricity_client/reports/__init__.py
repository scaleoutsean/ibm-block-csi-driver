"""Fixed-shape report helpers built on top of raw resources."""

from .controllers import CONTROLLERS, controllers_report
from .facade import ReportsFacade
from .interfaces_report import hostside_interfaces_report

__all__ = ["ReportsFacade", "CONTROLLERS", "controllers_report", "hostside_interfaces_report"]