from __future__ import annotations

import typing as t

from . import typing as ft
from .globals import current_app
from .globals import request

F = t.TypeVar("F", bound=t.Callable[..., t.Any])

http_method_funcs = frozenset(
    ["get", "post", "head", "options", "delete", "put", "trace", "patch"]
)

# 这段代码定义了一个 View 类，用于处理 HTTP 请求。主要功能如下：
# 类属性：
# methods: 定义允许的 HTTP 方法。
# provide_automatic_options: 是否自动提供 OPTIONS 方法。
# decorators: 用于装饰视图函数的装饰器列表。
# init_every_request: 是否在每次请求时初始化视图实例。
# 方法：
# dispatch_request(self) -> ft.ResponseReturnValue: 抽象方法，子类必须实现，用于处理请求并返回响应。
# as_view(cls, name: str, *class_args: t.Any, **class_kwargs: t.Any) -> ft.RouteCallable: 类方法，将视图类转换为视图函数，用于路由注册。
# 逻辑：
# 根据 init_every_request 的值决定是否在每次请求时创建新的视图实例。
# 应用装饰器（如果有）。
# 设置视图函数的元数据（名称、文档、模块、方法等）。
class View:
    methods: t.ClassVar[t.Collection[str] | None] = None

    provide_automatic_options: t.ClassVar[bool | None] = None

    decorators: t.ClassVar[list[t.Callable[[F], F]]] = []

    init_every_request: t.ClassVar[bool] = True

    def dispatch_request(self) -> ft.ResponseReturnValue:
        raise NotImplementedError()

    @classmethod
    def as_view(
        cls, name: str, *class_args: t.Any, **class_kwargs: t.Any
    ) -> ft.RouteCallable:
        """
        将视图类转换为视图函数，以便Flask能够使用它作为路由处理函数。

        参数:
        - name: 视图的名称，用于路由。
        - class_args: 传递给视图类构造器的位置参数。
        - class_kwargs: 传递给视图类构造器的关键字参数。

        返回:
        - 一个视图函数，它将使用类的实例来处理请求。
        """
        # 根据是否需要为每个请求初始化视图类的实例来定义视图函数
        if cls.init_every_request:

            def view(**kwargs: t.Any) -> ft.ResponseReturnValue:
                """
                视图函数，为每个请求创建新的视图类实例并调用其dispatch_request方法。

                参数:
                - kwargs: 从URL规则中提取的参数。

                返回:
                - 处理请求的响应。
                """
                self = view.view_class(  # type: ignore[attr-defined]
                    *class_args, **class_kwargs
                )
                return current_app.ensure_sync(self.dispatch_request)(**kwargs)  # type: ignore[no-any-return]

        else:
            # 如果不需要为每个请求初始化实例，则在as_view调用时创建实例
            self = cls(*class_args, **class_kwargs)

            def view(**kwargs: t.Any) -> ft.ResponseReturnValue:
                """
                视图函数，使用已创建的视图类实例调用其dispatch_request方法。

                参数:
                - kwargs: 从URL规则中提取的参数。

                返回:
                - 处理请求的响应。
                """
                return current_app.ensure_sync(self.dispatch_request)(**kwargs)  # type: ignore[no-any-return]

        # 应用装饰器，如果有的话
        if cls.decorators:
            view.__name__ = name
            view.__module__ = cls.__module__
            for decorator in cls.decorators:
                view = decorator(view)

        # 设置视图函数的属性，以便Flask能够正确地处理路由和选项
        view.view_class = cls  # type: ignore
        view.__name__ = name
        view.__doc__ = cls.__doc__
        view.__module__ = cls.__module__
        view.methods = cls.methods  # type: ignore
        view.provide_automatic_options = cls.provide_automatic_options  # type: ignore
        return view


# __init_subclass__ 方法
# 初始化子类：调用父类的 __init_subclass__ 方法。
# 检查 methods 属性：如果子类没有定义 methods 属性，则创建一个空集合 methods。
# 继承基类的方法：遍历所有基类，将基类的 methods 属性添加到 methods 集合中。
# 添加 HTTP 方法：遍历 http_method_funcs 列表，检查子类是否实现了这些方法，如果实现了则将其添加到 methods 集合中。
# 设置 methods 属性：如果 methods 集合不为空，则将其赋值给子类的 methods 属性。
# dispatch_request 方法
# 获取请求方法：根据当前请求的 HTTP 方法，获取对应的处理方法。
# 处理 HEAD 请求：如果请求方法为 HEAD 且没有找到对应的处理方法，则尝试使用 get 方法。
# 断言方法存在：确保找到的处理方法不为 None，否则抛出异常。
# 调用处理方法：调用找到的处理方法并返回结果。
class MethodView(View):
    def __init_subclass__(cls, **kwargs: t.Any) -> None:
        """
        初始化子类时调用的方法。

        该方法通过收集当前类及其基类中的HTTP方法，构建一个包含所有可继承HTTP方法的集合。
        如果子类没有定义'methods'属性，它将自动收集并设置这个属性。

        参数:
        - **kwargs: 任意额外的关键字参数，传递给MRO链中的下一个类的__init_subclass__方法。

        返回值:
        - 无返回值。
        """
        super().__init_subclass__(**kwargs)

        # 检查当前类是否已经定义了'methods'属性，如果没有，则进行初始化设置
        if "methods" not in cls.__dict__:
            methods = set()

            # 遍历所有基类，收集它们的'methods'属性，如果存在的话
            for base in cls.__bases__:
                if getattr(base, "methods", None):
                    methods.update(base.methods)  # type: ignore[attr-defined]

            # 检查当前类中是否实现了预定义的HTTP方法，如果是，则添加到'methods'集合中
            for key in http_method_funcs:
                if hasattr(cls, key):
                    methods.add(key.upper())

            # 如果收集到了任何方法，设置当前类的'methods'属性为收集到的方法集合
            if methods:
                cls.methods = methods

    def dispatch_request(self, **kwargs: t.Any) -> ft.ResponseReturnValue:
        """
        根据HTTP请求的方法分发请求到相应的处理方法。

        此方法首先根据请求方法（如GET、POST等）获取对应的处理方法。
        如果请求方法对应的处理方法不存在，并且请求方法是HEAD，则尝试获取GET方法进行处理。
        如果找到对应的处理方法，则调用该方法并传递所有关键字参数（**kwargs）。
        如果没有找到对应的处理方法，则抛出异常。

        Parameters:
        **kwargs: t.Any - 接受任意关键字参数，用于处理请求的相关数据。

        Returns:
        ft.ResponseReturnValue - 返回处理请求后的响应结果。

        Raises:
        AssertionError - 如果没有找到对应的处理方法，则抛出断言错误，提示方法未实现。
        """
        # 根据请求方法获取对应的处理方法，如果不存在则为None
        meth = getattr(self, request.method.lower(), None)

        # 如果请求方法对应的处理方法不存在，并且请求方法是HEAD，则尝试获取GET方法
        if meth is None and request.method == "HEAD":
            meth = getattr(self, "get", None)

        # 确保找到对应的处理方法，否则抛出断言错误
        assert meth is not None, f"Unimplemented method {request.method!r}"

        # 调用找到的处理方法，并传递所有关键字参数，同时确保方法同步执行
        return current_app.ensure_sync(meth)(**kwargs)  # type: ignore[no-any-return]
