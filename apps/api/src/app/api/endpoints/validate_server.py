"""API endpoints for server validation"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
import httpx
import base64
from typing import Dict, Any, Optional
from urllib.parse import urlparse

router = APIRouter(tags=["validation"])


class ValidateRequest(BaseModel):
    """Request schema for server validation"""
    server_id: str
    config: Dict[str, str]


class ValidateResponse(BaseModel):
    """Response schema for server validation"""
    valid: bool
    message: str
    details: Optional[Dict[str, Any]] = None


async def validate_supabase(config: Dict[str, str]) -> Dict[str, Any]:
    """Validate Supabase configuration"""
    url = config.get('SUPABASE_URL')
    anon_key = config.get('SUPABASE_ANON_KEY')

    if not url or not anon_key:
        return {"valid": False, "message": "Missing required fields: SUPABASE_URL and SUPABASE_ANON_KEY"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{url}/rest/v1/",
                headers={"apikey": anon_key},
                timeout=10.0
            )
            if response.status_code == 200:
                return {"valid": True, "message": "Successfully connected to Supabase"}
            else:
                return {"valid": False, "message": f"Supabase API returned status {response.status_code}"}
    except Exception as e:
        return {"valid": False, "message": f"Connection failed: {str(e)}"}


async def validate_supabase_selfhost(config: Dict[str, str]) -> Dict[str, Any]:
    """Validate Supabase self-host configuration (PostgREST + PostgreSQL DSN)"""
    pg_dsn = config.get('PG_DSN')
    postgrest_url = config.get('POSTGREST_URL')
    postgrest_jwt = config.get('POSTGREST_JWT')

    missing_fields = [
        field for field, value in [
            ("PG_DSN", pg_dsn),
            ("POSTGREST_URL", postgrest_url),
            ("POSTGREST_JWT", postgrest_jwt)
        ] if not value
    ]

    if missing_fields:
        missing = ", ".join(missing_fields)
        return {"valid": False, "message": f"Missing required fields: {missing}"}

    parsed_dsn = urlparse(pg_dsn)
    if parsed_dsn.scheme not in {"postgres", "postgresql"} or not parsed_dsn.hostname:
        return {"valid": False, "message": "Invalid PG_DSN format. Expected postgres://user:pass@host:port/db"}

    # Type narrowing: these are guaranteed non-None by the missing_fields check above
    if postgrest_url is None or postgrest_jwt is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="POSTGREST_URL and POSTGREST_JWT are required",
        )
    normalized_postgrest_url = postgrest_url.rstrip("/")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{normalized_postgrest_url}/",
                headers={
                    "apikey": postgrest_jwt,
                    "Authorization": f"Bearer {postgrest_jwt}"
                },
                timeout=10.0
            )

        if response.status_code == 200:
            return {
                "valid": True,
                "message": "Successfully connected to Supabase self-host PostgREST endpoint",
                "details": {"postgrest_url": normalized_postgrest_url}
            }
        return {"valid": False, "message": f"PostgREST returned status {response.status_code}"}
    except Exception as e:
        return {"valid": False, "message": f"PostgREST connection failed: {str(e)}"}


async def validate_stripe(config: Dict[str, str]) -> Dict[str, Any]:
    """Validate Stripe configuration"""
    secret_key = config.get('STRIPE_SECRET_KEY')

    if not secret_key:
        return {"valid": False, "message": "Missing STRIPE_SECRET_KEY"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.stripe.com/v1/balance",
                auth=(secret_key, ""),
                timeout=10.0
            )
            if response.status_code == 200:
                return {"valid": True, "message": "Successfully authenticated with Stripe"}
            else:
                return {"valid": False, "message": f"Stripe API returned status {response.status_code}"}
    except Exception as e:
        return {"valid": False, "message": f"Authentication failed: {str(e)}"}


async def validate_github(config: Dict[str, str]) -> Dict[str, Any]:
    """Validate GitHub configuration"""
    token = config.get('GITHUB_PERSONAL_ACCESS_TOKEN')

    if not token:
        return {"valid": False, "message": "Missing GITHUB_PERSONAL_ACCESS_TOKEN"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )
            if response.status_code == 200:
                user_data = response.json()
                return {
                    "valid": True,
                    "message": f"Authenticated as {user_data.get('login', 'unknown')}",
                    "details": {"username": user_data.get('login')}
                }
            else:
                return {"valid": False, "message": f"GitHub API returned status {response.status_code}"}
    except Exception as e:
        return {"valid": False, "message": f"Authentication failed: {str(e)}"}


async def validate_slack(config: Dict[str, str]) -> Dict[str, Any]:
    """Validate Slack configuration"""
    bot_token = config.get('SLACK_BOT_TOKEN')

    if not bot_token:
        return {"valid": False, "message": "Missing SLACK_BOT_TOKEN"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {bot_token}"},
                timeout=10.0
            )
            data = response.json()
            if data.get('ok'):
                return {
                    "valid": True,
                    "message": f"Connected to workspace: {data.get('team', 'unknown')}",
                    "details": {"team": data.get('team'), "user": data.get('user')}
                }
            else:
                return {"valid": False, "message": f"Slack API error: {data.get('error', 'unknown')}"}
    except Exception as e:
        return {"valid": False, "message": f"Connection failed: {str(e)}"}


async def validate_twilio(config: Dict[str, str]) -> Dict[str, Any]:
    """Validate Twilio configuration"""
    account_sid = config.get('TWILIO_ACCOUNT_SID')
    api_key = config.get('TWILIO_API_KEY')
    api_secret = config.get('TWILIO_API_SECRET')

    if not all([account_sid, api_key, api_secret]):
        return {"valid": False, "message": "Missing required fields: TWILIO_ACCOUNT_SID, TWILIO_API_KEY, TWILIO_API_SECRET"}

    try:
        auth = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}.json",
                headers={"Authorization": f"Basic {auth}"},
                timeout=10.0
            )
            if response.status_code == 200:
                account_data = response.json()
                return {
                    "valid": True,
                    "message": f"Connected to Twilio account: {account_data.get('friendly_name', 'unknown')}",
                    "details": {"account_name": account_data.get('friendly_name')}
                }
            else:
                return {"valid": False, "message": f"Twilio API returned status {response.status_code}"}
    except Exception as e:
        return {"valid": False, "message": f"Authentication failed: {str(e)}"}


async def validate_notion(config: Dict[str, str]) -> Dict[str, Any]:
    """Validate Notion configuration"""
    api_key = config.get('NOTION_API_KEY')

    if not api_key:
        return {"valid": False, "message": "Missing NOTION_API_KEY"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.notion.com/v1/users/me",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Notion-Version": "2022-06-28"
                },
                timeout=10.0
            )
            if response.status_code == 200:
                user_data = response.json()
                return {
                    "valid": True,
                    "message": f"Authenticated as {user_data.get('name', 'unknown')}",
                    "details": {"user_name": user_data.get('name')}
                }
            else:
                return {"valid": False, "message": f"Notion API returned status {response.status_code}"}
    except Exception as e:
        return {"valid": False, "message": f"Authentication failed: {str(e)}"}


async def validate_sentry(config: Dict[str, str]) -> Dict[str, Any]:
    """Validate Sentry configuration"""
    auth_token = config.get('SENTRY_AUTH_TOKEN')
    org = config.get('SENTRY_ORG')
    base_url = config.get('SENTRY_BASE_URL', 'https://sentry.io')

    if not auth_token or not org:
        return {"valid": False, "message": "Missing required fields: SENTRY_AUTH_TOKEN and SENTRY_ORG"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{base_url}/api/0/organizations/{org}/",
                headers={"Authorization": f"Bearer {auth_token}"},
                timeout=10.0
            )
            if response.status_code == 200:
                org_data = response.json()
                return {
                    "valid": True,
                    "message": f"Connected to organization: {org_data.get('name', org)}",
                    "details": {"org_name": org_data.get('name')}
                }
            else:
                return {"valid": False, "message": f"Sentry API returned status {response.status_code}"}
    except Exception as e:
        return {"valid": False, "message": f"Connection failed: {str(e)}"}


# Validation function mapping
VALIDATORS = {
    'supabase': validate_supabase,
    'supabase-selfhost': validate_supabase_selfhost,
    'stripe': validate_stripe,
    'github': validate_github,
    'slack': validate_slack,
    'twilio': validate_twilio,
    'notion': validate_notion,
    'sentry': validate_sentry,
}


@router.post(
    "/validate/{server_id}",
    response_model=ValidateResponse
)
async def validate_server(server_id: str, request: ValidateRequest):
    """
    Validate server configuration by attempting actual connection

    Args:
        server_id: ID of the server to validate
        request: Configuration to validate

    Returns:
        Validation result with success/failure message
    """
    # Check if validator exists for this server
    validator = VALIDATORS.get(server_id)
    if not validator:
        return ValidateResponse(
            valid=True,
            message=f"No validation available for {server_id} (assuming valid)"
        )

    # Run validation
    try:
        result = await validator(request.config)
        return ValidateResponse(**result)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Validation error: {str(e)}"
        )
