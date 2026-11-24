"""Signing in to Layla's cloud (blocking: run these in the executor).

Layla's apps sign in with an AWS Cognito user pool. The password is used once, to sign in; only
the refresh token is kept, and each access token (an hour long) comes from it. Which pool and app client
are used comes from Endpoints (Layla's web app's, unless the user changed them).
"""

from __future__ import annotations

from dataclasses import dataclass

from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pycognito import Cognito
from pycognito.exceptions import ForceChangePasswordException, MFAChallengeException, TokenVerificationException

from .model import token_claims
from .settings import Endpoints


class LaylaAuthError(Exception):
    """The sign-in was refused: a wrong password, an unknown email, or an expired session."""


class LaylaMfaError(LaylaAuthError):
    """The account asks for a second step, which this integration can't answer."""


class LaylaConnectError(Exception):
    """Layla's sign-in service couldn't be reached."""


class LaylaEndpointError(LaylaConnectError):
    """The sign-in service doesn't know the user pool or app client (only likely when they were changed)."""


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: float  # Unix time
    user_id: str  # the account's id (the token's subject)


def _cognito(endpoints: Endpoints, **kwargs) -> Cognito:
    return Cognito(
        endpoints.user_pool_id,
        endpoints.client_id,
        user_pool_region=endpoints.region,
        botocore_config=Config(signature_version=UNSIGNED),
        **kwargs,
    )


def _tokens(c: Cognito) -> Tokens:
    claims = token_claims(c.access_token or "")
    return Tokens(c.access_token, c.refresh_token, float(claims.get("exp") or 0), str(claims.get("sub") or ""))


_REFUSED = {"NotAuthorizedException", "UserNotFoundException", "UserNotConfirmedException", "PasswordResetRequiredException"}
# A user pool or app client that doesn't exist, or a client that doesn't allow this way of signing in
_MISCONFIGURED = {"ResourceNotFoundException", "InvalidParameterException"}


def _client_error(err: ClientError, refused: str) -> Exception:
    code = err.response.get("Error", {}).get("Code")
    message = err.response.get("Error", {}).get("Message") or str(err)
    if code in _REFUSED:
        return LaylaAuthError(refused or message)
    if code in _MISCONFIGURED:
        return LaylaEndpointError(message)
    return LaylaConnectError(str(err))


def sign_in(email: str, password: str, endpoints: Endpoints | None = None) -> Tokens:
    """Sign in with the account's email and password (SRP: the password never leaves this process)."""
    try:
        c = _cognito(endpoints or Endpoints(), username=email)
        c.authenticate(password=password)
    except MFAChallengeException as err:
        raise LaylaMfaError("two-step verification is on for this account") from err
    except ForceChangePasswordException as err:
        raise LaylaAuthError("Layla asks for a new password: set one in the Layla app first") from err
    except ClientError as err:
        raise _client_error(err, "") from err
    except (BotoCoreError, OSError, ValueError, TokenVerificationException) as err:
        raise LaylaConnectError(str(err)) from err
    return _tokens(c)


def refresh(refresh_token: str, endpoints: Endpoints | None = None) -> Tokens:
    """A new access token from the refresh token (and a new refresh token, if Cognito rotates it)."""
    try:
        c = _cognito(endpoints or Endpoints(), refresh_token=refresh_token)
        c.renew_access_token()
    except ClientError as err:
        raise _client_error(err, "the Layla session has ended: sign in again") from err
    except (BotoCoreError, OSError, ValueError, TokenVerificationException) as err:
        raise LaylaConnectError(str(err)) from err
    return _tokens(c)
