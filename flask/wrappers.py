from __future__ import annotations

import typing as t

from werkzeug.exceptions import BadRequest
from werkzeug.exceptions import HTTPException
from werkzeug.wrappers import Request as RequestBase
from werkzeug.wrappers import Response as ResponseBase

from . import json
from .globals import current_app
from .helpers import _split_blueprint_path

if t.TYPE_CHECKING:  # pragma: no cover
    from werkzeug.routing import Rule


# 这段代码定义了一个 Request 类，继承自 RequestBase 类。主要功能包括：
# max_content_length：获取当前应用配置的最大内容长度。
# endpoint：获取当前请求的终点（endpoint）。
# blueprint：获取当前请求所属的蓝图名称。
# blueprints：获取当前请求所属的所有蓝图路径。
# _load_form_data：加载表单数据，并在调试模式下处理特定的表单错误。
# on_json_loading_failed：处理 JSON 加载失败的情况，如果在调试模式下则抛出详细错误。
class Request(RequestBase):
    json_module: t.Any = json

    url_rule: Rule | None = None

    view_args: dict[str, t.Any] | None = None

    routing_exception: HTTPException | None = None

    @property
    def max_content_length(self) -> int | None:  # type: ignore[override]
        """
        获取当前应用的最大内容长度限制。

        此方法作为一个属性装饰器，用于获取在当前应用配置中设置的最大内容长度（MAX_CONTENT_LENGTH）。
        如果当前应用不存在，则返回None。

        Returns:
            int | None: 最大内容长度限制的整数值，如果没有配置或应用不存在，则返回None。
        """
        if current_app:
            # 如果当前应用存在，从应用配置中获取最大内容长度限制
            return current_app.config["MAX_CONTENT_LENGTH"]  # type: ignore[no-any-return]
        else:
            # 如果当前应用不存在，返回None
            return None

    @property
    def endpoint(self) -> str | None:
        """
        获取当前对象的终点端点。

        如果url_rule属性不为空，则返回该url_rule的endpoint属性。
        否则，返回None。

        :return: 字符串类型的endpoint或者None。
        """
        if self.url_rule is not None:
            return self.url_rule.endpoint  # type: ignore[no-any-return]

        return None

    @property
    def blueprint(self) -> str | None:
        """
        获取蓝图名称。

        蓝图名称是根据endpoint属性提取的。如果endpoint属性不为空且包含'.',
        则返回endpoint中最后一个'.'之前的部分作为蓝图名称；否则，返回None。

        :return: 蓝图名称字符串或None（如果没有蓝图名称）
        """
        # 获取当前对象的endpoint属性值
        endpoint = self.endpoint

        # 检查endpoint是否非空且包含'.', 用于判断是否存在蓝图名称
        if endpoint is not None and "." in endpoint:
            # 使用rpartition方法分割endpoint，获取最后一个'.'之前的部分作为蓝图名称
            return endpoint.rpartition(".")[0]

        # 如果条件不满足，表明没有蓝图名称，返回None
        return None

    @property
    def blueprints(self) -> list[str]:
        """
        获取蓝图路径列表。

        此属性方法用于获取当前实例的蓝图路径列表。如果实例的'blueprint'属性为None，
        则返回一个空列表，否则将'blueprint'属性指定的蓝图路径分割后以列表形式返回。

        :return: 蓝图路径列表，如果无蓝图则返回空列表。
        """
        # 获取实例的蓝图名称
        name = self.blueprint

        # 如果蓝图名称为空，则返回空列表
        if name is None:
            return []

        # 分割蓝图路径并返回
        return _split_blueprint_path(name)

    def _load_form_data(self) -> None:
        """
        加载表单数据方法。

        该方法首先调用父类的_load_form_data方法以执行基本的表单数据加载逻辑。
        然后，它在特定条件下提供额外的调试帮助功能，以处理表单数据类型错误。

        条件包括：
        - 当前应用对象存在且处于调试模式。
        - 当前表单数据的MIME类型不是"multipart/form-data"。
        - 没有文件被上传。

        在这些条件下，它将附加一个特殊的错误多字典，用于在调试环境中提供更多信息。
        """
        # 调用父类的_load_form_data方法以执行基本的表单数据加载逻辑
        super()._load_form_data()

        # 检查当前应用是否处于调试模式，且表单数据的MIME类型不适用于文件上传
        if (
                current_app
                and current_app.debug
                and self.mimetype != "multipart/form-data"
                and not self.files
        ):
            # 在调试模式下导入并附加错误多字典，以帮助调试表单数据类型错误
            from .debughelpers import attach_enctype_error_multidict

            attach_enctype_error_multidict(self)

    def on_json_loading_failed(self, e: ValueError | None) -> t.Any:
        """
        当JSON加载失败时调用的方法。

        参数:
        - e: ValueError | None - 导致JSON加载失败的ValueError异常，如果没有异常则为None。

        返回:
        - t.Any - 方法可能返回任何类型的响应，具体取决于调用的上下文和配置。

        此方法首先尝试调用父类的同名方法来处理JSON加载失败的情况。
        如果父类的方法抛出了BadRequest异常，并且当前应用处于调试模式下，
        则直接抛出该异常，否则，将从当前异常中再抛出一个新的BadRequest异常。
        """
        try:
            # 尝试调用父类的方法来处理JSON加载失败
            return super().on_json_loading_failed(e)
        except BadRequest as e:
            # 当父类方法抛出BadRequest异常时，检查是否处于调试模式
            if current_app and current_app.debug:
                # 如果是调试模式，直接抛出原始异常
                raise

            # 如果不是调试模式，从当前异常中抛出新的BadRequest异常
            raise BadRequest() from e


# 这段代码定义了一个 Response 类，继承自 ResponseBase 类。Response 类中有一个 max_cookie_size 属性，用于获取当前应用的最大 cookie 大小配置。
# 功能：
# 如果当前应用（current_app）存在，则从应用配置中获取最大 cookie 大小（MAX_COOKIE_SIZE）。
# 如果当前应用不存在，则回退到基类的 max_cookie_size 属性。
# 返回值：
# 返回最大 cookie 大小，类型为 int。
class Response(ResponseBase):
    default_mimetype: str | None = "text/html"

    json_module = json

    autocorrect_location_header = False

    @property
    def max_cookie_size(self) -> int:  # type: ignore
        """
        获取当前应用的最大cookie大小配置。

        如果当前应用（current_app）存在，则尝试从应用配置中获取最大cookie大小（MAX_COOKIE_SIZE）。
        如果当前应用不存在，則回退到基類的max_cookie_size屬性。

        :return: 最大cookie大小。
        :rtype: int

        :type: ignore[no-any-return]: 忽略类型检查器对返回类型的警告，因为current_app.config的类型未知。
        """
        if current_app:
            # 当current_app存在时，从其配置中获取最大cookie大小。
            return current_app.config["MAX_COOKIE_SIZE"]  # type: ignore[no-any-return]

        # 当current_app不存在时，回退到基类的max_cookie_size属性。
        return super().max_cookie_size
