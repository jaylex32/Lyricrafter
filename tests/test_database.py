from app.core.database import AppDatabase
from app.core.jobs import JobStatus, LyricJob


def test_clear_history(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.sqlite3")
    job = LyricJob(source_path=tmp_path / "song.mp3")
    job.status = JobStatus.COMPLETE
    db.save_job(job)

    assert len(db.list_history()) == 1

    db.clear_history()

    assert db.list_history() == []
