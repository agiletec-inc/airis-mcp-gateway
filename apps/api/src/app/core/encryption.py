"""Encryption utilities for secret management"""
import base64
import os
import stat
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from .config import settings
from .logging import get_logger

logger = get_logger(__name__)

_SECURE_FILE_MODE = 0o600


def _is_production() -> bool:
    return os.getenv("ENV", "").lower() == "production"


def _allow_insecure_perms() -> bool:
    return os.getenv("ENCRYPTION_ALLOW_INSECURE_KEY_PERMS", "").lower() in (
        "1",
        "true",
        "yes",
    )


def _chmod_strict(path: Path, *, description: str) -> None:
    """chmod a secret file to 0o600 and fail-closed if the result is wrong.

    Some filesystems (Windows shares, NFS without ACL, tmpfs in locked-down
    containers) silently ignore chmod. Detect this and refuse to continue
    unless the operator explicitly opts in via
    ENCRYPTION_ALLOW_INSECURE_KEY_PERMS=1.
    """
    try:
        os.chmod(path, _SECURE_FILE_MODE)
    except OSError as exc:
        logger.warning("Could not chmod %s on %s: %s", oct(_SECURE_FILE_MODE), path, exc)

    try:
        actual = stat.S_IMODE(os.stat(path).st_mode)
    except OSError as exc:
        raise RuntimeError(
            f"Failed to stat {description} at {path} after chmod: {exc}"
        ) from exc

    if actual == _SECURE_FILE_MODE:
        return

    msg = (
        f"{description} at {path} has insecure permissions {oct(actual)}; "
        f"expected {oct(_SECURE_FILE_MODE)}"
    )
    if _allow_insecure_perms():
        logger.warning(
            "%s (continuing because ENCRYPTION_ALLOW_INSECURE_KEY_PERMS=1)", msg
        )
        return
    raise RuntimeError(
        msg
        + ". Refusing to use this file. Set ENCRYPTION_ALLOW_INSECURE_KEY_PERMS=1 "
        "to override (not recommended)."
    )


def _default_key_path() -> Path:
    """Resolve the default file location for the persisted master key."""
    configured_path = os.getenv("ENCRYPTION_MASTER_KEY_FILE")
    if configured_path:
        return Path(configured_path).expanduser().resolve()

    project_root = settings.PROJECT_ROOT
    return (project_root / "data" / "encryption_master.key").resolve()


class EncryptionManager:
    """Manages encryption and decryption of secrets"""

    def __init__(self, master_key: str | None = None):
        """
        Initialize encryption manager with master key

        Args:
            master_key: Master encryption key. If None, generates or reads from env.
        """
        self._key_file_path = _default_key_path()

        if master_key is None:
            master_key = os.getenv("ENCRYPTION_MASTER_KEY")

            if not master_key and _is_production():
                raise RuntimeError(
                    "ENCRYPTION_MASTER_KEY must be set explicitly in production. "
                    "Relying on the persisted key file is forbidden because an "
                    "ephemeral container filesystem would regenerate it on restart "
                    "and permanently lock existing ciphertext. "
                    "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
                )

            if not master_key:
                master_key = self._load_persisted_key()

            if not master_key:
                master_key = Fernet.generate_key().decode()
                self._persist_key(master_key)
                logger.warning(f"Generated new ENCRYPTION_MASTER_KEY and stored it at {self._key_file_path}")
                logger.warning("Set ENCRYPTION_MASTER_KEY in your environment to override the persisted key")

        assert isinstance(master_key, str)
        self.master_key = master_key
        self._fernet = self._create_fernet(master_key)

    def _salt_path(self) -> Path:
        return self._key_file_path.parent / "encryption_salt.bin"

    def _get_or_create_salt(self) -> bytes:
        """Load persisted salt or generate and store a new one."""
        salt_path = self._salt_path()
        try:
            if salt_path.is_file():
                return salt_path.read_bytes()
        except OSError:
            pass

        salt = os.urandom(16)
        try:
            salt_path.parent.mkdir(parents=True, exist_ok=True)
            salt_path.write_bytes(salt)
        except OSError as exc:
            logger.warning(f"Failed to persist encryption salt to {salt_path}: {exc}")
            return salt

        _chmod_strict(salt_path, description="encryption salt")
        return salt

    def _create_fernet(self, master_key: str) -> Fernet:
        """Create Fernet cipher from master key"""
        salt = self._get_or_create_salt()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend(),
        )
        key = base64.urlsafe_b64encode(kdf.derive(master_key.encode()))
        return Fernet(key)

    def encrypt(self, plaintext: str) -> bytes:
        """
        Encrypt plaintext string

        Args:
            plaintext: String to encrypt

        Returns:
            Encrypted bytes
        """
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, encrypted: bytes) -> str:
        """
        Decrypt encrypted bytes

        Args:
            encrypted: Encrypted bytes

        Returns:
            Decrypted plaintext string
        """
        return self._fernet.decrypt(encrypted).decode()

    def _load_persisted_key(self) -> str | None:
        """Read a previously generated master key from disk if present."""
        try:
            if self._key_file_path.is_file():
                return self._key_file_path.read_text(encoding="utf-8").strip()
        except OSError:
            pass

        return None

    def _persist_key(self, key: str) -> None:
        """Persist a generated master key so secrets survive restarts."""
        try:
            self._key_file_path.parent.mkdir(parents=True, exist_ok=True)
            self._key_file_path.write_text(key, encoding="utf-8")
        except OSError as exc:
            logger.warning(f"Failed to persist ENCRYPTION_MASTER_KEY to {self._key_file_path}: {exc}")
            return

        _chmod_strict(self._key_file_path, description="encryption master key")

    @staticmethod
    def generate_master_key() -> str:
        """Generate a new master encryption key"""
        return Fernet.generate_key().decode()


# Global encryption manager instance
encryption_manager = EncryptionManager()
