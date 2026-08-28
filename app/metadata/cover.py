from __future__ import annotations

from io import BytesIO


def normalize_cover_image(data: bytes | None, mime: str = "image/jpeg") -> tuple[bytes | None, str]:
    if not data:
        return None, "image/jpeg"
    normalized_mime = (mime or "image/jpeg").split(";")[0].lower()
    if normalized_mime in {"image/jpeg", "image/jpg", "image/png"}:
        return data, "image/jpeg" if normalized_mime == "image/jpg" else normalized_mime
    try:
        from PIL import Image
    except ImportError:
        return data, normalized_mime
    try:
        image = Image.open(BytesIO(data))
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        output = BytesIO()
        image.save(output, format="JPEG", quality=92)
        return output.getvalue(), "image/jpeg"
    except Exception:
        return data, normalized_mime
