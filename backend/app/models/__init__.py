from app.models.approval import (
    ApprovalFlow,
    ApprovalFlowNode,
    ApprovalTask,
    approval_flow_depts,
)
from app.models.asset import (
    Asset,
    AssetAttachment,
    AssetCategory,
    AssetCategoryField,
    AssetHistory,
    AssetModel,
    AssetRequest,
    AssetRequestApproval,
    AssetRequestSetting,
)
from app.models.asset_ops import (
    AssetScrap,
    AssetTransfer,
    InventoryAdjustment,
    InventoryItem,
    InventorySurplus,
    InventoryTask,
)
from app.models.audit import AuditLog
from app.models.base import Base
from app.models.contract import AssetContract, AssetContractAsset
from app.models.dingtalk import DingTalkApproval, DingTalkConfig, DingTalkSyncLog
from app.models.domain import AssetDomain
from app.models.inbound import (
    AssetCodeSequence,
    AssetInbound,
    AssetInboundCode,
    AssetInboundItem,
)
from app.models.ldap import LdapConfig, LdapSyncLog
from app.models.maintenance import AssetMaintenance, AssetMaintenanceRecord
from app.models.rbac import (
    Dept,
    Menu,
    OrgSyncPolicy,
    Role,
    RoleDataPermission,
    RoleDomain,
    RoleFieldPermission,
    User,
    role_depts,
    role_menus,
    user_roles,
)
from app.models.settings import Announcement, SysSetting

__all__ = [
    "Announcement",
    "ApprovalFlow",
    "ApprovalFlowNode",
    "ApprovalTask",
    "approval_flow_depts",
    "Asset",
    "AssetAttachment",
    "AssetCategory",
    "AssetCategoryField",
    "AssetCodeSequence",
    "AssetContract",
    "AssetContractAsset",
    "AssetDomain",
    "AssetHistory",
    "AssetInbound",
    "AssetInboundCode",
    "AssetInboundItem",
    "AssetMaintenance",
    "AssetMaintenanceRecord",
    "AssetModel",
    "AssetRequest",
    "AssetRequestApproval",
    "AssetRequestSetting",
    "AssetScrap",
    "AssetTransfer",
    "AuditLog",
    "Base",
    "Dept",
    "DingTalkApproval",
    "DingTalkConfig",
    "DingTalkSyncLog",
    "InventoryAdjustment",
    "InventoryItem",
    "InventorySurplus",
    "InventoryTask",
    "LdapConfig",
    "LdapSyncLog",
    "Menu",
    "OrgSyncPolicy",
    "Role",
    "RoleDataPermission",
    "RoleDomain",
    "RoleFieldPermission",
    "SysSetting",
    "User",
    "role_depts",
    "role_menus",
    "user_roles",
]
