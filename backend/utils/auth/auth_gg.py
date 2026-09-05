"""
Google OAuth Authentication Utility.

Responsibilities:
- Initialize Google OAuth
- Redirect user to Google login page
- Handle Google OAuth callback
- Retrieve authenticated Google user information

This file does NOT:
- Access MongoDB
- Create users
- Check whether users exist
- Update login information
- Generate JWT

Those responsibilities are handled by other files.
"""

import os
from typing import Any, Dict

from authlib.integrations.starlette_client import OAuth
from dotenv import load_dotenv
from fastapi import HTTPException, Request, status
from starlette.responses import RedirectResponse


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()


GOOGLE_CLIENT_ID = os.getenv(
    "GOOGLE_CLIENT_ID"
)

GOOGLE_CLIENT_SECRET = os.getenv(
    "GOOGLE_CLIENT_SECRET"
)

GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI"
)


# ============================================================
# VALIDATE GOOGLE OAUTH CONFIGURATION
# ============================================================

def validate_google_oauth_config() -> None:
    """
    Validate required Google OAuth environment variables.

    Raises:
        RuntimeError:
            If one or more required environment variables
            are missing.
    """

    missing_variables = []

    if not GOOGLE_CLIENT_ID:
        missing_variables.append(
            "GOOGLE_CLIENT_ID"
        )

    if not GOOGLE_CLIENT_SECRET:
        missing_variables.append(
            "GOOGLE_CLIENT_SECRET"
        )

    if not GOOGLE_REDIRECT_URI:
        missing_variables.append(
            "GOOGLE_REDIRECT_URI"
        )

    if missing_variables:

        raise RuntimeError(
            "Missing Google OAuth environment variables: "
            + ", ".join(missing_variables)
        )


# ============================================================
# INITIALIZE OAUTH
# ============================================================

oauth = OAuth()


def register_google_oauth() -> None:
    """
    Register Google as an OAuth provider.
    """

    validate_google_oauth_config()

    oauth.register(
        name="google",

        client_id=GOOGLE_CLIENT_ID,

        client_secret=GOOGLE_CLIENT_SECRET,

        server_metadata_url=(
            "https://accounts.google.com/"
            ".well-known/openid-configuration"
        ),

        client_kwargs={
            "scope": "openid email profile"
        }
    )


# Register Google OAuth provider
register_google_oauth()


# ============================================================
# START GOOGLE LOGIN
# ============================================================

async def login_with_google(
    request: Request
) -> RedirectResponse:
    """
    Start Google OAuth login process.

    Flow:

        User
          ↓
        Backend
          ↓
        Google Login Page

    Args:
        request:
            FastAPI Request.

    Returns:
        RedirectResponse:
            Redirects the user to Google's login page.

    Raises:
        HTTPException:
            If the Google OAuth process cannot be started.
    """

    try:

        return await oauth.google.authorize_redirect(
            request,
            GOOGLE_REDIRECT_URI
        )

    except Exception as error:

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                "Unable to start Google authentication. "
                f"Error: {str(error)}"
            )
        )


# ============================================================
# GET GOOGLE USER INFORMATION
# ============================================================

async def get_google_user_info(
    request: Request
) -> Dict[str, Any]:
    """
    Process the Google OAuth callback and retrieve
    authenticated user information.

    Flow:

        Google Callback
            ↓
        Get Authorization Code
            ↓
        Exchange Code for Access Token
            ↓
        Get Google User Information
            ↓
        Return Normalized User Data

    Args:
        request:
            FastAPI Request received from Google callback.

    Returns:
        Dict containing:

        {
            "sub": "...",
            "email": "...",
            "name": "...",
            "email_verified": True
        }

    Raises:
        HTTPException:
            If Google authentication fails.
    """

    try:

        # ====================================================
        # 1. EXCHANGE AUTHORIZATION CODE FOR TOKEN
        # ====================================================

        token = await oauth.google.authorize_access_token(
            request
        )


        # ====================================================
        # 2. GET USER INFORMATION
        # ====================================================

        user_info = token.get(
            "userinfo"
        )


        # ====================================================
        # 3. FALLBACK TO GOOGLE USERINFO ENDPOINT
        # ====================================================

        if not user_info:

            response = await oauth.google.get(
                "userinfo",
                token=token
            )

            user_info = response.json()


        # ====================================================
        # 4. VALIDATE USER INFORMATION
        # ====================================================

        if not user_info:

            raise HTTPException(
                status_code=(
                    status.HTTP_401_UNAUTHORIZED
                ),
                detail=(
                    "Unable to retrieve Google user information"
                )
            )


        google_id = user_info.get(
            "sub"
        )

        email = user_info.get(
            "email"
        )


        if not google_id:

            raise HTTPException(
                status_code=(
                    status.HTTP_401_UNAUTHORIZED
                ),
                detail="Google user ID is missing"
            )


        if not email:

            raise HTTPException(
                status_code=(
                    status.HTTP_401_UNAUTHORIZED
                ),
                detail="Google user email is missing"
            )


        # ====================================================
        # 5. NORMALIZE USER DATA
        # ====================================================

        google_user = {

            # Google unique user ID
            "sub": google_id,

            # Google account email
            "email": email,

            # Google account name
            "name": user_info.get(
                "name"
            ),

            # Email verification status
            "email_verified": user_info.get(
                "email_verified",
                False
            )
        }


        return google_user


    except HTTPException:

        raise


    except Exception as error:

        raise HTTPException(
            status_code=(
                status.HTTP_401_UNAUTHORIZED
            ),
            detail=(
                "Google authentication failed. "
                f"Error: {str(error)}"
            )
        )


# ============================================================
# GOOGLE AUTHENTICATION HELPER
# ============================================================

async def authenticate_google_user(
    request: Request
) -> Dict[str, Any]:
    """
    Helper function for Google authentication.

    This function is an alias for get_google_user_info().

    Args:
        request:
            FastAPI Request from Google callback.

    Returns:
        Normalized Google user information.
    """

    return await get_google_user_info(
        request
    )