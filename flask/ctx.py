from __future__ import annotations

import contextvars
import sys
import typing as t
from functools import update_wrapper
from types import TracebackType

from werkzeug.exceptions import HTTPException

from . import typing as ft
from .globals import _cv_app
from .globals import _cv_request
from .signals import appcontext_popped
from .signals import appcontext_pushed

if t.TYPE_CHECKING:  # pragma: no cover
    from _typeshed.wsgi import WSGIEnvironment

    from .app import Flask
    from .sessions import SessionMixin
    from .wrappers import Request

_sentinel = object()


class _AppCtxGlobals:
    """
    应用上下文全局变量类，用于在应用生命周期内存储全局变量。
    """

    def __getattr__(self, name: str) -> t.Any:
        """
        获取属性值。

        参数:
        name (str): 属性名。

        返回:
        t.Any: 属性值。

        异常:
        AttributeError: 如果属性不存在，则抛出异常。
        """
        try:
            return self.__dict__[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name: str, value: t.Any) -> None:
        """
        设置属性值。

        参数:
        name (str): 属性名。
        value (t.Any): 属性值。
        """
        self.__dict__[name] = value

    def __delattr__(self, name: str) -> None:
        """
        删除属性。

        参数:
        name (str): 属性名。

        异常:
        AttributeError: 如果属性不存在，则抛出异常。
        """
        try:
            del self.__dict__[name]
        except KeyError:
            raise AttributeError(name) from None

    def get(self, name: str, default: t.Any | None = None) -> t.Any:
        """
        获取属性值，如果属性不存在则返回默认值。

        参数:
        name (str): 属性名。
        default (t.Any | None): 默认值。

        返回:
        t.Any: 属性值或默认值。
        """
        return self.__dict__.get(name, default)

    def pop(self, name: str, default: t.Any = _sentinel) -> t.Any:
        """
        移除并返回属性值，如果属性不存在则返回默认值。

        参数:
        name (str): 属性名。
        default (t.Any): 默认值。

        返回:
        t.Any: 属性值或默认值。
        """
        if default is _sentinel:
            return self.__dict__.pop(name)
        else:
            return self.__dict__.pop(name, default)

    def setdefault(self, name: str, default: t.Any = None) -> t.Any:
        """
        如果属性不存在，则设置属性值为默认值，并返回属性值。

        参数:
        name (str): 属性名。
        default (t.Any): 默认值。

        返回:
        t.Any: 属性值。
        """
        return self.__dict__.setdefault(name, default)

    def __contains__(self, item: str) -> bool:
        """
        检查是否包含指定的属性。

        参数:
        item (str): 属性名。

        返回:
        bool: 是否包含属性。
        """
        return item in self.__dict__

    def __iter__(self) -> t.Iterator[str]:
        """
        返回属性迭代器。

        返回:
        t.Iterator[str]: 属性迭代器。
        """
        return iter(self.__dict__)

    def __repr__(self) -> str:
        """
        返回对象的字符串表示。

        返回:
        str: 对象的字符串表示。
        """
        ctx = _cv_app.get(None)
        if ctx is not None:
            return f"<flask.g of '{ctx.app.name}'>"
        return object.__repr__(self)


def after_this_request(
    f: ft.AfterRequestCallable[t.Any],
) -> ft.AfterRequestCallable[t.Any]:
    """
    在请求结束后执行指定的函数。

    参数:
    f (ft.AfterRequestCallable[t.Any]): 请求结束后要执行的函数。

    返回:
    ft.AfterRequestCallable[t.Any]: 装饰后的函数。

    异常:
    RuntimeError: 如果没有激活的请求上下文，则抛出异常。
    """
    ctx = _cv_request.get(None)

    if ctx is None:
        raise RuntimeError(
            "'after_this_request' can only be used when a request"
            " context is active, such as in a view function."
        )

    ctx._after_request_functions.append(f)
    return f


F = t.TypeVar("F", bound=t.Callable[..., t.Any])


def copy_current_request_context(f: F) -> F:
    """
    复制当前请求上下文并应用于函数。

    参数:
    f (F): 要应用上下文的函数。

    返回:
    F: 装饰后的函数。

    异常:
    RuntimeError: 如果没有激活的请求上下文，则抛出异常。
    """
    ctx = _cv_request.get(None)

    if ctx is None:
        raise RuntimeError(
            "'copy_current_request_context' can only be used when a"
            " request context is active, such as in a view function."
        )

    ctx = ctx.copy()

    def wrapper(*args: t.Any, **kwargs: t.Any) -> t.Any:
        with ctx:  # type: ignore[union-attr]
            return ctx.app.ensure_sync(f)(*args, **kwargs)  # type: ignore[union-attr]

    return update_wrapper(wrapper, f)  # type: ignore[return-value]


def has_request_context() -> bool:
    """
    检查是否有激活的请求上下文。

    返回:
    bool: 是否有激活的请求上下文。
    """
    return _cv_request.get(None) is not None


def has_app_context() -> bool:
    """
    检查是否有激活的应用上下文。

    返回:
    bool: 是否有激活的应用上下文。
    """
    return _cv_app.get(None) is not None

class AppContext:
    """
    应用上下文类，用于管理应用层面的上下文变量和URL适配。

    :param app: Flask应用实例，用于创建URL适配器和管理全局变量。
    """
    def __init__(self, app: Flask) -> None:
        self.app = app
        self.url_adapter = app.create_url_adapter(None)
        self.g: _AppCtxGlobals = app.app_ctx_globals_class()
        self._cv_tokens: list[contextvars.Token[AppContext]] = []

    def push(self) -> None:
        """
        将当前应用上下文压入上下文栈中，并发送应用上下文推送信号。
        """
        self._cv_tokens.append(_cv_app.set(self))
        appcontext_pushed.send(self.app, _async_wrapper=self.app.ensure_sync)

    def pop(self, exc: BaseException | None = _sentinel) -> None:  # type: ignore
        """
        从上下文栈中弹出当前应用上下文，并发送应用上下文弹出信号。

        :param exc: 异常实例，用于在发生异常时进行上下文清理。
        """
        try:
            if len(self._cv_tokens) == 1:
                if exc is _sentinel:
                    exc = sys.exc_info()[1]
                self.app.do_teardown_appcontext(exc)
        finally:
            ctx = _cv_app.get()
            _cv_app.reset(self._cv_tokens.pop())

        if ctx is not self:
            raise AssertionError(
                f"Popped wrong app context. ({ctx!r} instead of {self!r})"
            )

        appcontext_popped.send(self.app, _async_wrapper=self.app.ensure_sync)

    def __enter__(self) -> AppContext:
        """
        上下文管理器的进入方法，用于在进入时自动推送应用上下文。
        """
        self.push()
        return self

    def __exit__(
        self,
        exc_type: type | None,
        exc_value: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """
        上下文管理器的退出方法，用于在退出时自动弹出应用上下文。
        """
        self.pop(exc_value)


class RequestContext:
    """
    请求上下文类，用于管理请求层面的上下文变量、URL适配和请求匹配。

    :param app: Flask应用实例。
    :param environ: WSGI环境变量。
    :param request: 请求实例，如果未提供则会根据环境变量创建。
    :param session: 会话实例，用于管理请求中的会话信息。
    """
    def __init__(
        self,
        app: Flask,
        environ: WSGIEnvironment,
        request: Request | None = None,
        session: SessionMixin | None = None,
    ) -> None:
        self.app = app
        if request is None:
            request = app.request_class(environ)
            request.json_module = app.json
        self.request: Request = request
        self.url_adapter = None
        try:
            self.url_adapter = app.create_url_adapter(self.request)
        except HTTPException as e:
            self.request.routing_exception = e
        self.flashes: list[tuple[str, str]] | None = None
        self.session: SessionMixin | None = session
        self._after_request_functions: list[ft.AfterRequestCallable[t.Any]] = []
        self._cv_tokens: list[
            tuple[contextvars.Token[RequestContext], AppContext | None]
        ] = []

    def copy(self) -> RequestContext:
        """
        复制当前请求上下文，用于创建与当前上下文相同的新实例。

        :return: 新的请求上下文实例。
        """
        return self.__class__(
            self.app,
            environ=self.request.environ,
            request=self.request,
            session=self.session,
        )

    def match_request(self) -> None:
        """
        匹配当前请求到URL适配器，用于确定请求的路由规则和视图参数。
        """
        try:
            result = self.url_adapter.match(return_rule=True)  # type: ignore
            self.request.url_rule, self.request.view_args = result  # type: ignore
        except HTTPException as e:
            self.request.routing_exception = e

    def push(self) -> None:
        """
        将当前请求上下文压入上下文栈中，并发送请求上下文推送信号。
        """
        app_ctx = _cv_app.get(None)

        if app_ctx is None or app_ctx.app is not self.app:
            app_ctx = self.app.app_context()
            app_ctx.push()
        else:
            app_ctx = None

        self._cv_tokens.append((_cv_request.set(self), app_ctx))

        if self.session is None:
            session_interface = self.app.session_interface
            self.session = session_interface.open_session(self.app, self.request)

            if self.session is None:
                self.session = session_interface.make_null_session(self.app)

        if self.url_adapter is not None:
            self.match_request()

    def pop(self, exc: BaseException | None = _sentinel) -> None:  # type: ignore
        """
        从上下文栈中弹出当前请求上下文，并发送请求上下文弹出信号。

        :param exc: 异常实例，用于在发生异常时进行上下文清理。
        """
        clear_request = len(self._cv_tokens) == 1

        try:
            if clear_request:
                if exc is _sentinel:
                    exc = sys.exc_info()[1]
                self.app.do_teardown_request(exc)

                request_close = getattr(self.request, "close", None)
                if request_close is not None:
                    request_close()
        finally:
            ctx = _cv_request.get()
            token, app_ctx = self._cv_tokens.pop()
            _cv_request.reset(token)

            if clear_request:
                ctx.request.environ["werkzeug.request"] = None

            if app_ctx is not None:
                app_ctx.pop(exc)

            if ctx is not self:
                raise AssertionError(
                    f"Popped wrong request context. ({ctx!r} instead of {self!r})"
                )

    def __enter__(self) -> RequestContext:
        """
        上下文管理器的进入方法，用于在进入时自动推送请求上下文。
        """
        self.push()
        return self

    def __exit__(
        self,
        exc_type: type | None,
        exc_value: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """
        上下文管理器的退出方法，用于在退出时自动弹出请求上下文。
        """
        self.pop(exc_value)

    def __repr__(self) -> str:
        """
        请求上下文的字符串表示，包含请求URL和方法以及所属应用名称。

        :return: 请求上下文的字符串表示。
        """
        return (
            f"<{type(self).__name__} {self.request.url!r}"
            f" [{self.request.method}] of {self.app.name}>"
        )

