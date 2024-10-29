from __future__ import annotations

import typing as t

from . import json as json
from .app import Flask as Flask
from .blueprints import Blueprint as Blueprint
from .config import Config as Config
from .ctx import after_this_request as after_this_request
from .ctx import copy_current_request_context as copy_current_request_context
from .ctx import has_app_context as has_app_context
from .ctx import has_request_context as has_request_context
from .globals import current_app as current_app
from .globals import g as g
from .globals import request as request
from .globals import session as session
from .helpers import abort as abort
from .helpers import flash as flash
from .helpers import get_flashed_messages as get_flashed_messages
from .helpers import get_template_attribute as get_template_attribute
from .helpers import make_response as make_response
from .helpers import redirect as redirect
from .helpers import send_file as send_file
from .helpers import send_from_directory as send_from_directory
from .helpers import stream_with_context as stream_with_context
from .helpers import url_for as url_for
from .json import jsonify as jsonify
from .signals import appcontext_popped as appcontext_popped
from .signals import appcontext_pushed as appcontext_pushed
from .signals import appcontext_tearing_down as appcontext_tearing_down
from .signals import before_render_template as before_render_template
from .signals import got_request_exception as got_request_exception
from .signals import message_flashed as message_flashed
from .signals import request_finished as request_finished
from .signals import request_started as request_started
from .signals import request_tearing_down as request_tearing_down
from .signals import template_rendered as template_rendered
from .templating import render_template as render_template
from .templating import render_template_string as render_template_string
from .templating import stream_template as stream_template
from .templating import stream_template_string as stream_template_string
from .wrappers import Request as Request
from .wrappers import Response as Response


def __getattr__(name: str) -> t.Any:
    """
    自定义__getattr__方法，处理特定属性的动态获取。

    当尝试获取对象的属性时，如果属性名称为'__version__'，则发出过时警告并动态获取Flask的版本信息。
    否则，如果请求的属性不是'__version__'，则抛出AttributeError异常。

    参数:
    name (str): 尝试获取的属性名称。

    返回:
    t.Any: 动态获取的属性值，通常为字符串类型。

    异常:
    AttributeError: 如果请求的属性不是'__version__'，则抛出此异常。
    """
    if name == "__version__":
        # 导入importlib.metadata模块以动态获取Flask版本信息。
        import importlib.metadata
        # 导入warnings模块用于发出过时警告。
        import warnings

        # 发出过时警告，说明'__version__'属性将在Flask 3.1中移除，并提供替代方法。
        warnings.warn(
            "The '__version__' attribute is deprecated and will be removed in"
            " Flask 3.1. Use feature detection or"
            " 'importlib.metadata.version(\"flask\")' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        # 动态获取并返回Flask的版本信息。
        return importlib.metadata.version("flask")

    # 如果请求的属性不是'__version__'，抛出AttributeError异常。
    raise AttributeError(name)

