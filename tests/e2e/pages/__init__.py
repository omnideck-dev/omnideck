"""Page Object Models for e2e tests.

Naming follows docs/ui_architecture.md: the three main views are
Chat, Network View, and Agent Activity View. Shared sub-panels
(PreviewPanel, FilePreview, FullscreenPreview) live here too. FullscreenPreview
represents the generic maximized-surface presentation.
"""

from .chat_view import ChatView
from .network_view import NetworkView
from .agent_activity_view import AgentActivityView
from .artifacts_hub import ArtifactsHub
from .recent_conversations import RecentConversations
from .preview_panel import PreviewPanel
from .browser_control import BrowserControl
from .file_preview import FilePreview
from .fullscreen_preview import FullscreenPreview
from .routines_view import RoutinesView
from .agents_page import AgentsPage
from .settings_page import SettingsPage
from .sidebar import Sidebar
from .desktop_windows import DesktopWindows

__all__ = [
    "ChatView",
    "NetworkView",
    "AgentActivityView",
    "ArtifactsHub",
    "RecentConversations",
    "PreviewPanel",
    "BrowserControl",
    "FilePreview",
    "FullscreenPreview",
    "RoutinesView",
    "AgentsPage",
    "SettingsPage",
    "Sidebar",
    "DesktopWindows",
]
