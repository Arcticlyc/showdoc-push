import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

import httpx
from loguru import logger

# -----------------------
# 数据类
# -----------------------


@dataclass
class QrcodeInfo:
    url: str  # 二维码链接
    qrscene: str  # 二维码参数


@dataclass
class UserInfo:
    uid: int
    username: str
    groupid: int
    name: Optional[str]
    certified: bool
    avatar: str
    avatar_small: str
    email: str
    email_verify: bool
    mobile: str
    password: str
    created_at: str
    updated_at: str
    last_login_time: str
    roles: List[str]
    user_token: str

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> Optional["UserInfo"]:
        return cls(**data) if data else None


@dataclass
class QrcodeStatus:
    status: int  # 0-未扫描，1-已扫描
    qrscene: Optional[str] = None
    user_info: Optional[UserInfo] = None

    @classmethod
    def from_dict(cls, data: dict) -> "QrcodeStatus":
        return cls(
            status=data["status"],
            qrscene=data.get("qrscene"),
            user_info=UserInfo.from_dict(data.get("user_info")),
        )


# -----------------------
# 主客户端
# -----------------------


class ShowDocPush:
    BASE_PUSH_URL = "https://push.showdoc.com.cn/server/api/push/"

    API_URLS = {
        "get_qrcode_url": "https://push.showdoc.com.cn/server/api/wechat/getQrcodeUrl",
        "check_qrcode_status": "https://push.showdoc.com.cn/server/api/wechat/checkOrcodeStatus",
        "get_token": "https://push.showdoc.com.cn/server/api/push/getToken",
    }

    def __init__(
        self,
        token: str = "",
    ):
        """
        :param token:         推送 token 或完整推送 URL
        """
        if token.startswith("http"):
            token = token.split("/")[-1]
        self.token = token

        self._qrscene: Optional[str] = None
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self.client = httpx.Client(
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10.0,
        )

    # -----------------------
    # 内部工具
    # -----------------------

    def _post(self, url: str, data: Optional[dict] = None) -> dict:
        resp = self.client.post(url, data=data)
        resp.raise_for_status()
        body = resp.json()
        if body.get("error_code") != 0:
            raise RuntimeError(body.get("error_message", "未知错误"))
        return body["data"]

    # -----------------------
    # 属性
    # -----------------------

    @property
    def push_url(self) -> str:
        return self.BASE_PUSH_URL + self.token

    @property
    def is_polling(self) -> bool:
        """是否正在后台轮询登录"""
        return self._poll_thread is not None and self._poll_thread.is_alive()

    # -----------------------
    # API
    # -----------------------

    def get_qrcode_url(self) -> QrcodeInfo:
        data = self._post(self.API_URLS["get_qrcode_url"])
        return QrcodeInfo(**data)

    def check_qrcode_status(self, qrscene: str) -> QrcodeStatus:
        data = self._post(
            self.API_URLS["check_qrcode_status"],
            {"qrscene": qrscene},
        )
        return QrcodeStatus.from_dict(data)

    def get_token(self, user_token: str) -> str:
        data = self._post(
            self.API_URLS["get_token"],
            {"redirect_login": False, "user_token": user_token},
        )
        return data["token"]

    def push_message(self, title: str, content: str) -> bool:
        """发送推送消息，返回是否成功"""
        data = self._post(self.push_url, {"title": title, "content": content})
        logger.info(f"推送成功: {data}")
        return True

    # -----------------------
    # 登录流程
    # -----------------------

    def start_qrcode_login(
        self,
        poll_interval: float = 1.5,
        poll_timeout: int = 120,
        on_success: Optional[Callable[[str], None]] = None,
        on_timeout: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> str:
        """
        获取二维码 URL，并在后台自动轮询登录状态。
        扫码成功后自动设置 self.token，不阻塞调用方。

        :param poll_interval: 后台轮询间隔（秒）
        :param poll_timeout:  后台轮询超时（秒），超时后自动停止
        :param on_success: 登录成功回调，参数为新 token
        :param on_timeout: 轮询超时回调
        :param on_error:   发生异常时的回调，参数为异常对象
        :return: 二维码图片 URL（供展示/打开）
        """
        if self.is_polling:
            raise RuntimeError(
                "已有登录轮询在进行中，请先调用 stop_qrcode_login() 取消"
            )

        info = self.get_qrcode_url()
        self._qrscene = info.qrscene
        self._stop_event.clear()

        self._poll_thread = threading.Thread(
            target=self._poll_login,
            args=(
                self._qrscene,
                poll_interval,
                poll_timeout,
                on_success,
                on_timeout,
                on_error,
            ),
            daemon=True,
            name="showdoc-login-poll",
        )
        self._poll_thread.start()
        logger.info(f"二维码已生成，后台开始轮询登录（超时 {poll_timeout}s）")

        return info.url

    def _poll_login(
        self,
        qrscene: str,
        poll_interval: float,
        poll_timeout: int,
        on_success: Optional[Callable[[str], None]],
        on_timeout: Optional[Callable[[], None]],
        on_error: Optional[Callable[[Exception], None]],
    ) -> None:
        """后台轮询线程主体"""
        deadline = time.monotonic() + poll_timeout

        try:
            while not self._stop_event.is_set():
                if time.monotonic() > deadline:
                    logger.warning("二维码登录超时")
                    self._qrscene = None
                    if on_timeout:
                        on_timeout()
                    return

                try:
                    status = self.check_qrcode_status(qrscene)
                except Exception as exc:
                    logger.error(f"轮询请求失败: {exc}")
                    if on_error:
                        on_error(exc)
                    return

                if status.status == 1 and status.user_info:
                    try:
                        token = self.get_token(status.user_info.user_token)
                    except Exception as exc:
                        logger.error(f"获取 token 失败: {exc}")
                        if on_error:
                            on_error(exc)
                        return

                    self.token = token
                    self._qrscene = None
                    logger.success(f"登录成功，token 已自动更新")

                    if on_success:
                        try:
                            on_success(token)
                        except Exception as exc:
                            logger.warning(f"on_success 回调异常: {exc}")
                    return

                self._stop_event.wait(poll_interval)

        except Exception as exc:
            logger.error(f"登录轮询意外终止: {exc}")
            if on_error:
                on_error(exc)

    def stop_qrcode_login(self) -> None:
        """主动取消后台登录轮询"""
        self._stop_event.set()
        self._qrscene = None
        logger.info("已取消二维码登录")

    def wait_for_login(self, timeout: Optional[float] = None) -> bool:
        """
        阻塞等待后台登录完成（可选超时）。
        :param timeout: 最长等待秒数，None 表示不限
        :return: True=登录成功，False=超时或未在轮询
        """
        if not self.is_polling:
            return bool(self.token)
        self._poll_thread.join(timeout=timeout)
        return bool(self.token)

    # -----------------------
    # 上下文管理器支持
    # -----------------------

    def close(self) -> None:
        self.stop_qrcode_login()
        self.client.close()

    def __enter__(self) -> "ShowDocPush":
        return self

    def __exit__(self, *_) -> None:
        self.close()
