from __future__ import annotations

import hashlib
import typing as t
from collections.abc import MutableMapping
from datetime import datetime
from datetime import timezone

from itsdangerous import BadSignature
from itsdangerous import URLSafeTimedSerializer
from werkzeug.datastructures import CallbackDict

from .json.tag import TaggedJSONSerializer

if t.TYPE_CHECKING:  # pragma: no cover
    import typing_extensions as te

    from .app import Flask
    from .wrappers import Request
    from .wrappers import Response


# TODO generic when Python > 3.8
# 这段代码定义了一个名为 SessionMixin 的类，继承自 MutableMapping。该类主要用于管理会话数据，并提供了以下功能：
# 属性 permanent：
# getter：返回会话是否为永久会话，默认值为 False。
# setter：设置会话是否为永久会话，值必须为布尔类型。
# 类变量：
# new：表示会话是否为新创建的，默认值为 False。
# modified：表示会话是否被修改，默认值为 True。
# accessed：表示会话是否被访问，默认值为 True。
class SessionMixin(MutableMapping):  # type: ignore[type-arg]

    @property
    def permanent(self) -> bool:
        return self.get("_permanent", False)

    @permanent.setter
    def permanent(self, value: bool) -> None:
        self["_permanent"] = bool(value)

    new = False

    modified = True

    accessed = True


# TODO generic when Python > 3.8
# 这段代码定义了一个名为 SecureCookieSession 的类，继承自 CallbackDict 和 SessionMixin。该类用于管理安全的会话数据，并跟踪会话是否被修改或访问。
# 初始化 (__init__ 方法)：
# 接受一个可选的初始值 initial。
# 定义一个回调函数 on_update，当会话数据被更新时，设置 modified 和 accessed 属性为 True。
# 调用父类的初始化方法，传入初始值和回调函数。
# 获取项 (__getitem__ 方法)：
# 设置 accessed 属性为 True。
# 调用父类的 __getitem__ 方法获取指定键的值。
# 获取项 (get 方法)：
# 设置 accessed 属性为 True。
# 调用父类的 get 方法获取指定键的值，如果键不存在则返回默认值。
# 设置默认值 (setdefault 方法)：
# 设置 accessed 属性为 True。
# 调用父类的 setdefault 方法设置指定键的默认值，如果键不存在则插入默认值并返回。
class SecureCookieSession(CallbackDict, SessionMixin):  # type: ignore[type-arg]
    modified = False

    accessed = False

    def __init__(self, initial: t.Any = None) -> None:
        def on_update(self: te.Self) -> None:
            self.modified = True
            self.accessed = True

        super().__init__(initial, on_update)

    def __getitem__(self, key: str) -> t.Any:
        self.accessed = True
        return super().__getitem__(key)

    def get(self, key: str, default: t.Any = None) -> t.Any:
        self.accessed = True
        return super().get(key, default)

    def setdefault(self, key: str, default: t.Any = None) -> t.Any:
        self.accessed = True
        return super().setdefault(key, default)

# 这段代码定义了一个名为 NullSession 的类，继承自 SecureCookieSession。主要功能如下：
# 定义了一个 _fail 方法，当会话不可用时抛出 RuntimeError，提示用户设置应用的 secret_key。
# 将多个会话操作方法（如 __setitem__, __delitem__, clear 等）重定向到 _fail 方法，确保这些方法在没有设置 secret_key 时都会抛出异常。
# 删除 _fail 方法，防止外部直接调用。
class NullSession(SecureCookieSession):

    def _fail(self, *args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        raise RuntimeError(
            "The session is unavailable because no secret "
            "key was set.  Set the secret_key on the "
            "application to something unique and secret."
        )

    __setitem__ = __delitem__ = clear = pop = popitem = update = setdefault = _fail  # type: ignore # noqa: B950
    del _fail


class SessionInterface:
    """
    定义一个会话接口类，用于管理Flask应用中的会话。
    """

    # 设置空会话的类，当会话为空时使用
    null_session_class = NullSession

    # 标记是否基于pickle的会话
    pickle_based = False

    def make_null_session(self, app: Flask) -> NullSession:
        """
        创建一个空会话对象。

        参数:
        app (Flask): 当前的Flask应用实例。

        返回:
        NullSession: 空会话对象。
        """
        return self.null_session_class()

    def is_null_session(self, obj: object) -> bool:
        """
        检查对象是否是空会话。

        参数:
        obj (object): 要检查的对象。

        返回:
        bool: 如果对象是空会话，则返回True，否则返回False。
        """
        return isinstance(obj, self.null_session_class)

    def get_cookie_name(self, app: Flask) -> str:
        """
        获取会话cookie的名称。

        参数:
        app (Flask): 当前的Flask应用实例。

        返回:
        str: 会话cookie的名称。
        """
        return app.config["SESSION_COOKIE_NAME"]  # type: ignore[no-any-return]

    def get_cookie_domain(self, app: Flask) -> str | None:
        """
        获取会话cookie的域名。

        参数:
        app (Flask): 当前的Flask应用实例。

        返回:
        str | None: 会话cookie的域名，如果没有设置，则返回None。
        """
        return app.config["SESSION_COOKIE_DOMAIN"]  # type: ignore[no-any-return]

    def get_cookie_path(self, app: Flask) -> str:
        """
        获取会话cookie的路径。

        参数:
        app (Flask): 当前的Flask应用实例。

        返回:
        str: 会话cookie的路径，如果没有设置，则返回应用的根路径。
        """
        return app.config["SESSION_COOKIE_PATH"] or app.config["APPLICATION_ROOT"]  # type: ignore[no-any-return]

    def get_cookie_httponly(self, app: Flask) -> bool:
        """
        检查会话cookie是否设置为仅通过HTTP协议传输。

        参数:
        app (Flask): 当前的Flask应用实例。

        返回:
        bool: 如果会话cookie设置为仅通过HTTP协议传输，则返回True，否则返回False。
        """
        return app.config["SESSION_COOKIE_HTTPONLY"]  # type: ignore[no-any-return]

    def get_cookie_secure(self, app: Flask) -> bool:
        """
        检查会话cookie是否设置为仅在安全的连接上传输。

        参数:
        app (Flask): 当前的Flask应用实例。

        返回:
        bool: 如果会话cookie设置为仅在安全的连接上传输，则返回True，否则返回False。
        """
        return app.config["SESSION_COOKIE_SECURE"]  # type: ignore[no-any-return]

    def get_cookie_samesite(self, app: Flask) -> str | None:
        """
        获取会话cookie的SameSite属性。

        参数:
        app (Flask): 当前的Flask应用实例。

        返回:
        str | None: 会话cookie的SameSite属性，如果没有设置，则返回None。
        """
        return app.config["SESSION_COOKIE_SAMESITE"]  # type: ignore[no-any-return]

    def get_expiration_time(self, app: Flask, session: SessionMixin) -> datetime | None:
        """
        获取会话的过期时间。

        参数:
        app (Flask): 当前的Flask应用实例。
        session (SessionMixin): 当前的会话对象。

        返回:
        datetime | None: 会话的过期时间，如果会话不是永久的，则返回None。
        """
        if session.permanent:
            return datetime.now(timezone.utc) + app.permanent_session_lifetime
        return None

    def should_set_cookie(self, app: Flask, session: SessionMixin) -> bool:
        """
        检查是否应该设置会话cookie。

        参数:
        app (Flask): 当前的Flask应用实例。
        session (SessionMixin): 当前的会话对象。

        返回:
        bool: 如果应该设置会话cookie，则返回True，否则返回False。
        """
        return session.modified or (
            session.permanent and app.config["SESSION_REFRESH_EACH_REQUEST"]
        )

    def open_session(self, app: Flask, request: Request) -> SessionMixin | None:
        """
        打开会话，根据请求初始化会话数据。

        参数:
        app (Flask): 当前的Flask应用实例。
        request (Request): 当前的请求对象。

        返回:
        SessionMixin | None: 初始化后的会话对象，如果没有会话数据，则返回None。
        """
        raise NotImplementedError()

    def save_session(
        self, app: Flask, session: SessionMixin, response: Response
    ) -> None:
        """
        保存会话，将会话数据更新到响应中。

        参数:
        app (Flask): 当前的Flask应用实例。
        session (SessionMixin): 当前的会话对象。
        response (Response): 当前的响应对象。

        返回:
        None
        """
        raise NotImplementedError()


session_json_serializer = TaggedJSONSerializer()


def _lazy_sha1(string: bytes = b"") -> t.Any:

    return hashlib.sha1(string)


class SecureCookieSessionInterface(SessionInterface):
    """
    提供一个安全的Cookie会话接口，用于在Flask应用中管理用户会话。
    它包括会话数据的序列化、验证和在客户端（浏览器）与服务器之间安全传输的机制。
    """

    # 用于签名的盐值，增加签名的安全性
    salt = "cookie-session"
    # 使用SHA1进行数据签名，确保数据完整性
    digest_method = staticmethod(_lazy_sha1)
    # 使用HMAC作为密钥派生函数，增强安全性
    key_derivation = "hmac"
    # 使用JSON序列化会话数据
    serializer = session_json_serializer
    # 会话类，用于存储会话数据
    session_class = SecureCookieSession

    def get_signing_serializer(self, app: Flask) -> URLSafeTimedSerializer | None:
        """
        获取一个用于签名和验证的序列化器。

        :param app: Flask应用实例
        :return: 一个URLSafeTimedSerializer实例，用于安全地序列化和签名会话数据，如果没有配置密钥则返回None
        """
        if not app.secret_key:
            return None
        signer_kwargs = dict(
            key_derivation=self.key_derivation, digest_method=self.digest_method
        )
        return URLSafeTimedSerializer(
            app.secret_key,
            salt=self.salt,
            serializer=self.serializer,
            signer_kwargs=signer_kwargs,
        )

    def open_session(self, app: Flask, request: Request) -> SecureCookieSession | None:
        """
        从请求中加载会话数据。

        :param app: Flask应用实例
        :param request: 请求对象
        :return: 一个SecureCookieSession实例，包含从请求中恢复的会话数据，如果没有有效数据则返回空会话或None
        """
        s = self.get_signing_serializer(app)
        if s is None:
            return None
        val = request.cookies.get(self.get_cookie_name(app))
        if not val:
            return self.session_class()
        max_age = int(app.permanent_session_lifetime.total_seconds())
        try:
            data = s.loads(val, max_age=max_age)
            return self.session_class(data)
        except BadSignature:
            return self.session_class()

    def save_session(
        self, app: Flask, session: SessionMixin, response: Response
    ) -> None:
        """
        将会话数据保存到响应中。

        :param app: Flask应用实例
        :param session: 会话对象
        :param response: 响应对象
        """
        # 准备cookie相关配置
        name = self.get_cookie_name(app)
        domain = self.get_cookie_domain(app)
        path = self.get_cookie_path(app)
        secure = self.get_cookie_secure(app)
        samesite = self.get_cookie_samesite(app)
        httponly = self.get_cookie_httponly(app)

        # 如果会话被访问，添加Vary: Cookie头，以正确缓存响应
        if session.accessed:
            response.vary.add("Cookie")

        # 如果会话为空，且已被修改，删除cookie
        if not session:
            if session.modified:
                response.delete_cookie(
                    name,
                    domain=domain,
                    path=path,
                    secure=secure,
                    samesite=samesite,
                    httponly=httponly,
                )
                response.vary.add("Cookie")
            return

        # 检查是否应该设置cookie
        if not self.should_set_cookie(app, session):
            return

        # 设置cookie的过期时间、值等
        expires = self.get_expiration_time(app, session)
        val = self.get_signing_serializer(app).dumps(dict(session))  # type: ignore[union-attr]
        response.set_cookie(
            name,
            val,
            expires=expires,
            httponly=httponly,
            domain=domain,
            path=path,
            secure=secure,
            samesite=samesite,
        )
        response.vary.add("Cookie")
