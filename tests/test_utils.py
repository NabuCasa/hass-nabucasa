"""Test utils."""
import pathlib
import tempfile

from hass_nabucasa import utils


def test_safe_write():
    """Test we can safely write to a file."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        orig_file = pathlib.Path(tmp_dir) / "orig-file.txt"
        orig_file.write_text("orig-content")
        orig_file.chmod(0o444)

        utils.safe_write(orig_file, "new-content", None, True)

        assert orig_file.read_text() == "new-content"
        assert orig_file.stat().st_mode == 33152
