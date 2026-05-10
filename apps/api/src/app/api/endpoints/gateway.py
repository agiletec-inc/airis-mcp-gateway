"""Gateway control endpoints"""
import asyncio
import os

from fastapi import APIRouter, HTTPException, status

from ...core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["gateway"])


def _project_root() -> str:
    return os.getenv(
        "PROJECT_ROOT",
        os.getenv("CONTAINER_PROJECT_ROOT", "/workspace/project"),
    )


async def _run_compose(*args: str, timeout: int = 30) -> asyncio.subprocess.Process:
    proc = await asyncio.create_subprocess_exec(
        "docker", "compose", *args,
        cwd=_project_root(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    return proc


@router.post("/restart", response_model=dict)
async def restart_gateway():
    """Restart MCP Gateway to apply new secrets"""
    try:
        proc = await _run_compose("restart", "mcp-gateway", timeout=30)

        if proc.returncode != 0:
            stderr = (await proc.stderr.read()).decode() if proc.stderr else ""
            logger.error(f"Gateway restart failed: {stderr}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to restart gateway",
            )

        return {
            "status": "success",
            "message": "MCP Gateway restarted successfully",
        }

    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Gateway restart timeout",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Gateway restart unexpected error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/status", response_model=dict)
async def gateway_status():
    """Get MCP Gateway status"""
    try:
        proc = await _run_compose("ps", "mcp-gateway", timeout=10)
        stdout = (await proc.stdout.read()).decode() if proc.stdout else ""
        is_running = "Up" in stdout

        return {
            "status": "running" if is_running else "stopped",
            "details": stdout,
        }

    except Exception as e:
        logger.error(f"Gateway status check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get gateway status",
        )
