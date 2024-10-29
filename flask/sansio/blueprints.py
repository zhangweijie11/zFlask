from __future__ import annotations

import os
import typing as t
from collections import defaultdict
from functools import update_wrapper

from .. import typing as ft
from .scaffold import _endpoint_from_view_func
from .scaffold import _sentinel
from .scaffold import Scaffold
from .scaffold import setupmethod

if t.TYPE_CHECKING:  # pragma: no cover
    from .app import App

DeferredSetupFunction = t.Callable[["BlueprintSetupState"], None]
T_after_request = t.TypeVar("T_after_request", bound=ft.AfterRequestCallable[t.Any])
T_before_request = t.TypeVar("T_before_request", bound=ft.BeforeRequestCallable)
T_error_handler = t.TypeVar("T_error_handler", bound=ft.ErrorHandlerCallable)
T_teardown = t.TypeVar("T_teardown", bound=ft.TeardownCallable)
T_template_context_processor = t.TypeVar(
    "T_template_context_processor", bound=ft.TemplateContextProcessorCallable
)
T_template_filter = t.TypeVar("T_template_filter", bound=ft.TemplateFilterCallable)
T_template_global = t.TypeVar("T_template_global", bound=ft.TemplateGlobalCallable)
T_template_test = t.TypeVar("T_template_test", bound=ft.TemplateTestCallable)
T_url_defaults = t.TypeVar("T_url_defaults", bound=ft.URLDefaultCallable)
T_url_value_preprocessor = t.TypeVar(
    "T_url_value_preprocessor", bound=ft.URLValuePreprocessorCallable
)


class BlueprintSetupState:
    def __init__(
        self,
        blueprint: Blueprint,
        app: App,
        options: t.Any,
        first_registration: bool,
    ) -> None:
        """
        初始化蓝图注册器。

        :param blueprint: 要注册的蓝图对象。
        :param app: 应用程序实例。
        :param options: 传递给蓝图的配置选项。
        :param first_registration: 表示是否是第一次注册蓝图的布尔值。
        """
        # 存储应用实例
        self.app = app

        # 存储蓝图实例
        self.blueprint = blueprint

        # 存储蓝图配置选项
        self.options = options

        # 存储表示是否是第一次注册的布尔值
        self.first_registration = first_registration

        # 获取子域名配置，如果没有指定，则使用蓝图的子域名配置
        subdomain = self.options.get("subdomain")
        if subdomain is None:
            subdomain = self.blueprint.subdomain
        self.subdomain = subdomain

        # 获取URL前缀配置，如果没有指定，则使用蓝图的URL前缀配置
        url_prefix = self.options.get("url_prefix")
        if url_prefix is None:
            url_prefix = self.blueprint.url_prefix
        self.url_prefix = url_prefix

        # 获取蓝图名称配置，如果没有指定，则使用蓝图的名称
        self.name = self.options.get("name", blueprint.name)

        # 获取名称前缀配置，如果没有指定，则使用空字符串
        self.name_prefix = self.options.get("name_prefix", "")

        # 初始化URL默认值字典，用于在生成URL时提供默认的参数值
        self.url_defaults = dict(self.blueprint.url_values_defaults)
        # 更新URL默认值字典，用当前配置选项中的URL默认值覆盖蓝图的URL默认值
        self.url_defaults.update(self.options.get("url_defaults", ()))

    def add_url_rule(
        self,
        rule: str,
        endpoint: str | None = None,
        view_func: ft.RouteCallable | None = None,
        **options: t.Any,
    ) -> None:
        """
        向应用程序添加一个URL规则。

        该方法允许在当前蓝图或应用程序上绑定一个新的URL规则，指定其路由规则、视图函数、
        以及任何额外的配置选项。

        参数:
        - rule (str): URL规则的路径部分，例如 '/home'。
        - endpoint (str | None): 视图函数的端点名称。如果未提供，则从视图函数自动推导。
        - view_func (ft.RouteCallable | None): 处理该URL规则的视图函数。
        - **options (t.Any): 任意额外的配置选项，将传递给应用程序的URL规则注册方法。

        返回:
        该方法没有返回值。
        """
        # 如果当前蓝图或应用程序指定了URL前缀，则将其与规则合并
        if self.url_prefix is not None:
            if rule:
                rule = "/".join((self.url_prefix.rstrip("/"), rule.lstrip("/")))
            else:
                rule = self.url_prefix
        # 设置规则的子域选项，如果没有显式指定，则使用蓝图或应用程序的默认子域
        options.setdefault("subdomain", self.subdomain)
        # 如果未提供端点，则根据视图函数自动推导
        if endpoint is None:
            endpoint = _endpoint_from_view_func(view_func)  # type: ignore
        # 合并URL默认值配置
        defaults = self.url_defaults
        if "defaults" in options:
            defaults = dict(defaults, **options.pop("defaults"))

        # 向应用程序添加URL规则，结合当前蓝图或应用程序的名称前缀和名称，形成完整的端点名称
        self.app.add_url_rule(
            rule,
            f"{self.name_prefix}.{self.name}.{endpoint}".lstrip("."),
            view_func,
            defaults=defaults,
            **options,
        )


class Blueprint(Scaffold):

    _got_registered_once = False

    def __init__(
        self,
        name: str,
        import_name: str,
        static_folder: str | os.PathLike[str] | None = None,
        static_url_path: str | None = None,
        template_folder: str | os.PathLike[str] | None = None,
        url_prefix: str | None = None,
        subdomain: str | None = None,
        url_defaults: dict[str, t.Any] | None = None,
        root_path: str | None = None,
        cli_group: str | None = _sentinel,  # type: ignore[assignment]
    ):
        """
        初始化蓝图对象。

        参数:
        - name: 蓝图的名称，用于内部标识，不允许为空或包含'.'字符。
        - import_name: 用于导入的名称，通常为Python模块的名称。
        - static_folder: 静态文件目录，可为路径字符串或PathLike对象。
        - static_url_path: 静态文件的URL路径。
        - template_folder: 模板文件目录，可为路径字符串或PathLike对象。
        - url_prefix: 蓝图的URL前缀。
        - subdomain: 蓝图的子域名。
        - url_defaults: URL默认值的字典。
        - root_path: 蓝图的根路径。
        - cli_group: CLI命令组的名称，如果为_sentinel则表示默认值。

        异常:
        - ValueError: 如果name为空或包含'.'字符。
        """
        # 调用父类初始化方法，设置基本配置
        super().__init__(
            import_name=import_name,
            static_folder=static_folder,
            static_url_path=static_url_path,
            template_folder=template_folder,
            root_path=root_path,
        )

        # 校验name参数，确保其不为空且不包含'.'字符
        if not name:
            raise ValueError("'name' may not be empty.")

        if "." in name:
            raise ValueError("'name' may not contain a dot '.' character.")

        # 设置蓝图的名称、URL前缀、子域名和延迟初始化函数列表
        self.name = name
        self.url_prefix = url_prefix
        self.subdomain = subdomain
        self.deferred_functions: list[DeferredSetupFunction] = []

        # 初始化URL默认值字典，如果未提供则使用空字典
        if url_defaults is None:
            url_defaults = {}

        self.url_values_defaults = url_defaults
        self.cli_group = cli_group
        self._blueprints: list[tuple[Blueprint, dict[str, t.Any]]] = []

    def _check_setup_finished(self, f_name: str) -> None:
        if self._got_registered_once:
            raise AssertionError(
                f"The setup method '{f_name}' can no longer be called on the blueprint"
                f" '{self.name}'. It has already been registered at least once, any"
                " changes will not be applied consistently.\n"
                "Make sure all imports, decorators, functions, etc. needed to set up"
                " the blueprint are done before registering it."
            )

    # 使用装饰器声明此方法为设置方法，意味着该方法应在对象初始化完成后调用
    @setupmethod
    def record(self, func: DeferredSetupFunction) -> None:
        """
        记录一个延迟执行的函数，以便在适当的时候调用。

        :param func: 一个 DeferredSetupFunction 类型的函数，用于后续的设置操作。
        :return: 无返回值。

        此方法允许对象在初始化后动态地添加设置操作，这些操作将在特定时机被调用。
        """
        # 将传入的函数添加到延迟执行函数列表中
        self.deferred_functions.append(func)

    @setupmethod
    def record_once(self, func: DeferredSetupFunction) -> None:
        """
        记录一个只执行一次的函数。

        当`BlueprintSetupState`的`first_registration`属性为`True`时，该函数将被调用并执行。
        这个装饰器方法用于确保在蓝图设置过程中，某些操作只被执行一次。

        参数:
        - func (DeferredSetupFunction): 要记录并延迟执行的函数。

        返回:
        - None
        """

        def wrapper(state: BlueprintSetupState) -> None:
            """
            包装函数，用于检查是否是首次注册，并调用原始函数。

            参数:
            - state (BlueprintSetupState): 蓝图设置状态对象，包含设置过程中的状态信息。

            返回:
            - None
            """
            if state.first_registration:
                func(state)

        # 使用functools.update_wrapper来更新包装函数的元数据，使其与原始函数一致
        self.record(update_wrapper(wrapper, func))

    def make_setup_state(
        self, app: App, options: dict[str, t.Any], first_registration: bool = False
    ) -> BlueprintSetupState:
        """
        创建并返回一个BlueprintSetupState对象，用于记录蓝图的设置状态。

        参数:
        - app: App实例，表示当前蓝图所属的应用。
        - options: 字典，包含蓝图的各种配置选项。
        - first_registration: 布尔值，指示这是否是蓝图的首次注册，默认为False。

        返回:
        - BlueprintSetupState实例，封装了蓝图在特定应用环境下的设置状态。
        """
        return BlueprintSetupState(self, app, options, first_registration)

    @setupmethod
    def register_blueprint(self, blueprint: Blueprint, **options: t.Any) -> None:
        """
        注册蓝图到当前应用。

        此方法允许在应用中注册一个蓝图，蓝图是一种组织应用的方法，
        可以将相关功能的视图、模板等组织在一起，以便于管理和复用。

        参数:
        - blueprint (Blueprint): 要注册的蓝图实例。
        - **options (t.Any): 附加的配置选项，用于定制蓝图的行为。

        返回:
        无

        异常:
        - ValueError: 如果尝试将蓝图注册到自身，会抛出此异常。
        """
        # 检查蓝图是否是自身，防止递归注册
        if blueprint is self:
            raise ValueError("Cannot register a blueprint on itself")
        # 将蓝图和其配置选项作为元组添加到应用的蓝prints列表中
        self._blueprints.append((blueprint, options))

    def register(self, app: App, options: dict[str, t.Any]) -> None:
        """
        在应用程序中注册蓝图。

        :param app: 应用程序实例，表示要将蓝图注册到哪个应用。
        :param options: 包含注册选项的字典，用于自定义蓝图的注册行为。
        """
        # 从options中获取name_prefix和name，构造蓝图的完整名称
        name_prefix = options.get("name_prefix", "")
        self_name = options.get("name", self.name)
        name = f"{name_prefix}.{self_name}".lstrip(".")

        # 检查蓝图名称是否已注册，如果已注册则抛出ValueError
        if name in app.blueprints:
            bp_desc = "this" if app.blueprints[name] is self else "a different"
            existing_at = f" '{name}'" if self_name != name else ""
            raise ValueError(
                f"The name '{self_name}' is already registered for"
                f" {bp_desc} blueprint{existing_at}. Use 'name=' to"
                f" provide a unique name."
            )

        # 判断是否是首次注册该蓝图
        first_bp_registration = not any(bp is self for bp in app.blueprints.values())
        first_name_registration = name not in app.blueprints

        # 在应用的blueprints字典中注册蓝图
        app.blueprints[name] = self
        self._got_registered_once = True

        # 创建蓝图的设置状态
        state = self.make_setup_state(app, options, first_bp_registration)

        # 如果蓝图有静态文件夹，则添加静态文件的URL规则
        if self.has_static_folder:
            state.add_url_rule(
                f"{self.static_url_path}/<path:filename>",
                view_func=self.send_static_file,  # type: ignore[attr-defined]
                endpoint="static",
            )

        # 如果是首次注册该蓝图或首次使用该名称注册，則合并蓝图函数
        if first_bp_registration or first_name_registration:
            self._merge_blueprint_funcs(app, name)

        # 执行所有延迟函数
        for deferred in self.deferred_functions:
            deferred(state)

        # 解析CLI组选项并根据情况进行命令注册
        cli_resolved_group = options.get("cli_group", self.cli_group)
        if self.cli.commands:
            if cli_resolved_group is None:
                app.cli.commands.update(self.cli.commands)
            elif cli_resolved_group is _sentinel:
                self.cli.name = name
                app.cli.add_command(self.cli)
            else:
                self.cli.name = cli_resolved_group
                app.cli.add_command(self.cli)

        # 遍历所有嵌套的蓝图并注册它们
        for blueprint, bp_options in self._blueprints:
            bp_options = bp_options.copy()
            bp_url_prefix = bp_options.get("url_prefix")
            bp_subdomain = bp_options.get("subdomain")

            if bp_subdomain is None:
                bp_subdomain = blueprint.subdomain

            if state.subdomain is not None and bp_subdomain is not None:
                bp_options["subdomain"] = bp_subdomain + "." + state.subdomain
            elif bp_subdomain is not None:
                bp_options["subdomain"] = bp_subdomain
            elif state.subdomain is not None:
                bp_options["subdomain"] = state.subdomain

            if bp_url_prefix is None:
                bp_url_prefix = blueprint.url_prefix

            if state.url_prefix is not None and bp_url_prefix is not None:
                bp_options["url_prefix"] = (
                    state.url_prefix.rstrip("/") + "/" + bp_url_prefix.lstrip("/")
                )
            elif bp_url_prefix is not None:
                bp_options["url_prefix"] = bp_url_prefix
            elif state.url_prefix is not None:
                bp_options["url_prefix"] = state.url_prefix

            bp_options["name_prefix"] = name
            blueprint.register(app, bp_options)

    def _merge_blueprint_funcs(self, app: App, name: str) -> None:
        """
        将蓝图的函数合并到应用中。

        此函数负责将属于某个蓝图的所有函数（包括错误处理程序、视图函数、请求钩子等）
        合并到主应用或另一个蓝图中，以便在应用结构中统一注册和管理这些函数。

        参数:
        - app (App): 应用实例，这些实例拥有需要合并的函数。
        - name (str): 蓝图的名称，用于在合并时构建全局唯一的键名。
        """

        def extend(
            bp_dict: dict[ft.AppOrBlueprintKey, list[t.Any]],
            parent_dict: dict[ft.AppOrBlueprintKey, list[t.Any]],
        ) -> None:
            """
            扩展父字典中的函数列表。

            此内部函数用于将蓝图字典中的函数列表添加到父字典（应用或更大范围的蓝图）中，
            如果键不存在于父字典中，则会创建一个新的键，并将蓝图的键值对格式化后加入。

            参数:
            - bp_dict (dict): 蓝图字典，包含需要合并的函数列表。
            - parent_dict (dict): 父字典，这些字典属于应用或更高级别的蓝图。
            """
            for key, values in bp_dict.items():
                # 如果蓝图的键为None，则使用蓝图的名称作为键，否则构建完整的键名
                key = name if key is None else f"{name}.{key}"
                # 将蓝图中的函数列表合并到父字典中对应的键下
                parent_dict[key].extend(values)

        # 遍历蓝图中的错误处理程序，并将其合并到应用的错误处理程序中
        for key, value in self.error_handler_spec.items():
            # 如果蓝图的键为None，则使用蓝图的名称作为键，否则构建完整的键名
            key = name if key is None else f"{name}.{key}"
            # 构建并更新应用的错误处理程序字典
            value = defaultdict(
                dict,
                {
                    code: {exc_class: func for exc_class, func in code_values.items()}
                    for code, code_values in value.items()
                },
            )
            app.error_handler_spec[key] = value

        # 将蓝图中的视图函数合并到应用的视图函数中
        for endpoint, func in self.view_functions.items():
            app.view_functions[endpoint] = func

        # 使用extend函数将蓝图中的请求前置处理函数合并到应用中
        extend(self.before_request_funcs, app.before_request_funcs)
        # 使用extend函数将蓝图中的请求后置处理函数合并到应用中
        extend(self.after_request_funcs, app.after_request_funcs)
        # 使用extend函数将蓝图中的请求销毁处理函数合并到应用中
        extend(
            self.teardown_request_funcs,
            app.teardown_request_funcs,
        )
        # 使用extend函数将蓝图中的URL默认函数合并到应用中
        extend(self.url_default_functions, app.url_default_functions)
        # 使用extend函数将蓝图中的URL值预处理器合并到应用中
        extend(self.url_value_preprocessors, app.url_value_preprocessors)
        # 使用extend函数将蓝图中的模板上下文处理器合并到应用中
        extend(self.template_context_processors, app.template_context_processors)

    @setupmethod
    def add_url_rule(
        self,
        rule: str,
        endpoint: str | None = None,
        view_func: ft.RouteCallable | None = None,
        provide_automatic_options: bool | None = None,
        **options: t.Any,
    ) -> None:
        """
        在应用程序中添加一个URL规则。

        此方法允许将一个URL规则绑定到一个特定的视图函数或端点上，以处理特定的HTTP请求。
        它还可以记录是否应自动提供选项响应。

        参数:
        - rule (str): URL规则的字符串表达形式，例如 '/index'。
        - endpoint (str | None): 端点的名称，如果未提供，则使用视图函数的名称。
        - view_func (ft.RouteCallable | None): 处理该URL规则的视图函数。
        - provide_automatic_options (bool | None): 是否自动提供HTTP选项响应，如果为None，则根据应用程序配置决定。
        - **options (t.Any): 其他额外的选项将作为关键字参数传递给视图函数。

        返回:
        - None

        异常:
        - ValueError: 如果端点或视图函数名称包含点('.')字符，则引发此异常。
        """
        # 检查端点名称中是否包含不允许的点字符
        if endpoint and "." in endpoint:
            raise ValueError("'endpoint' may not contain a dot '.' character.")

        # 检查视图函数名称中是否包含不允许的点字符
        if view_func and hasattr(view_func, "__name__") and "." in view_func.__name__:
            raise ValueError("'view_func' name may not contain a dot '.' character.")

        # 记录一个操作，该操作将在适当的时候添加URL规则到应用程序
        self.record(
            lambda s: s.add_url_rule(
                rule,
                endpoint,
                view_func,
                provide_automatic_options=provide_automatic_options,
                **options,
            )
        )

    @setupmethod
    def app_template_filter(
        self, name: str | None = None
    ) -> t.Callable[[T_template_filter], T_template_filter]:
        """
        用于注册应用程序模板过滤器的装饰器。

        此函数创建并返回一个装饰器，用于将模板过滤器函数添加到应用程序中。
        装饰器模式允许在不修改函数代码的情况下，增加函数的功能。

        参数:
        - name (str | None): 模板过滤器的名称。如果未提供，则使用函数的名称。

        返回:
        - Callable[[T_template_filter], T_template_filter]: 一个装饰器，用于将函数作为模板过滤器注册到应用程序中。
        """
        def decorator(f: T_template_filter) -> T_template_filter:
            """
            装饰器函数，用于将传入的函数添加为应用模板过滤器。

            参数:
            - f (T_template_filter): 要添加为模板过滤器的函数。

            返回:
            - T_template_filter: 返回原始函数，不修改原始函数的行为。
            """
            self.add_app_template_filter(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_app_template_filter(
        self, f: ft.TemplateFilterCallable, name: str | None = None
    ) -> None:
        """
        添加一个应用模板过滤器。

        该方法允许在应用程序的Jinja2环境中的filters字典中注册一个新的过滤器函数，
        以便在渲染模板时使用。如果提供了过滤器名称，则使用该名称；否则，使用函数的名称。

        参数:
        - f: 一个可调用的模板过滤器，其签名符合TemplateFilterCallable类型。
        - name: 可选参数，指定过滤器在模板中的名称。如果未提供，则使用函数的名称。

        返回:
        该方法没有返回值。
        """
        def register_template(state: BlueprintSetupState) -> None:
            """
            注册模板过滤器。

            该函数负责将过滤器函数添加到应用的Jinja2环境的filters字典中。
            它使用提供的名称或函数的名称作为键，过滤器函数作为值。

            参数:
            - state: BlueprintSetupState对象，表示蓝图的设置状态。

            返回:
            该函数没有返回值。
            """
            state.app.jinja_env.filters[name or f.__name__] = f

        # 记录注册模板过滤器的操作，确保它只被执行一次。
        self.record_once(register_template)

    @setupmethod
    def app_template_test(
        self, name: str | None = None
    ) -> t.Callable[[T_template_test], T_template_test]:
        """
        装饰器工厂函数，用于注册应用模板测试函数。

        此函数的主要作用是创建一个装饰器，该装饰器将应用模板测试函数注册到系统中，
        以便在测试时使用。它接受一个可选的名称参数，用于指定测试的名称。

        参数:
        - name (str | None): 测试的名称，如果未提供，则默认为None。这个名称用于标识测试。

        返回:
        - t.Callable[[T_template_test], T_template_test]: 返回一个装饰器，该装饰器用于包装测试函数，
          并将其注册到系统中。
        """
        def decorator(f: T_template_test) -> T_template_test:
            """
            装饰器函数，用于包装并注册应用模板测试函数。

            参数:
            - f (T_template_test): 被装饰的测试函数。

            返回:
            - T_template_test: 返回包装后的测试函数。
            """
            self.add_app_template_test(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_app_template_test(
        self, f: ft.TemplateTestCallable, name: str | None = None
    ) -> None:
        """
        在应用程序的Jinja2环境中注册一个模板测试函数。

        此函数装饰器用于在应用程序中添加自定义的模板测试函数，这些测试函数可以用于模板渲染过程中对数据进行校验。

        参数:
        - f: 一个可调用对象，用于定义模板测试逻辑。
        - name: 可选参数，指定测试函数的名称。如果未提供，则使用函数本身的名称。

        返回:
        无返回值。
        """
        def register_template(state: BlueprintSetupState) -> None:
            """
            在蓝图设置状态下注册模板测试函数。

            此内部函数负责将提供的测试函数添加到应用程序的Jinja2环境中的测试字典中。

            参数:
            - state: 蓝图设置状态对象，包含应用程序和蓝图的相关信息。

            返回:
            无返回值。
            """
            state.app.jinja_env.tests[name or f.__name__] = f

        self.record_once(register_template)

    @setupmethod
    def app_template_global(
        self, name: str | None = None
    ) -> t.Callable[[T_template_global], T_template_global]:
        """
        一个装饰器工厂函数，用于注册应用程序模板全局变量。

        此函数允许用户将自定义函数或变量注册到应用程序的模板全局变量中，
        以便在模板渲染时使用。通过此方式，可以在模板中直接访问注册的函数或变量。

        参数:
        - name (str | None): 注册到模板全局变量中的名称。如果未提供，则使用函数的原始名称。

        返回:
        - Callable[[T_template_global], T_template_global]: 返回一个装饰器，用于包裹需要注册的函数或变量。
        """
        def decorator(f: T_template_global) -> T_template_global:
            """
            实际的装饰器函数，负责将传入的函数或变量注册到应用程序模板全局变量中。

            参数:
            - f (T_template_global): 需要注册的函数或变量。

            返回:
            - T_template_global: 返回注册的函数或变量本身，不修改其行为。
            """
            self.add_app_template_global(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_app_template_global(
        self, f: ft.TemplateGlobalCallable, name: str | None = None
    ) -> None:
        """
        在应用中添加一个全局模板变量或函数。

        此装饰器方法允许在蓝图中注册一个全局可用的模板变量或函数，
        它将在蓝图注册时添加到应用的 Jinja 环境中。

        参数:
        - f: 一个可调用对象，用作模板全局变量或函数。
        - name: 可选参数，指定在模板中使用的变量或函数的名字。
                如果未提供，则使用被装饰函数的名称。

        返回:
        无返回值。
        """

        # 定义一个内部函数 register_template，它将被记录到蓝图的设置状态中
        def register_template(state: BlueprintSetupState) -> None:
            # 在 Jinja 环境的 globals 字典中注册函数 f，
            # 使用参数 name 或 f 的名称作为键
            state.app.jinja_env.globals[name or f.__name__] = f

        # 使用 record_once 方法确保 register_template 函数只被调用一次
        self.record_once(register_template)

    @setupmethod
    def before_app_request(self, f: T_before_request) -> T_before_request:
        """
        在应用程序处理请求前执行指定的函数f。

        该装饰器用于在应用处理请求前，执行一些预处理操作。通过该装饰器修饰的函数f，
        将会在每次请求前被调用，除非该函数在请求处理过程中被移除。

        参数:
        - f: T_before_request -> 被装饰的函数，该函数无参数，返回值为None。

        返回:
        - T_before_request -> 返回被装饰的函数f，保持其原始类型。
        """
        # 记录一个操作，该操作会在应用初始化时执行一次
        # 这里记录的操作是将函数f添加到应用的before_request_funcs中
        # 如果None键不存在，则创建一个列表并将f添加到列表中
        self.record_once(
            lambda s: s.app.before_request_funcs.setdefault(None, []).append(f)
        )
        # 返回被装饰的函数，保持其原始行为
        return f

    @setupmethod
    def after_app_request(self, f: T_after_request) -> T_after_request:
        """
        注册一个在处理请求后调用的函数。

        此装饰器用于在应用程序处理请求后执行特定操作。传递给此方法的函数`f`将在每次请求处理后被调用。
        它可以用于执行一些请求后的清理或日志记录操作。

        参数:
        - f (T_after_request): 一个函数类型，表示请求处理后要执行的操作。

        返回:
        - T_after_request: 返回传入的函数`f`，主要用于装饰器的语法。

        此方法通过`self.record_once`记录操作，确保在应用程序初始化时，将`f`添加到`after_request_funcs`字典中，
        该字典的键为`None`，值为一个包含请求后调用函数的列表。这样做的目的是确保在应用程序的生命周期内，
        每个请求处理后都能执行注册的函数`f`。
        """
        self.record_once(
            lambda s: s.app.after_request_funcs.setdefault(None, []).append(f)
        )
        return f

    # 注解：此函数用于在应用程序请求结束时执行指定的函数
    @setupmethod
    def teardown_app_request(self, f: T_teardown) -> T_teardown:
        """
        在应用程序请求结束时执行给定的函数f。

        参数:
        - f: T_teardown类型，请求结束后要执行的函数。

        返回:
        - 返回传入的函数f，用于装饰器语法。
        """
        # 在应用程序的请求结束时执行的函数列表中添加f
        self.record_once(
            lambda s: s.app.teardown_request_funcs.setdefault(None, []).append(f)
        )
        return f

    # 注解：此函数用于注册一个应用上下文处理器
    @setupmethod
    def app_context_processor(
        self, f: T_template_context_processor
    ) -> T_template_context_processor:
        """
        注册一个应用上下文处理器，用于在渲染模板之前修改模板上下文。

        参数:
        - f: T_template_context_processor类型，要注册的上下文处理器函数。

        返回:
        - 返回传入的函数f，用于装饰器语法。
        """
        # 将上下文处理器函数f添加到应用的模板上下文处理器列表中
        self.record_once(
            lambda s: s.app.template_context_processors.setdefault(None, []).append(f)
        )
        return f

    # 注解：此函数用于注册一个错误处理器
    @setupmethod
    def app_errorhandler(
        self, code: type[Exception] | int
    ) -> t.Callable[[T_error_handler], T_error_handler]:
        """
        注册一个错误处理器，用于处理特定错误代码或异常类型。

        参数:
        - code: type[Exception] | int类型，错误代码或异常类型。

        返回:
        - 返回一个装饰器，用于装饰错误处理器函数。
        """
        # 定义一个装饰器，用于装饰错误处理器函数
        def decorator(f: T_error_handler) -> T_error_handler:
            # 定义一个函数，用于在蓝图设置时注册错误处理器
            def from_blueprint(state: BlueprintSetupState) -> None:
                state.app.errorhandler(code)(f)

            # 在蓝图设置时执行from_blueprint函数
            self.record_once(from_blueprint)
            return f

        return decorator
    @setupmethod
    def app_url_value_preprocessor(
        self, f: T_url_value_preprocessor
    ) -> T_url_value_preprocessor:
        """
        注册一个URL值预处理器函数。

        该方法允许在应用程序的URL解析时，预处理传入的URL参数。
        这对于在路由匹配之前对URL参数进行验证、转换或其它预处理非常有用。

        参数:
        - f: 一个可调用的预处理器函数，该函数将在URL值解析时被调用。

        返回:
        - 返回注册的预处理器函数本身，这使得该方法可以作为装饰器使用。
        """
        # 使用record_once确保预处理器函数只被注册一次
        self.record_once(
            lambda s: s.app.url_value_preprocessors.setdefault(None, []).append(f)
        )
        return f

    @setupmethod
    def app_url_defaults(self, f: T_url_defaults) -> T_url_defaults:
        """
        注册一个URL默认值函数。

        该方法允许在生成URL时，为未指定的参数提供默认值。
        这对于在生成URL时确保参数的一致性和完整性非常有用。

        参数:
        - f: 一个可调用的默认值函数，该函数将在生成URL时被调用以提供缺失的参数默认值。

        返回:
        - 返回注册的默认值函数本身，这使得该方法可以作为装饰器使用。
        """
        # 使用record_once确保默认值函数只被注册一次
        self.record_once(
            lambda s: s.app.url_default_functions.setdefault(None, []).append(f)
        )
        return f