from cryptography.fernet import Fernet, InvalidToken

from nawa.core.config import Settings
from nawa.core.errors import ServiceUnavailableError

_MISSING_KEY = (
    "DATA_ENCRYPTION_KEY is missing or not a valid Fernet key; "
    "data source credentials cannot be stored or read"
)


class CredentialVault:
    """Encrypts secrets at rest with Fernet. The key comes from `DATA_ENCRYPTION_KEY`."""

    def __init__(self, key: str | None) -> None:
        self._fernet: Fernet | None = None
        if key:
            try:
                self._fernet = Fernet(key.encode())
            except ValueError:
                self._fernet = None

    def _require(self) -> Fernet:
        if self._fernet is None:
            raise ServiceUnavailableError(_MISSING_KEY)
        return self._fernet

    def encrypt(self, plaintext: str) -> str:
        return self._require().encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        fernet = self._require()
        try:
            return fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Credential cannot be decrypted with the configured key") from exc


def get_vault(settings: Settings) -> CredentialVault:
    return CredentialVault(settings.data_encryption_key)
