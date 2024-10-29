from __future__ import annotations

import typing as t

from jinja2 import BaseLoader
from jinja2 import Environment as BaseEnvironment
from jinja2 import Template
from jinja2 import TemplateNotFound

from .globals import _cv_app
from .globals import _cv_request
from .globals import current_app
from .globals import request
from .helpers import stream_with_context
from .signals import before_render_template
from .signals import template_rendered

if t.TYPE_CHECKING:  # pragma: no cover
    from .app import Flask
    from .sansio.app import App
    from .sansio.scaffold import Scaffold


def _default_template_ctx_processor() -> dict[str, t.Any]:
    """
    默认的模板上下文处理器函数。

    本函数用于收集并返回在模板渲染时需要的上下文变量。它主要关注于应用上下文和请求上下文的处理。

    Returns:
        dict[str, t.Any]: 包含上下文变量的字典，键为变量名，值为对应的上下文对象。
    """
    # 获取当前应用上下文
    appctx = _cv_app.get(None)
    # 获取当前请求上下文
    reqctx = _cv_request.get(None)

    # 初始化要返回的上下文变量字典
    rv: dict[str, t.Any] = {}

    # 如果应用上下文存在，则将全局变量'g'添加到返回的上下文字典中
    if appctx is not None:
        rv["g"] = appctx.g

    # 如果请求上下文存在，则将请求和会话信息添加到返回的上下文字典中
    if reqctx is not None:
        rv["request"] = reqctx.request
        rv["session"] = reqctx.session

    # 返回收集到的上下文变量字典
    return rv



class Environment(BaseEnvironment):
    """
    继承自BaseEnvironment的环境类，用于设置和管理应用程序的环境配置。

    Attributes:
        app (App): 与当前环境关联的应用程序实例。
    """

    def __init__(self, app: App, **options: t.Any) -> None:
        """
        初始化环境类实例。

        Parameters:
            app (App): 应用程序实例，用于环境配置。
            **options (t.Any): 可变关键字参数，用于配置环境选项。

        Returns:
            None
        """
        # 检查options字典中是否包含'loader'键，如果没有，则使用app实例创建的全局Jinja加载器
        if "loader" not in options:
            options["loader"] = app.create_global_jinja_loader()

        # 调用BaseEnvironment的构造方法，初始化当前环境类实例
        BaseEnvironment.__init__(self, **options)

        # 保存app实例作为环境的一部分
        self.app = app


# DispatchingJinjaLoader 类
# 初始化方法 __init__:
# 接受一个 App 对象作为参数，并将其存储在实例变量 self.app 中。
# get_source 方法:
# 根据配置项 EXPLAIN_TEMPLATE_LOADING 的值决定调用 _get_source_explained 或 _get_source_fast 方法来获取模板源代码。
# 返回一个包含模板源代码、加载路径和是否过期检查函数的元组。
# _get_source_explained 方法:
# 通过 _iter_loaders 方法遍历所有可能的加载器，尝试加载模板。
# 记录每次加载尝试的结果，并调用 explain_template_loading_attempts 函数记录详细的加载尝试信息。
# 如果找到模板，返回模板源代码；否则抛出 TemplateNotFound 异常。
# _get_source_fast 方法:
# 通过 _iter_loaders 方法遍历所有可能的加载器，尝试加载模板。
# 如果找到模板，立即返回模板源代码；否则抛出 TemplateNotFound 异常。
# _iter_loaders 方法:
# 生成一个迭代器，返回应用和蓝图的加载器。
# 先返回应用的加载器，然后返回每个蓝图的加载器。
# list_templates 方法:
# 列出所有可用的模板。
# 首先获取应用的模板，然后获取每个蓝图的模板，合并后返回。
class DispatchingJinjaLoader(BaseLoader):

    def __init__(self, app: App) -> None:
        self.app = app

    def get_source(
        self, environment: BaseEnvironment, template: str
    ) -> tuple[str, str | None, t.Callable[[], bool] | None]:
        """
        根据环境和模板字符串获取模板的源代码及其相关信息。

        此函数根据当前应用配置，选择性地以详细解释模式或快速模式获取模板源信息。

        参数:
        - environment: BaseEnvironment, 定义了模板加载的环境。
        - template: str, 模板的字符串表示。

        返回:
        - tuple[str, str | None, t.Callable[[], bool] | None]: 包含模板源代码、模板路径（可选）和一个可调用的函数（可选）。
        """
        # 根据应用配置决定使用哪种方式获取模板源信息
        if self.app.config["EXPLAIN_TEMPLATE_LOADING"]:
            # 如果配置启用了详细解释模式，则调用_explain_source_explained方法
            return self._get_source_explained(environment, template)
        # 如果配置未启用详细解释模式，则调用_get_source_fast方法以快速获取模板源信息
        return self._get_source_fast(environment, template)

    def _get_source_explained(
        self, environment: BaseEnvironment, template: str
    ) -> tuple[str, str | None, t.Callable[[], bool] | None]:
        """
        获取模板源代码并解释加载过程。

        在这个方法中，它会尝试使用不同的加载器来加载指定的模板，并记录每个加载器的加载尝试结果。
        如果模板成功加载，则返回模板的源代码、文件名和一个用于重新加载模板的函数。
        如果所有加载尝试均失败，则抛出TemplateNotFound异常。

        :param environment: BaseEnvironment 实例，表示当前的环境。
        :param template: str，模板的名称。
        :return: 一个元组，包含模板源代码（str）、文件名（可选，str）和一个用于重新加载模板的函数（可选，Callable）。
        :raises TemplateNotFound: 如果所有加载器都无法找到指定的模板，则抛出此异常。
        """
        # 初始化加载尝试记录列表
        attempts = []
        # 初始化返回值变量
        rv: tuple[str, str | None, t.Callable[[], bool] | None] | None
        trv: None | (tuple[str, str | None, t.Callable[[], bool] | None]) = None

        # 遍历模板加载器
        for srcobj, loader in self._iter_loaders(template):
            try:
                # 尝试使用当前加载器加载模板源代码
                rv = loader.get_source(environment, template)
                # 如果尚未记录成功加载，则记录本次加载结果
                if trv is None:
                    trv = rv
            except TemplateNotFound:
                # 如果加载失败，记录为None
                rv = None
            # 记录本次加载尝试的信息
            attempts.append((loader, srcobj, rv))

        # 导入调试辅助模块以解释模板加载尝试
        from .debughelpers import explain_template_loading_attempts

        # 使用调试辅助函数解释模板加载尝试
        explain_template_loading_attempts(self.app, template, attempts)

        # 如果有成功加载的模板，则返回加载结果
        if trv is not None:
            return trv
        # 如果所有尝试均失败，则抛出异常
        raise TemplateNotFound(template)

    def _get_source_fast(
        self, environment: BaseEnvironment, template: str
    ) -> tuple[str, str | None, t.Callable[[], bool] | None]:
        """
        快速获取模板源代码。

        该方法通过迭代内部加载器来尝试获取指定模板的源代码。它会依次尝试每个加载器，直到成功获取源代码或所有加载器均失败。

        参数:
        - environment: BaseEnvironment 实例，表示当前模板的环境。
        - template: 字符串，表示要加载的模板名称。

        返回:
        - 一个元组，包含模板源代码、模板的路径（如果可用）以及一个可调用对象（如果可用），该对象可用于检查模板是否已过期。

        异常:
        - 如果所有加载器都无法找到指定的模板，则抛出 TemplateNotFound 异常。
        """
        # 遍历所有加载器，尝试获取模板源代码
        for _srcobj, loader in self._iter_loaders(template):
            try:
                # 尝试使用当前加载器获取模板源代码
                return loader.get_source(environment, template)
            except TemplateNotFound:
                # 如果当前加载器无法找到模板，继续尝试下一个加载器
                continue
        # 如果所有加载器都无法找到模板，抛出异常
        raise TemplateNotFound(template)

    def _iter_loaders(self, template: str) -> t.Iterator[tuple[Scaffold, BaseLoader]]:
        """
        遍历并生成所有Scaffold及其对应的模板加载器。

        该函数首先尝试获取应用本身的模板加载器，如果存在，则生成应用及其加载器。
        接着，函数遍历应用中的所有蓝图，对于每个蓝图，尝试获取其模板加载器，
        如果加载器存在，则生成该蓝图及其加载器。

        :param template: str 类型，模板的名称（该参数在此函数中未使用，但可能在其他上下文中用到）
        :return: t.Iterator[tuple[Scaffold, BaseLoader]] 类型，返回一个生成器，生成Scaffold对象和其对应的BaseLoader对象的元组
        """
        # 尝试获取应用的模板加载器
        loader = self.app.jinja_loader
        # 如果加载器存在，生成应用及其加载器
        if loader is not None:
            yield self.app, loader

        # 遍历应用中的所有蓝图
        for blueprint in self.app.iter_blueprints():
            # 尝试获取蓝图的模板加载器
            loader = blueprint.jinja_loader
            # 如果加载器存在，生成蓝图及其加载器
            if loader is not None:
                yield blueprint, loader

    def list_templates(self) -> list[str]:
        """
        获取所有模板文件的列表。

        此方法首先从应用的Jinja加载器中获取模板文件列表，然后遍历应用中的所有蓝图，
        从每个蓝图的Jinja加载器中收集模板文件列表。最后，将所有收集到的模板文件名
        转换为列表形式返回。

        :return: 包含所有模板文件名的列表。
        """
        # 初始化一个集合，用于存储模板文件名，以避免重复
        result = set()

        # 获取应用的Jinja加载器
        loader = self.app.jinja_loader
        # 如果加载器存在，则将所有模板文件名添加到结果集合中
        if loader is not None:
            result.update(loader.list_templates())

        # 遍历应用中的所有蓝图
        for blueprint in self.app.iter_blueprints():
            # 获取当前蓝图的Jinja加载器
            loader = blueprint.jinja_loader
            # 如果加载器存在，则将所有模板文件名添加到结果集合中
            if loader is not None:
                for template in loader.list_templates():
                    result.add(template)

        # 将结果集合转换为列表形式并返回
        return list(result)


def _render(app: Flask, template: Template, context: dict[str, t.Any]) -> str:
    """
    渲染模板函数。

    该函数使用给定的Flask应用、模板和上下文字典来渲染模板。它在渲染前后发送信号，
    允许订阅这些信号的组件执行自定义逻辑。

    参数:
    - app: Flask应用实例，用于访问Flask相关的上下文和配置。
    - template: 要渲染的模板实例。
    - context: 包含模板渲染所需数据的字典，键为字符串类型，值为任意类型。

    返回:
    - rv: 渲染后的模板字符串。
    """
    # 更新模板上下文，以便包含Flask应用的全局变量
    app.update_template_context(context)

    # 在模板渲染之前发送信号，参数_async_wrapper用于处理异步逻辑
    before_render_template.send(
        app, _async_wrapper=app.ensure_sync, template=template, context=context
    )

    # 渲染模板并存储结果
    rv = template.render(context)

    # 在模板渲染之后发送信号，参数_async_wrapper用于处理异步逻辑
    template_rendered.send(
        app, _async_wrapper=app.ensure_sync, template=template, context=context
    )

    # 返回渲染后的模板字符串
    return rv



def render_template(
    template_name_or_list: str | Template | list[str | Template],
    **context: t.Any,
) -> str:
    """
    渲染模板函数。

    该函数接受模板名称或模板对象（或其列表），并使用Jinja2环境渲染模板。
    它主要用于将模板和上下文数据结合在一起，生成最终的HTML字符串。

    参数:
    - template_name_or_list: 模板的名称、模板对象，或它们的列表。这允许灵活地指定要渲染的模板。
    - **context: 以关键字参数形式传入的渲染上下文。这些数据将在模板中使用。

    返回:
    - str: 渲染后的模板字符串。
    """
    # 获取当前应用对象
    app = current_app._get_current_object()  # type: ignore[attr-defined]
    # 根据模板名称或列表选择或获取模板对象
    template = app.jinja_env.get_or_select_template(template_name_or_list)
    # 调用内部渲染函数，传入应用对象、模板对象和上下文数据
    return _render(app, template, context)



def render_template_string(source: str, **context: t.Any) -> str:
    """
    使用Jinja2模板引擎渲染给定的模板字符串。

    :param source: 待渲染的模板字符串。
    :param context: 传递给模板的上下文变量，以关键字参数的形式。
    :return: 渲染后的字符串结果。
    """
    # 获取当前应用对象，忽略类型检查以避免直接引用内部属性
    app = current_app._get_current_object()  # type: ignore[attr-defined]

    # 从应用的Jinja2环境中，根据给定的模板字符串创建模板对象
    template = app.jinja_env.from_string(source)

    # 调用内部渲染函数，传入应用对象、模板对象和上下文变量，返回渲染后的结果
    return _render(app, template, context)



def _stream(
    app: Flask, template: Template, context: dict[str, t.Any]
) -> t.Iterator[str]:
    """
    为模板渲染提供一个流式输出的函数。

    该函数首先更新模板的上下文，然后发送一个模板渲染开始前的信号。
    通过内部的生成器函数generate，逐行或逐块地生成模板渲染结果，并在生成结束后发送渲染完成的信号。

    Args:
        app (Flask): Flask应用实例。
        template (Template): 要渲染的模板实例。
        context (dict[str, t.Any]): 模板的上下文，包含渲染所需的数据。

    Returns:
        t.Iterator[str]: 渲染结果的迭代器，逐行或逐块地提供渲染后的字符串。
    """
    # 更新模板上下文，以便包含Flask应用的全局变量
    app.update_template_context(context)
    before_render_template.send(
        app, _async_wrapper=app.ensure_sync, template=template, context=context
    )

    def generate() -> t.Iterator[str]:
        """
        生成模板渲染结果的迭代器。

        该函数通过委托生成器的方式，从模板的生成方法中获取渲染结果，
        并在所有内容生成完毕后，发送一个模板渲染完成的信号。

        Yields:
            t.Iterator[str]: 渲染结果的迭代器，逐行或逐块地提供渲染后的字符串。

        Signals:
            template_rendered: 当模板渲染完成时发送的信号，包含应用实例、异步包装器、模板和上下文。
        """
        # 通过委托生成器，直接使用模板的生成方法来生成内容
        yield from template.generate(context)

        # 发送模板渲染完成的信号，通知订阅者模板已经渲染完毕
        template_rendered.send(
            app, _async_wrapper=app.ensure_sync, template=template, context=context
        )

    rv = generate()

    # 如果存在请求上下文，使用stream_with_context来保持上下文
    if request:
        rv = stream_with_context(rv)

    return rv



def stream_template(
    template_name_or_list: str | Template | list[str | Template],
    **context: t.Any,
) -> t.Iterator[str]:
    """
    通过生成器方式流式渲染模板。

    该函数允许通过提供模板名称或模板列表，以及渲染上下文来流式渲染模板。
    它首先获取当前应用对象，然后根据提供的模板名称或列表选择模板，
    最后通过流式渲染函数 `_stream` 渲染模板。

    参数:
    - template_name_or_list: 单个模板的名称、模板对象或模板名称和对象的列表。
    - **context: 渲染模板所需的上下文变量，作为关键字参数提供。

    返回:
    - t.Iterator[str]: 返回一个字符串生成器，用于流式渲染模板。
    """
    # 获取当前应用对象
    app = current_app._get_current_object()  # type: ignore[attr-defined]
    # 根据提供的模板名称或列表选择模板
    template = app.jinja_env.get_or_select_template(template_name_or_list)
    # 调用流式渲染函数，开始渲染模板
    return _stream(app, template, context)



def stream_template_string(source: str, **context: t.Any) -> t.Iterator[str]:
    """
    使用Jinja2模板引擎从字符串源中生成模板，并根据上下文流式传输渲染后的字符串。

    此函数通过从当前应用的Jinja2环境中加载一个模板字符串，创建一个模板对象，
    然后使用提供的上下文变量对模板进行渲染，并以迭代器的形式逐行输出渲染后的模板。

    :param source: 一个字符串，包含模板的源代码。
    :param context: 一个或多个键值对，代表模板中的变量及其值。这些变量将被用于渲染模板。
    :return: 返回一个字符串迭代器，逐行输出渲染后的模板。
    """
    # 获取当前应用实例，用于访问Jinja2模板环境。
    app = current_app._get_current_object()  # type: ignore[attr-defined]
    # 从字符串源代码中创建一个模板对象。
    template = app.jinja_env.from_string(source)
    # 使用应用实例、模板对象和上下文变量调用_stream函数，以流式传输渲染后的模板。
    return _stream(app, template, context)

