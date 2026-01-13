#!/bin/bash
set -e

if [ "$BROWSER_MODE" = "headed" ]; then
    echo "Starting in HEADED mode with VNC support..."

    # Start Xvfb (virtual framebuffer)
    Xvfb $DISPLAY -screen 0 $VNC_RESOLUTION &
    sleep 1

    # Start fluxbox window manager
    fluxbox -display $DISPLAY &
    sleep 1

    # Start x11vnc server (no password for local dev, add -passwd for production)
    x11vnc -display $DISPLAY -forever -shared -rfbport $VNC_PORT &

    # Start noVNC web server (access at http://localhost:6080/vnc.html)
    /usr/share/novnc/utils/novnc_proxy --vnc localhost:$VNC_PORT --listen $NOVNC_PORT &

    echo "VNC server started on port $VNC_PORT"
    echo "noVNC web access at http://localhost:$NOVNC_PORT/vnc.html"
else
    echo "Starting in HEADLESS mode..."
    # Start Xvfb for headless operation (needed by some browser tools)
    Xvfb $DISPLAY -screen 0 $VNC_RESOLUTION &
    sleep 1
fi

# Start the FastAPI application
cd /app/api-src
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
