import subprocess


def test_alembic_upgrade_head_smoke():
    subprocess.run(
        ["alembic", "upgrade", "head"],
        check=True,
        capture_output=True,
        text=True,
    )
