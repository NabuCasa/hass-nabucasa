"""Manage remote UI connections."""
from pathlib import Path

from . import cloud_api


ACME_SERVER = "https://acme-v01.api.letsencrypt.org/directory"
ACCOUNT_KEY_SIZE = 2048


class RemoteUI:
    """Class to help manage remote connections."""

    def __init__(self, cloud):
        """Initialize cloudhooks."""
        self.cloud = cloud
