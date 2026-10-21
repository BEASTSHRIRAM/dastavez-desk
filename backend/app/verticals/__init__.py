from app.verticals.accounting import ACCOUNTING
from app.verticals.base import WorkspaceConfig
from app.verticals.government import GOVERNMENT
from app.verticals.legal import LEGAL
from app.verticals.property import PROPERTY
from app.verticals.travel import TRAVEL

WORKSPACES: dict[str, WorkspaceConfig] = {w.id: w for w in (LEGAL, PROPERTY, GOVERNMENT, TRAVEL, ACCOUNTING)}


def get_workspace(workspace_id: str) -> WorkspaceConfig:
    try:
        return WORKSPACES[workspace_id]
    except KeyError:
        raise KeyError(f"Unknown workspace: {workspace_id}") from None
