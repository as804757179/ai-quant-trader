from app.ws.manager import WebSocketManager, ws_manager


def get_ws_manager() -> WebSocketManager:
    return ws_manager