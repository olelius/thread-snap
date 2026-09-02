"""腾讯双图滑块的本地图像识别。"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image
from scipy import ndimage


@dataclass(frozen=True)
class SliderOffset:
    """背景原图坐标与页面拖动距离。"""

    source_x: int
    source_y: int
    drag_css_px: float
    confidence_margin: float
    selection_reason: str


def analyze_slider_offset(
    background_bytes: bytes,
    sprite_bytes: bytes,
    *,
    display_width: float,
    piece_top_css: float,
    piece_left_css: float,
    piece_sprite_x: int,
    piece_sprite_y: int,
) -> SliderOffset:
    """结合拼图块轮廓、明暗差和纹理相关性定位背景缺口。"""

    background_image = Image.open(BytesIO(background_bytes)).convert("RGB")
    sprite_image = Image.open(BytesIO(sprite_bytes)).convert("RGBA")
    background = np.asarray(background_image, dtype=np.float32)
    sprite = np.asarray(sprite_image, dtype=np.float32)
    if background.ndim != 3 or sprite.ndim != 3:
        raise ValueError("腾讯验证码图片维度异常。")

    crop_width = crop_height = 120
    piece_rgba = sprite[
        piece_sprite_y : piece_sprite_y + crop_height,
        piece_sprite_x : piece_sprite_x + crop_width,
    ]
    if piece_rgba.shape != (crop_height, crop_width, 4):
        raise ValueError("腾讯验证码拼图块超出精灵图范围。")
    mask = piece_rgba[:, :, 3].astype(np.uint8) > 96
    if int(np.count_nonzero(mask)) < 100:
        raise ValueError("腾讯验证码拼图块透明轮廓异常。")

    boundary = ndimage.binary_dilation(mask, iterations=2) ^ ndimage.binary_erosion(
        mask, iterations=2
    )
    inner = ndimage.binary_erosion(mask, iterations=5)
    outer = ndimage.binary_dilation(mask, iterations=8) & ~ndimage.binary_dilation(
        mask, iterations=2
    )
    gray = background.mean(axis=2)
    piece_gray = piece_rgba[:, :, :3].mean(axis=2)
    grad_x = ndimage.sobel(gray, axis=1, mode="reflect")
    grad_y = ndimage.sobel(gray, axis=0, mode="reflect")
    gradient = np.hypot(grad_x, grad_y)
    piece_gradient = np.hypot(
        ndimage.sobel(piece_gray, axis=1, mode="reflect"),
        ndimage.sobel(piece_gray, axis=0, mode="reflect"),
    )
    texture_mask = ndimage.binary_erosion(mask, iterations=4)
    scale = display_width / background.shape[1]
    target_y = int(round(piece_top_css / scale))
    if target_y < 0 or target_y + crop_height > background.shape[0]:
        raise ValueError("腾讯验证码拼图块纵向位置异常。")

    def normalized_correlation(left: np.ndarray, right: np.ndarray) -> float:
        left_values = left[texture_mask].astype(np.float64)
        right_values = right[texture_mask].astype(np.float64)
        left_values -= left_values.mean()
        right_values -= right_values.mean()
        denominator = np.linalg.norm(left_values) * np.linalg.norm(right_values)
        return float(np.dot(left_values, right_values) / (denominator + 1e-9))

    scores: list[dict[str, float | int]] = []
    for target_x in range(0, background.shape[1] - crop_width + 1):
        patch_gray = gray[target_y : target_y + crop_height, target_x : target_x + crop_width]
        patch_grad = gradient[
            target_y : target_y + crop_height, target_x : target_x + crop_width
        ]
        edge_score = float(np.mean(patch_grad[boundary]))
        contrast_score = float(np.mean(patch_gray[outer]) - np.mean(patch_gray[inner]))
        texture_score = normalized_correlation(piece_gray, patch_gray)
        texture_gradient_score = normalized_correlation(piece_gradient, patch_grad)
        scores.append(
            {
                "x": target_x,
                "edge": edge_score,
                "contrast": contrast_score,
                "texture_combined": texture_score + texture_gradient_score,
            }
        )
    if not scores:
        raise ValueError("腾讯验证码背景图没有可扫描区域。")

    edge_values = np.asarray([item["edge"] for item in scores], dtype=float)
    contrast_values = np.asarray([item["contrast"] for item in scores], dtype=float)
    edge_z = (edge_values - edge_values.mean()) / (edge_values.std() + 1e-9)
    contrast_z = (contrast_values - contrast_values.mean()) / (
        contrast_values.std() + 1e-9
    )
    for item, value in zip(scores, edge_z + 0.8 * contrast_z, strict=True):
        item["combined"] = float(value)

    ranked = sorted(scores, key=lambda item: float(item["combined"]), reverse=True)
    peaks: list[dict[str, float | int]] = []
    for item in ranked:
        if all(abs(int(item["x"]) - int(existing["x"])) >= 20 for existing in peaks):
            peaks.append(item)
        if len(peaks) == 5:
            break
    best = peaks[0]
    selection_reason = "strongest-outline"
    if (
        len(peaks) > 1
        and float(peaks[0]["texture_combined"]) > 1.2
        and float(peaks[1]["combined"]) >= 0.55 * float(peaks[0]["combined"])
        and float(peaks[1]["texture_combined"]) < 0.8
    ):
        best = peaks[1]
        selection_reason = "paired-outline-excluding-source-texture"
    alternatives = peaks[1:] if best is peaks[0] else [item for item in peaks if item is not best]
    confidence_margin = (
        float(best["combined"]) - float(alternatives[0]["combined"])
        if alternatives
        else float(best["combined"])
    )
    source_x = int(best["x"])
    return SliderOffset(
        source_x=source_x,
        source_y=target_y,
        drag_css_px=source_x * scale - piece_left_css,
        confidence_margin=confidence_margin,
        selection_reason=selection_reason,
    )
