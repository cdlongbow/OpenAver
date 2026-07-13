"""core.focal — face-aware focal-point detection (TASK-98a-T1).

Public surface:
    detect_focal(fs_path, ratio, work_width) -> (x_ratio, y_ratio) | None
    crop_image_position(img, ratio, pos) -> PIL.Image
"""
from .detector import crop_image_position, detect_focal

__all__ = ["crop_image_position", "detect_focal"]
