"""Importing this package registers every handler in handlers/*.py.

Add a new feature by dropping a file in this directory with an @handler-
decorated function inside it -- nothing else needs to change (PLAN.md section 3).
"""
from __future__ import annotations

import importlib
import pkgutil

for _module_info in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_module_info.name}")
