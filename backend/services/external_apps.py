"""
Tenants whose software runs as its own application (for example FAI).

Users of these tenants still sign in at app.streemlyne.com. After their
password is checked, StreemLyne signs them in to their own application's
backend and hands the resulting token to that application's /sso page, so
they never sign in twice.

Configured with the EXTERNAL_TENANT_APPS environment variable, a JSON object
keyed by tenant_id:

    {"3": {"name": "FAI",
           "app_url": "http://localhost:3001",
           "api_url": "http://localhost:5001"}}

app_url  - where the tenant's frontend runs (must serve /sso)
api_url  - the tenant's backend, which exposes POST /auth/login
"""

import json
import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

LOGIN_TIMEOUT_SECONDS = 15


class ExternalLoginError(Exception):
    """The tenant's own application refused or failed the sign-in."""


def _load_config() -> dict:
    raw = os.getenv('EXTERNAL_TENANT_APPS', '').strip()
    if not raw:
        return {}
    try:
        config = json.loads(raw)
    except json.JSONDecodeError:
        logger.error('EXTERNAL_TENANT_APPS is not valid JSON; ignoring it')
        return {}
    return {str(k): v for k, v in config.items()}


def get_external_app(tenant_id) -> Optional[dict]:
    """Return the app config for this tenant, or None if it uses StreemLyne itself."""
    if tenant_id is None:
        return None
    app = _load_config().get(str(tenant_id))
    if not app or not app.get('app_url') or not app.get('api_url'):
        return None
    return app


def login_to_external_app(app: dict, user_name: str, password: str) -> str:
    """Sign the user in to the tenant's own backend and return its token."""
    url = app['api_url'].rstrip('/') + '/auth/login'
    try:
        resp = requests.post(
            url,
            json={'user_name': user_name, 'password': password},
            timeout=LOGIN_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        logger.error('Could not reach %s backend: %s', app.get('name', 'external'), e)
        raise ExternalLoginError(f"{app.get('name', 'The application')} is not reachable right now")

    try:
        data = resp.json()
    except ValueError:
        data = {}

    token = data.get('token') or data.get('access_token')
    if resp.status_code != 200 or not token:
        logger.warning('%s login refused (status %s)', app.get('name', 'external'), resp.status_code)
        raise ExternalLoginError(data.get('error') or data.get('message') or 'Sign-in was refused')
    return token


def build_redirect_url(app: dict, token: str) -> str:
    """URL of the tenant app's SSO page. The token travels in the #fragment,
    which browsers never send to servers, so it stays out of server logs."""
    return app['app_url'].rstrip('/') + '/sso/#token=' + token
