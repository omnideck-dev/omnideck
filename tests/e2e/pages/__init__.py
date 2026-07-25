"""Page Object Models for e2e tests.

Naming follows docs/ui_architecture.md: the three main views are
Chat, Network View, and Agent Activity View. Shared sub-panels
(PreviewTabGroup, FilePreview, FullscreenPreview) live here too. FullscreenPreview
represents the generic maximized-view presentation.
"""

from .chat_view import ChatView
from .network_view import NetworkView
from .agent_activity_view import AgentActivityView
from .artifacts_hub import ArtifactsHub
from .recent_conversations import RecentConversations
from .preview_panel import PreviewTabGroup
from .browser_control import BrowserControl
from .file_preview import FilePreview
from .fullscreen_preview import FullscreenPreview
from .routines_view import RoutinesView
from .agents_page import AgentsPage
from .settings_page import SettingsPage
from .sidebar import Sidebar
from .desktop_layout import DesktopLayout

__all__ = [
    "ChatView",
    "NetworkView",
    "AgentActivityView",
    "ArtifactsHub",
    "RecentConversations",
    "PreviewTabGroup",
    "BrowserControl",
    "FilePreview",
    "FullscreenPreview",
    "RoutinesView",
    "AgentsPage",
    "SettingsPage",
    "Sidebar",
    "DesktopLayout",
]
