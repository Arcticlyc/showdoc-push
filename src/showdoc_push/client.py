import time
from dataclasses import dataclass
from typing import List, Optional, Union

import httpx
from loguru import logger


@dataclass
class QrcodeInfo:
    url: str  # 二维码链接
    qrscene: str  # 二维码参数


@dataclass
class UserInfo:
    uid: int  # 用户ID
    username: str  # 用户名
    groupid: int  # 用户组ID
    name: Optional[str]  # 用户姓名
    certified: bool  # 是否认证
    avatar: str  # 用户头像链接
    avatar_small: str  # 用户头像小图链接
    email: str  # 用户邮箱
    email_verify: bool  # 用户邮箱是否已验证
    mobile: str  # 用户手机号
    password: str  # 用户密码
    created_at: str  # 用户创建时间
    updated_at: str  # 用户更新时间
    last_login_time: str  # 用户最后登录时间
    roles: List[str]  # 用户角色列表
    user_token: str  # 用户登录令牌

    @classmethod
    def from_dict(cls, data: dict | None):
        return cls(**data) if data else None


@dataclass
class QrcodeStatus:
    """
    qrscene和user_info为可选，因为在未扫描二维码时，这两个字段可能不存在
    """

    status: int  # 二维码状态，0-未扫描，1-已扫描
    qrscene: Optional[str] = None  # 二维码参数
    user_info: Optional[UserInfo] = None  # 用户信息

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            status=data["status"],
            qrscene=data.get("qrscene"),
            user_info=UserInfo.from_dict(data.get("user_info")),
        )


class ShowDocPush:
    BASE_PUSH_URL = "https://push.showdoc.com.cn/server/api/push/"

    API_URLS = {
        "get_qrcode_url": "https://push.showdoc.com.cn/server/api/wechat/getQrcodeUrl",
        "check_qrcode_status": "https://push.showdoc.com.cn/server/api/wechat/checkOrcodeStatus",
        "get_token": "https://push.showdoc.com.cn/server/api/push/getToken",
    }

    def __init__(self, token: str = ""):
        if token.startswith("http"):
            token = token.split("/")[-1]
        self.token = token
        self.qrscene: Optional[str] = None

        self.client = httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0",
            }
        )

    # -----------------------
    # 通用请求封装（核心优化）
    # -----------------------

    def _post(self, url: str, data=None) -> dict:
        r = self.client.post(url, data=data)
        r.raise_for_status()

        resp = r.json()

        if resp.get("error_code") != 0:
            raise RuntimeError(resp.get("error_message"))

        return resp.get("data")

    # -----------------------
    # 属性
    # -----------------------

    @property
    def push_url(self) -> str:
        return self.BASE_PUSH_URL + self.token

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
        data = self._post(self.push_url, {"title": title, "content": content})
        logger.info(f"推送成功: {data}")
        return True

    # -----------------------
    # 登录流程（修复）
    # -----------------------

    def qrcode_login(self) -> Union[str, bool, None]:
        """
        第一次调用 → 返回二维码URL
        第二次调用 → 轮询登录
        """

        # 第一步：获取二维码
        if not self.qrscene:
            info = self.get_qrcode_url()
            self.qrscene = info.qrscene
            return info.url

        # 第二步：轮询
        logger.info("等待扫码...")

        for _ in range(10):
            status = self.check_qrcode_status(self.qrscene)

            if status.status == 1 and status.user_info:
                user_token = status.user_info.user_token
                self.token = self.get_token(user_token)
                self.qrscene = None
                logger.success("登录成功")
                return True

            time.sleep(1)

        logger.warning("二维码超时")
        self.qrscene = None
        return None

    def stop_qrcode_login(self):
        self.qrscene = None
