from app.core.config import APP_NAME, default_online_download_dir, youtube_download_dir


def test_default_online_download_dir_is_user_visible() -> None:
    path = default_online_download_dir()

    assert path.name == APP_NAME
    assert "AppData" not in path.parts


def test_youtube_download_dir_uses_default_online_folder() -> None:
    assert youtube_download_dir() == default_online_download_dir()
