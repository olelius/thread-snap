"""平台无关的腾讯滑块验证码纯协议求解能力。"""

from .solver import (
    TencentCaptchaError,
    TencentCaptchaResult,
    TencentCaptchaSolver,
    TencentCaptchaSolverProtocol,
)

__all__ = [
    "TencentCaptchaError",
    "TencentCaptchaResult",
    "TencentCaptchaSolver",
    "TencentCaptchaSolverProtocol",
]
