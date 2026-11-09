import asyncio
import logging
from decimal import Decimal

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.assets import AssetDomain, CategoryType, FieldType
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.permissions import SUPER_ADMIN_ROLE, DataScope, DomainScope
from app.core.security import hash_password
from app.models import (
    AssetCategory,
    AssetCategoryField,
    AssetDomain as AssetDomainEntity,
    AssetModel,
    AssetRequestSetting,
    Dept,
    Menu,
    Role,
    User,
    role_menus,
    user_roles,
)
from app.repositories.user_repo import UserRepository

logger = logging.getLogger("itam.seed")

DEPARTMENTS = [
    {"name": "总公司", "code": "HQ", "sort": 10},
    {"name": "信息技术部", "code": "IT", "parent": "HQ", "sort": 20},
    {"name": "财务部", "code": "FIN", "parent": "HQ", "sort": 30},
    {"name": "人力资源部", "code": "HR", "parent": "HQ", "sort": 40},
    {"name": "运维组", "code": "OPS", "parent": "IT", "sort": 10},
]

ROLES = [
    {
        "code": SUPER_ADMIN_ROLE,
        "name": "超级管理员",
        "description": "系统全量权限，包含所有数据与字段",
        "data_scope": DataScope.ALL,
        "sort": 10,
        "is_system": True,
    },
    {
        "code": "ASSET_ADMIN",
        "name": "资产管理员",
        "description": "资产台账与资产业务管理",
        "data_scope": DataScope.ALL,
        "sort": 20,
        "is_system": True,
    },
    {
        "code": "DEPT_ADMIN",
        "name": "部门管理员",
        "description": "管理本部门及下级部门资产",
        "data_scope": DataScope.DEPT_AND_CHILD,
        "sort": 30,
        "is_system": True,
    },
    {
        "code": "EMPLOYEE",
        "name": "普通员工",
        "description": "查看本人名下资产与自助申请",
        "data_scope": DataScope.SELF,
        "sort": 40,
        "is_system": True,
    },
    {
        "code": "AUDITOR",
        "name": "审计员",
        "description": "全局只读与审计日志查看",
        "data_scope": DataScope.ALL,
        "sort": 50,
        "is_system": True,
    },
    {
        "code": "REPAIRER",
        "name": "维修人员",
        "description": "处理指派给自己的维修工单",
        "data_scope": DataScope.SELF,
        "sort": 60,
        "is_system": True,
    },
]

MENUS = [
    {
        "key": "dashboard",
        "name": "工作台",
        "type": "MENU",
        "path": "/dashboard",
        "component": "dashboard/index",
        "icon": "Odometer",
        "sort": 10,
        "permission_code": "dashboard:view",
        "visible": True,
    },
    {
        "key": "work",
        "name": "我的工作",
        "type": "DIR",
        "path": "/work",
        "icon": "User",
        "sort": 20,
        "permission_code": "asset:work:view",
        "visible": True,
    },
    {
        "key": "assets",
        "name": "资产生命周期",
        "type": "DIR",
        "path": "/assets",
        "icon": "Box",
        "sort": 30,
        "permission_code": "asset:view",
        "visible": True,
    },
    {
        "key": "base_data",
        "name": "基础数据",
        "type": "DIR",
        "path": "/base-data",
        "icon": "Grid",
        "sort": 40,
        "permission_code": "asset:base:view",
        "visible": True,
    },
    {
        "key": "ops_contracts",
        "name": "运维与合同",
        "type": "DIR",
        "path": "/operations",
        "icon": "Tools",
        "sort": 50,
        "permission_code": "asset:ops:view",
        "visible": True,
    },
    {
        "key": "analysis",
        "name": "分析报表",
        "type": "DIR",
        "path": "/analysis",
        "icon": "DataAnalysis",
        "sort": 60,
        "permission_code": "asset:analysis:view",
        "visible": True,
    },
    {
        "key": "asset_categories",
        "parent": "base_data",
        "name": "资产分类",
        "type": "MENU",
        "path": "/assets/categories",
        "component": "assets/categories/index",
        "icon": "Files",
        "sort": 10,
        "permission_code": "asset:category:view",
        "visible": True,
    },
    {
        "key": "category_create",
        "parent": "asset_categories",
        "name": "新增分类",
        "type": "BUTTON",
        "sort": 10,
        "permission_code": "asset:category:create",
        "visible": False,
    },
    {
        "key": "category_update",
        "parent": "asset_categories",
        "name": "编辑分类",
        "type": "BUTTON",
        "sort": 20,
        "permission_code": "asset:category:update",
        "visible": False,
    },
    {
        "key": "category_delete",
        "parent": "asset_categories",
        "name": "删除分类",
        "type": "BUTTON",
        "sort": 30,
        "permission_code": "asset:category:delete",
        "visible": False,
    },
    {
        "key": "model_create",
        "parent": "asset_categories",
        "name": "新增型号",
        "type": "BUTTON",
        "sort": 40,
        "permission_code": "asset:model:create",
        "visible": False,
    },
    {
        "key": "model_update",
        "parent": "asset_categories",
        "name": "编辑型号",
        "type": "BUTTON",
        "sort": 50,
        "permission_code": "asset:model:update",
        "visible": False,
    },
    {
        "key": "model_delete",
        "parent": "asset_categories",
        "name": "删除型号",
        "type": "BUTTON",
        "sort": 60,
        "permission_code": "asset:model:delete",
        "visible": False,
    },
    {
        "key": "asset_ledger",
        "parent": "assets",
        "name": "资产台账",
        "type": "MENU",
        "path": "/assets/ledger",
        "component": "assets/ledger/index",
        "icon": "Monitor",
        "sort": 10,
        "permission_code": "asset:ledger:view",
        "visible": True,
    },
    {
        "key": "ledger_create",
        "parent": "asset_ledger",
        "name": "新增资产",
        "type": "BUTTON",
        "sort": 10,
        "permission_code": "asset:ledger:create",
        "visible": False,
    },
    {
        "key": "ledger_update",
        "parent": "asset_ledger",
        "name": "编辑资产",
        "type": "BUTTON",
        "sort": 20,
        "permission_code": "asset:ledger:update",
        "visible": False,
    },
    {
        "key": "ledger_delete",
        "parent": "asset_ledger",
        "name": "删除资产",
        "type": "BUTTON",
        "sort": 30,
        "permission_code": "asset:ledger:delete",
        "visible": False,
    },
    {
        "key": "asset_inbound",
        "parent": "assets",
        "name": "资产入库",
        "type": "MENU",
        "path": "/assets/inbounds",
        "component": "assets/inbounds/index",
        "icon": "Box",
        "sort": 20,
        "permission_code": "asset:inbound:view",
        "visible": True,
    },
    {
        "key": "asset_inbound_create",
        "parent": "asset_inbound",
        "name": "创建入库单",
        "type": "BUTTON",
        "sort": 10,
        "permission_code": "asset:inbound:create",
        "visible": False,
    },
    {
        "key": "asset_inbound_confirm",
        "parent": "asset_inbound",
        "name": "确认入库",
        "type": "BUTTON",
        "sort": 20,
        "permission_code": "asset:inbound:confirm",
        "visible": False,
    },
    {
        "key": "asset_inbound_cancel",
        "parent": "asset_inbound",
        "name": "取消入库单",
        "type": "BUTTON",
        "sort": 30,
        "permission_code": "asset:inbound:cancel",
        "visible": False,
    },
    {
        "key": "asset_inbound_update",
        "parent": "asset_inbound",
        "name": "编辑入库单",
        "type": "BUTTON",
        "sort": 40,
        "permission_code": "asset:inbound:update",
        "visible": False,
    },
    {
        "key": "asset_inbound_delete",
        "parent": "asset_inbound",
        "name": "删除入库单",
        "type": "BUTTON",
        "sort": 50,
        "permission_code": "asset:inbound:delete",
        "visible": False,
    },
    {
        "key": "asset_outbound",
        "parent": "assets",
        "name": "资产领用确认",
        "type": "MENU",
        "path": "/assets/outbound",
        "component": "assets/review/index",
        "icon": "Box",
        "sort": 30,
        "permission_code": "asset:outbound:view",
        "visible": True,
    },
    {
        "key": "asset_return_review",
        "parent": "assets",
        "name": "资产归还确认",
        "type": "MENU",
        "path": "/assets/returns",
        "component": "assets/review/index",
        "icon": "Connection",
        "sort": 40,
        "permission_code": "asset:return:confirm:view",
        "visible": True,
    },
    {
        "key": "asset_stock",
        "parent": "base_data",
        "name": "库存管理",
        "type": "MENU",
        "path": "/assets/stock",
        "component": "assets/stock/index",
        "icon": "Grid",
        "sort": 20,
        "permission_code": "asset:stock:view",
        "visible": True,
    },
    {
        "key": "asset_maintenance",
        "parent": "ops_contracts",
        "name": "维修管理",
        "type": "MENU",
        "path": "/assets/maintenance",
        "component": "assets/maintenance/index",
        "icon": "Tools",
        "sort": 10,
        "permission_code": "asset:maintenance:view",
        "visible": True,
    },
    {
        "key": "maintenance_create",
        "parent": "asset_maintenance",
        "name": "提交报修",
        "type": "BUTTON",
        "sort": 10,
        "permission_code": "asset:maintenance:create",
        "visible": False,
    },
    {
        "key": "maintenance_approve",
        "parent": "asset_maintenance",
        "name": "审批维修",
        "type": "BUTTON",
        "sort": 20,
        "permission_code": "asset:maintenance:approve",
        "visible": False,
    },
    {
        "key": "maintenance_repair",
        "parent": "asset_maintenance",
        "name": "处理维修",
        "type": "BUTTON",
        "sort": 30,
        "permission_code": "asset:maintenance:repair",
        "visible": False,
    },
    {
        "key": "maintenance_accept",
        "parent": "asset_maintenance",
        "name": "验收维修",
        "type": "BUTTON",
        "sort": 40,
        "permission_code": "asset:maintenance:accept",
        "visible": False,
    },
    {
        "key": "maintenance_cancel",
        "parent": "asset_maintenance",
        "name": "取消维修",
        "type": "BUTTON",
        "sort": 50,
        "permission_code": "asset:maintenance:cancel",
        "visible": False,
    },
    {
        "key": "asset_contract",
        "parent": "ops_contracts",
        "name": "合同管理",
        "type": "MENU",
        "path": "/assets/contracts",
        "component": "assets/contracts/index",
        "icon": "Memo",
        "sort": 20,
        "permission_code": "asset:contract:view",
        "visible": True,
    },
    {
        "key": "contract_create",
        "parent": "asset_contract",
        "name": "新建合同",
        "type": "BUTTON",
        "sort": 10,
        "permission_code": "asset:contract:create",
        "visible": False,
    },
    {
        "key": "contract_edit",
        "parent": "asset_contract",
        "name": "编辑合同",
        "type": "BUTTON",
        "sort": 20,
        "permission_code": "asset:contract:edit",
        "visible": False,
    },
    {
        "key": "contract_terminate",
        "parent": "asset_contract",
        "name": "终止合同",
        "type": "BUTTON",
        "sort": 30,
        "permission_code": "asset:contract:terminate",
        "visible": False,
    },
    {
        "key": "asset_reports",
        "parent": "analysis",
        "name": "报表分析",
        "type": "MENU",
        "path": "/assets/reports",
        "component": "assets/reports/index",
        "icon": "DataAnalysis",
        "sort": 10,
        "permission_code": "asset:report:view",
        "visible": True,
    },
    {
        "key": "report_export",
        "parent": "asset_reports",
        "name": "导出报表",
        "type": "BUTTON",
        "sort": 10,
        "permission_code": "asset:report:export",
        "visible": False,
    },
    {
        "key": "asset_reminders",
        "parent": "ops_contracts",
        "name": "到期提醒",
        "type": "MENU",
        "path": "/assets/reminders",
        "component": "assets/reminders/index",
        "icon": "Bell",
        "sort": 30,
        "permission_code": "asset:reminder:view",
        "visible": True,
    },
    {
        "key": "reminder_scan",
        "parent": "asset_reminders",
        "name": "执行提醒扫描",
        "type": "BUTTON",
        "sort": 10,
        "permission_code": "asset:reminder:scan",
        "visible": False,
    },
    {
        "key": "asset_todos",
        "parent": "work",
        "name": "我的待办",
        "type": "MENU",
        "path": "/todos",
        "component": "todos/index",
        "icon": "Finished",
        "sort": 5,
        "permission_code": "asset:todo:view",
        "visible": True,
    },
    {
        "key": "asset_requisition",
        "parent": "work",
        "name": "我的申请",
        "type": "MENU",
        "path": "/assets/requisitions",
        "component": "assets/requisitions/index",
        "icon": "Tickets",
        "sort": 20,
        "permission_code": "asset:requisition:view",
        "visible": True,
    },
    {
        "key": "requisition_create",
        "parent": "asset_requisition",
        "name": "发起领用/借用",
        "type": "BUTTON",
        "sort": 10,
        "permission_code": "asset:requisition:create",
        "visible": False,
    },
    {
        "key": "requisition_cancel",
        "parent": "asset_requisition",
        "name": "撤销申请",
        "type": "BUTTON",
        "sort": 20,
        "permission_code": "asset:requisition:cancel",
        "visible": False,
    },
    {
        "key": "asset_mine",
        "parent": "work",
        "name": "我的资产",
        "type": "MENU",
        "path": "/assets/mine",
        "component": "assets/mine/index",
        "icon": "User",
        "sort": 10,
        "permission_code": "asset:mine:view",
        "visible": True,
    },
    {
        "key": "asset_return_create",
        "parent": "asset_mine",
        "name": "发起归还",
        "type": "BUTTON",
        "sort": 10,
        "permission_code": "asset:return:create",
        "visible": False,
    },
    {
        "key": "asset_review",
        "parent": "work",
        "name": "业务审批",
        "type": "MENU",
        "path": "/assets/review",
        "component": "assets/review/index",
        "icon": "Tools",
        "sort": 30,
        "permission_code": "asset:request:review",
        "visible": True,
    },
    {
        "key": "asset_request_approve",
        "parent": "asset_review",
        "name": "审批业务申请",
        "type": "BUTTON",
        "sort": 10,
        "permission_code": "asset:request:approve",
        "visible": False,
    },
    {
        "key": "asset_request_outbound",
        "parent": "asset_review",
        "name": "确认出库",
        "type": "BUTTON",
        "sort": 20,
        "permission_code": "asset:request:outbound",
        "visible": False,
    },
    {
        "key": "asset_return_confirm",
        "parent": "asset_review",
        "name": "确认归还",
        "type": "BUTTON",
        "sort": 30,
        "permission_code": "asset:return:confirm",
        "visible": False,
    },
    {
        "key": "asset_transfer",
        "parent": "assets",
        "name": "资产调拨",
        "type": "MENU",
        "path": "/assets/transfers",
        "component": "assets/transfers/index",
        "icon": "Connection",
        "sort": 50,
        "permission_code": "asset:transfer:view",
        "visible": True,
    },
    {
        "key": "asset_transfer_create",
        "parent": "asset_transfer",
        "name": "发起调拨",
        "type": "BUTTON",
        "sort": 10,
        "permission_code": "asset:transfer:create",
        "visible": False,
    },
    {
        "key": "asset_transfer_approve",
        "parent": "asset_transfer",
        "name": "审批调拨",
        "type": "BUTTON",
        "sort": 20,
        "permission_code": "asset:transfer:approve",
        "visible": False,
    },
    {
        "key": "asset_transfer_confirm",
        "parent": "asset_transfer",
        "name": "确认调拨",
        "type": "BUTTON",
        "sort": 30,
        "permission_code": "asset:transfer:confirm",
        "visible": False,
    },
    {
        "key": "asset_transfer_cancel",
        "parent": "asset_transfer",
        "name": "撤销调拨",
        "type": "BUTTON",
        "sort": 40,
        "permission_code": "asset:transfer:cancel",
        "visible": False,
    },
    {
        "key": "asset_scrap",
        "parent": "assets",
        "name": "资产报废",
        "type": "MENU",
        "path": "/assets/scraps",
        "component": "assets/scraps/index",
        "icon": "Document",
        "sort": 70,
        "permission_code": "asset:scrap:view",
        "visible": True,
    },
    {
        "key": "asset_scrap_create",
        "parent": "asset_scrap",
        "name": "发起报废",
        "type": "BUTTON",
        "sort": 10,
        "permission_code": "asset:scrap:create",
        "visible": False,
    },
    {
        "key": "asset_scrap_approve",
        "parent": "asset_scrap",
        "name": "审批报废",
        "type": "BUTTON",
        "sort": 20,
        "permission_code": "asset:scrap:approve",
        "visible": False,
    },
    {
        "key": "asset_scrap_confirm",
        "parent": "asset_scrap",
        "name": "确认报废",
        "type": "BUTTON",
        "sort": 30,
        "permission_code": "asset:scrap:confirm",
        "visible": False,
    },
    {
        "key": "asset_scrap_cancel",
        "parent": "asset_scrap",
        "name": "撤销报废",
        "type": "BUTTON",
        "sort": 40,
        "permission_code": "asset:scrap:cancel",
        "visible": False,
    },
    {
        "key": "asset_inventory",
        "parent": "assets",
        "name": "资产盘点",
        "type": "MENU",
        "path": "/assets/inventory",
        "component": "assets/inventory/index",
        "icon": "Files",
        "sort": 60,
        "permission_code": "asset:inventory:view",
        "visible": True,
    },
    {
        "key": "asset_inventory_create",
        "parent": "asset_inventory",
        "name": "创建盘点任务",
        "type": "BUTTON",
        "sort": 10,
        "permission_code": "asset:inventory:create",
        "visible": False,
    },
    {
        "key": "asset_inventory_manage",
        "parent": "asset_inventory",
        "name": "执行盘点",
        "type": "BUTTON",
        "sort": 20,
        "permission_code": "asset:inventory:manage",
        "visible": False,
    },
    {
        "key": "asset_inventory_approve",
        "parent": "asset_inventory",
        "name": "盘点盈亏审批",
        "type": "BUTTON",
        "sort": 30,
        "permission_code": "asset:inventory:approve",
        "visible": False,
    },
    {
        "key": "system",
        "name": "系统管理",
        "type": "DIR",
        "path": "/system",
        "icon": "Setting",
        "sort": 70,
        "permission_code": "system:view",
        "visible": True,
    },
    {
        "key": "org",
        "parent": "system",
        "name": "组织架构",
        "type": "MENU",
        "path": "/system/org",
        "component": "system/org/index",
        "icon": "OfficeBuilding",
        "sort": 10,
        "permission_code": "system:org:view",
        "visible": True,
    },
    {
        "key": "dept_create",
        "parent": "org",
        "name": "新增部门",
        "type": "BUTTON",
        "sort": 10,
        "permission_code": "system:dept:create",
        "visible": False,
    },
    {
        "key": "dept_update",
        "parent": "org",
        "name": "编辑部门",
        "type": "BUTTON",
        "sort": 20,
        "permission_code": "system:dept:update",
        "visible": False,
    },
    {
        "key": "dept_delete",
        "parent": "org",
        "name": "删除部门",
        "type": "BUTTON",
        "sort": 30,
        "permission_code": "system:dept:delete",
        "visible": False,
    },
    {
        "key": "user_create",
        "parent": "org",
        "name": "新增用户",
        "type": "BUTTON",
        "sort": 40,
        "permission_code": "system:user:create",
        "visible": False,
    },
    {
        "key": "user_update",
        "parent": "org",
        "name": "编辑用户",
        "type": "BUTTON",
        "sort": 50,
        "permission_code": "system:user:update",
        "visible": False,
    },
    {
        "key": "user_delete",
        "parent": "org",
        "name": "删除用户",
        "type": "BUTTON",
        "sort": 60,
        "permission_code": "system:user:delete",
        "visible": False,
    },
    {
        "key": "user_reset",
        "parent": "org",
        "name": "重置密码",
        "type": "BUTTON",
        "sort": 70,
        "permission_code": "system:user:reset-password",
        "visible": False,
    },
    {
        "key": "roles",
        "parent": "system",
        "name": "角色权限",
        "type": "MENU",
        "path": "/system/roles",
        "component": "system/roles/index",
        "icon": "Key",
        "sort": 20,
        "permission_code": "system:role:view",
        "visible": True,
    },
    {
        "key": "role_create",
        "parent": "roles",
        "name": "新增角色",
        "type": "BUTTON",
        "sort": 10,
        "permission_code": "system:role:create",
        "visible": False,
    },
    {
        "key": "role_update",
        "parent": "roles",
        "name": "编辑角色",
        "type": "BUTTON",
        "sort": 20,
        "permission_code": "system:role:update",
        "visible": False,
    },
    {
        "key": "role_delete",
        "parent": "roles",
        "name": "删除角色",
        "type": "BUTTON",
        "sort": 30,
        "permission_code": "system:role:delete",
        "visible": False,
    },
    {
        "key": "role_assign_menu",
        "parent": "roles",
        "name": "分配菜单",
        "type": "BUTTON",
        "sort": 40,
        "permission_code": "system:role:assign-menu",
        "visible": False,
    },
    {
        "key": "role_assign_data",
        "parent": "roles",
        "name": "分配数据权限",
        "type": "BUTTON",
        "sort": 50,
        "permission_code": "system:role:assign-data",
        "visible": False,
    },
    {
        "key": "role_assign_field",
        "parent": "roles",
        "name": "分配字段权限",
        "type": "BUTTON",
        "sort": 60,
        "permission_code": "system:role:assign-field",
        "visible": False,
    },
    {
        "key": "role_assign_user",
        "parent": "roles",
        "name": "分配用户",
        "type": "BUTTON",
        "sort": 70,
        "permission_code": "system:role:assign-user",
        "visible": False,
    },
    {
        "key": "audit",
        "parent": "system",
        "name": "审计日志",
        "type": "MENU",
        "path": "/system/audit",
        "component": "system/audit/index",
        "icon": "Document",
        "sort": 30,
        "permission_code": "system:audit:view",
        "visible": True,
    },
    {
        "key": "ldap_sync",
        "parent": "system",
        "name": "域控同步",
        "type": "MENU",
        "path": "/system/ldap",
        "component": "system/ldap/index",
        "icon": "Connection",
        "sort": 40,
        "permission_code": "system:ldap:view",
        "visible": True,
    },
    {
        "key": "ldap_update",
        "parent": "ldap_sync",
        "name": "编辑域控配置",
        "type": "BUTTON",
        "sort": 10,
        "permission_code": "system:ldap:update",
        "visible": False,
    },
    {
        "key": "ldap_sync_run",
        "parent": "ldap_sync",
        "name": "手动同步",
        "type": "BUTTON",
        "sort": 20,
        "permission_code": "system:ldap:sync",
        "visible": False,
    },
    {
        "key": "dingtalk_sync",
        "parent": "system",
        "name": "钉钉同步",
        "type": "MENU",
        "path": "/system/dingtalk",
        "component": "system/dingtalk/index",
        "icon": "ChatDotRound",
        "sort": 50,
        "permission_code": "system:dingtalk:view",
        "visible": True,
    },
    {
        "key": "dingtalk_update",
        "parent": "dingtalk_sync",
        "name": "编辑钉钉配置",
        "type": "BUTTON",
        "sort": 10,
        "permission_code": "system:dingtalk:update",
        "visible": False,
    },
    {
        "key": "dingtalk_sync_run",
        "parent": "dingtalk_sync",
        "name": "手动同步",
        "type": "BUTTON",
        "sort": 20,
        "permission_code": "system:dingtalk:sync",
        "visible": False,
    },
    {
        "key": "org_sync_policy",
        "parent": "system",
        "name": "组织同步策略",
        "type": "MENU",
        "path": "/system/org-sync-policy",
        "component": "system/org-sync-policy/index",
        "icon": "SetUp",
        "sort": 55,
        "permission_code": "system:org-sync-policy:view",
        "visible": True,
    },
    {
        "key": "org_sync_policy_update",
        "parent": "org_sync_policy",
        "name": "编辑同步策略",
        "type": "BUTTON",
        "sort": 10,
        "permission_code": "system:org-sync-policy:update",
        "visible": False,
    },
    {
        "key": "approval_flow_config",
        "parent": "system",
        "name": "审批流程配置",
        "type": "MENU",
        "path": "/system/approval-flows",
        "component": "system/approval-flows/index",
        "icon": "Share",
        "sort": 25,
        "permission_code": "asset:request:flow:view",
        "visible": True,
    },
    {
        "key": "approval_flow_manage",
        "parent": "approval_flow_config",
        "name": "维护审批流程",
        "type": "BUTTON",
        "sort": 10,
        "permission_code": "asset:request:flow:manage",
        "visible": False,
    },
]


CATEGORY_TREE = [
    {
        "key": "computer",
        "name": "计算机设备",
        "code": "HW-COMPUTER",
        "category_type": CategoryType.HARDWARE,
        "sort": 10,
        "remark": "服务器、台式机、笔记本等计算终端",
        "children": [
            {"key": "desktop", "name": "台式电脑", "code": "HW-DESKTOP", "sort": 10},
            {"key": "laptop", "name": "笔记本电脑", "code": "HW-LAPTOP", "sort": 20},
            {"key": "server", "name": "服务器", "code": "HW-SERVER", "sort": 30},
        ],
    },
    {
        "key": "network",
        "name": "网络设备",
        "code": "HW-NETWORK",
        "category_type": CategoryType.HARDWARE,
        "sort": 20,
        "children": [
            {"key": "switch", "name": "交换机", "code": "HW-SWITCH", "sort": 10},
            {"key": "router", "name": "路由器", "code": "HW-ROUTER", "sort": 20},
            {"key": "firewall", "name": "防火墙", "code": "HW-FIREWALL", "sort": 30},
        ],
    },
    {
        "key": "peripheral",
        "name": "外设与配件",
        "code": "HW-PERIPHERAL",
        "category_type": CategoryType.ACCESSORY,
        "sort": 30,
        "children": [
            {"key": "monitor", "name": "显示器", "code": "HW-MONITOR", "sort": 10},
            {"key": "printer", "name": "打印机", "code": "HW-PRINTER", "sort": 20},
            {"key": "dock", "name": "扩展坞", "code": "HW-DOCK", "sort": 30},
        ],
    },
    {
        "key": "software",
        "name": "软件资产",
        "code": "SW-LICENSE",
        "category_type": CategoryType.SOFTWARE,
        "sort": 40,
        "children": [
            {"key": "office", "name": "办公软件", "code": "SW-OFFICE", "sort": 10},
            {"key": "security", "name": "安全软件", "code": "SW-SECURITY", "sort": 20},
        ],
    },
    {
        "key": "consumable",
        "name": "办公耗材",
        "code": "CS-MATERIAL",
        "category_type": CategoryType.CONSUMABLE,
        "sort": 50,
        "children": [
            {"key": "toner", "name": "打印耗材", "code": "CS-TONER", "sort": 10},
            {"key": "cable", "name": "线缆配件", "code": "CS-CABLE", "sort": 20},
        ],
    },
    {
        "key": "admin_asset",
        "name": "行政资产",
        "code": "ADM-ASSET",
        "category_type": CategoryType.HARDWARE,
        "asset_domain": AssetDomain.ADMIN,
        "sort": 90,
        "remark": "办公家具、电器等非 IT 类行政资产",
        "children": [
            {"key": "admin_furniture", "name": "办公家具", "code": "ADM-FURNITURE", "sort": 10},
            {"key": "admin_appliance", "name": "办公电器", "code": "ADM-APPLIANCE", "sort": 20},
            {"key": "admin_other", "name": "其他行政资产", "code": "ADM-OTHER", "sort": 30},
        ],
    },
]

CATEGORY_FIELDS = {
    "HW-DESKTOP": [
        {"name": "处理器", "field_key": "cpu", "field_type": FieldType.TEXT, "sort": 10},
        {"name": "内存", "field_key": "memory", "field_type": FieldType.TEXT, "sort": 20},
        {"name": "硬盘", "field_key": "disk", "field_type": FieldType.TEXT, "sort": 30},
        {
            "name": "操作系统",
            "field_key": "os",
            "field_type": FieldType.SELECT,
            "options": ["Windows 11", "Windows 10", "Ubuntu 22.04"],
            "sort": 40,
        },
    ],
    "HW-LAPTOP": [
        {"name": "处理器", "field_key": "cpu", "field_type": FieldType.TEXT, "sort": 10},
        {"name": "内存", "field_key": "memory", "field_type": FieldType.TEXT, "sort": 20},
        {"name": "硬盘", "field_key": "disk", "field_type": FieldType.TEXT, "sort": 30},
        {
            "name": "操作系统",
            "field_key": "os",
            "field_type": FieldType.SELECT,
            "options": ["Windows 11", "Windows 10", "macOS"],
            "sort": 40,
        },
    ],
    "HW-SERVER": [
        {
            "name": "CPU 核数",
            "field_key": "cpu_cores",
            "field_type": FieldType.NUMBER,
            "required": True,
            "sort": 10,
        },
        {"name": "内存", "field_key": "memory", "field_type": FieldType.TEXT, "sort": 20},
        {"name": "存储", "field_key": "disk", "field_type": FieldType.TEXT, "sort": 30},
    ],
    "HW-MONITOR": [
        {"name": "屏幕尺寸", "field_key": "screen_size", "field_type": FieldType.TEXT, "sort": 10},
        {
            "name": "面板类型",
            "field_key": "panel",
            "field_type": FieldType.SELECT,
            "options": ["IPS", "VA", "OLED"],
            "sort": 20,
        },
    ],
    "SW-OFFICE": [
        {
            "name": "授权类型",
            "field_key": "license_type",
            "field_type": FieldType.SELECT,
            "options": ["订阅", "永久授权", "OEM"],
            "required": True,
            "sort": 10,
        },
        {"name": "授权数量", "field_key": "seats", "field_type": FieldType.NUMBER, "sort": 20},
    ],
    "SW-SECURITY": [
        {
            "name": "授权类型",
            "field_key": "license_type",
            "field_type": FieldType.SELECT,
            "options": ["订阅", "永久授权"],
            "required": True,
            "sort": 10,
        },
        {"name": "授权数量", "field_key": "seats", "field_type": FieldType.NUMBER, "sort": 20},
    ],
}

MODEL_SEEDS = [
    {
        "category": "HW-DESKTOP",
        "name": "OptiPlex 7010",
        "code": "DELL-OPTIPLEX-7010",
        "brand": "Dell",
        "spec": "i5-13500 / 16GB / 512GB SSD",
        "depreciation_months": 60,
    },
    {
        "category": "HW-LAPTOP",
        "name": "ThinkPad X1 Carbon Gen 11",
        "code": "LENOVO-X1-CARBON-G11",
        "brand": "Lenovo",
        "spec": "i7-1365U / 32GB / 1TB SSD / 14英寸",
        "depreciation_months": 48,
    },
    {
        "category": "HW-SERVER",
        "name": "ProLiant DL380 Gen11",
        "code": "HPE-DL380-G11",
        "brand": "HPE",
        "spec": "2×Xeon Silver 4410Y / 128GB / 4×1.92TB SSD",
        "depreciation_months": 72,
    },
    {
        "category": "HW-SWITCH",
        "name": "S5735-L24T4S-A1",
        "code": "HUAWEI-S5735",
        "brand": "Huawei",
        "spec": "24×GE / 4×GE SFP",
        "depreciation_months": 60,
    },
    {
        "category": "HW-MONITOR",
        "name": "UltraSharp U2723QE",
        "code": "DELL-U2723QE",
        "brand": "Dell",
        "spec": "27英寸 4K IPS Black / USB-C 90W",
        "depreciation_months": 48,
    },
    {
        "category": "SW-OFFICE",
        "name": "Microsoft 365 E3",
        "code": "MS365-E3",
        "brand": "Microsoft",
        "spec": "企业版年度订阅 / 每用户",
        "unit": "套",
        "residual_rate": 0,
    },
    {
        "category": "SW-SECURITY",
        "name": "终端安全防护 EDR",
        "code": "EDR-AV",
        "brand": "奇安信",
        "spec": "终端检测与响应 / 每终端年度订阅",
        "unit": "套",
        "residual_rate": 0,
    },
    {
        "category": "CS-TONER",
        "name": "HP 88A 硒鼓",
        "code": "HP-CF248A",
        "brand": "HP",
        "spec": "黑色 / 适配 LaserJet P1007/P1008",
        "unit": "支",
        "depreciation_months": 12,
        "residual_rate": 0,
    },
]

async def _ensure_departments(session: AsyncSession) -> dict[str, Dept]:
    dept_map: dict[str, Dept] = {}
    for item in DEPARTMENTS:
        dept = (
            await session.execute(select(Dept).where(Dept.code == item["code"]))
        ).scalar_one_or_none()
        parent = dept_map.get(item.get("parent", ""))
        if dept is None:
            dept = Dept(
                name=item["name"],
                code=item["code"],
                parent_id=parent.id if parent else None,
                sort=item["sort"],
                status=1,
            )
            session.add(dept)
            await session.flush()
        if not dept.path:
            dept.path = f"{parent.path if parent else '/'}{dept.id}/"
            dept.level = (parent.level + 1) if parent else 1
        dept_map[item["code"]] = dept
    return dept_map


async def _ensure_domains(session: AsyncSession) -> None:
    for code, name, sort in (("IT", "IT 资产", 10), ("ADMIN", "行政资产", 20)):
        domain = (
            await session.execute(
                select(AssetDomainEntity).where(AssetDomainEntity.code == code)
            )
        ).scalar_one_or_none()
        if domain is None:
            session.add(
                AssetDomainEntity(code=code, name=name, sort=sort, is_builtin=True)
            )
    await session.flush()


async def _ensure_roles(session: AsyncSession) -> tuple[dict[str, Role], set[int]]:
    role_map: dict[str, Role] = {}
    created_ids: set[int] = set()
    for item in ROLES:
        role = (
            await session.execute(select(Role).where(Role.code == item["code"]))
        ).scalar_one_or_none()
        if role is None:
            role = Role(
                code=item["code"],
                name=item["name"],
                description=item.get("description"),
                data_scope=item["data_scope"],
                domain_scope=DomainScope.ALL,
                sort=item.get("sort", 0),
                is_system=item.get("is_system", False),
                status=1,
            )
            session.add(role)
            await session.flush()
            created_ids.add(role.id)
        elif item.get("is_system") and not role.is_system:
            role.is_system = True
        role_map[item["code"]] = role
    return role_map, created_ids


async def _ensure_menus(session: AsyncSession) -> list[Menu]:
    menus: list[Menu] = []
    menu_by_key: dict[str, Menu] = {}
    for item in MENUS:
        parent = menu_by_key.get(item.get("parent", ""))
        menu = (
            await session.execute(
                select(Menu).where(Menu.permission_code == item["permission_code"])
            )
        ).scalar_one_or_none()
        if menu is None:
            menu = Menu(status=1)
            session.add(menu)
        menu.name = item["name"]
        menu.type = item["type"]
        menu.permission_code = item["permission_code"]
        menu.parent_id = parent.id if parent else None
        menu.path = item.get("path")
        menu.component = item.get("component")
        menu.icon = item.get("icon")
        menu.sort = item.get("sort", 0)
        menu.visible = item.get("visible", True)
        await session.flush()
        menu_by_key[item["key"]] = menu
        menus.append(menu)
    return menus


async def _ensure_categories(session: AsyncSession) -> dict[str, AssetCategory]:
    category_map: dict[str, AssetCategory] = {}

    async def ensure(item: dict, parent: AssetCategory | None) -> None:
        expected_parent_id = parent.id if parent else None
        category = (
            await session.execute(
                select(AssetCategory).where(AssetCategory.code == item["code"])
            )
        ).scalar_one_or_none()
        if category is None:
            category = AssetCategory(
                parent_id=expected_parent_id,
                name=item["name"],
                code=item["code"],
                category_type=item.get(
                    "category_type",
                    parent.category_type if parent else CategoryType.HARDWARE,
                ),
                asset_domain=item.get(
                    "asset_domain",
                    parent.asset_domain if parent else AssetDomain.IT,
                ),
                sort=item.get("sort", 0),
                status=1,
                remark=item.get("remark"),
            )
            session.add(category)
            await session.flush()
        elif expected_parent_id is not None and category.parent_id is None:
            category.parent_id = expected_parent_id
            await session.flush()
        if not category.path:
            category.path = f"{parent.path if parent else '/'}{category.id}/"
            category.level = (parent.level + 1) if parent else 1
            await session.flush()
        category_map[item["code"]] = category
        for child in item.get("children", []):
            await ensure(child, category)

    for node in CATEGORY_TREE:
        await ensure(node, None)
    return category_map


async def _ensure_category_fields(
    session: AsyncSession,
    category_map: dict[str, AssetCategory],
) -> int:
    created = 0
    for category_code, fields in CATEGORY_FIELDS.items():
        category = category_map.get(category_code)
        if category is None:
            continue
        existing = set(
            (
                await session.execute(
                    select(AssetCategoryField.field_key).where(
                        AssetCategoryField.category_id == category.id
                    )
                )
            )
            .scalars()
            .all()
        )
        for item in fields:
            if item["field_key"] in existing:
                continue
            session.add(
                AssetCategoryField(
                    category_id=category.id,
                    name=item["name"],
                    field_key=item["field_key"],
                    field_type=item["field_type"],
                    required=item.get("required", False),
                    options=item.get("options"),
                    sort=item.get("sort", 0),
                    status=1,
                )
            )
            created += 1
    return created


async def _ensure_models(
    session: AsyncSession,
    category_map: dict[str, AssetCategory],
) -> dict[str, AssetModel]:
    model_map: dict[str, AssetModel] = {}
    for item in MODEL_SEEDS:
        model = (
            await session.execute(select(AssetModel).where(AssetModel.code == item["code"]))
        ).scalar_one_or_none()
        category = category_map[item["category"]]
        if model is None:
            model = AssetModel(
                category_id=category.id,
                name=item["name"],
                code=item["code"],
                brand=item.get("brand"),
                spec=item.get("spec"),
                unit=item.get("unit", "台"),
                depreciation_months=item.get("depreciation_months"),
                residual_rate=Decimal(str(item.get("residual_rate", 0.05))),
                status=1,
            )
            model.category = category
            session.add(model)
            await session.flush()
        model_map[item["code"]] = model
    return model_map


async def _ensure_admin(
    session: AsyncSession,
    dept_map: dict[str, Dept],
) -> User:
    username = settings.DEFAULT_ADMIN_USERNAME.strip().lower()
    user = await UserRepository(session).get_by_username(username)
    if user is None:
        password = settings.DEFAULT_ADMIN_PASSWORD.strip()
        if not password:
            raise RuntimeError(
                "DEFAULT_ADMIN_PASSWORD 未配置：请在 .env 中设置初始管理员密码后再启动"
            )
        dept = dept_map.get("IT")
        user = User(
            username=username,
            password_hash=hash_password(password),
            real_name=settings.DEFAULT_ADMIN_NAME,
            dept_id=dept.id if dept else None,
            position="系统管理员",
            status=1,
            must_change_password=False,
        )
        session.add(user)
        await session.flush()
        logger.info("Created initial admin account: %s", username)
    else:
        logger.info("Initial admin account already exists: %s", username)
    return user


DEFAULT_ROLE_MENUS = {
    SUPER_ADMIN_ROLE: None,
    "ASSET_ADMIN": {
        "dashboard:view",
        "asset:todo:view",
        "asset:view",
        "asset:category:view",
        "asset:category:create",
        "asset:category:update",
        "asset:category:delete",
        "asset:model:create",
        "asset:model:update",
        "asset:model:delete",
        "asset:ledger:view",
        "asset:ledger:create",
        "asset:ledger:update",
        "asset:ledger:delete",
        "asset:inbound:view",
        "asset:inbound:create",
        "asset:inbound:confirm",
        "asset:inbound:cancel",
        "asset:inbound:update",
        "asset:inbound:delete",
        "asset:stock:view",
        "asset:requisition:view",
        "asset:requisition:create",
        "asset:requisition:cancel",
        "asset:mine:view",
        "asset:return:create",
        "asset:request:review",
        "asset:request:approve",
        "asset:request:flow:view",
        "asset:request:flow:manage",
        "asset:request:outbound",
        "asset:return:confirm",
        "asset:outbound:view",
        "asset:return:confirm:view",
        "asset:transfer:view",
        "asset:transfer:create",
        "asset:transfer:approve",
        "asset:transfer:confirm",
        "asset:transfer:cancel",
        "asset:scrap:view",
        "asset:scrap:create",
        "asset:scrap:approve",
        "asset:scrap:confirm",
        "asset:scrap:cancel",
        "asset:inventory:view",
        "asset:inventory:create",
        "asset:inventory:manage",
        "asset:inventory:approve",
        "asset:maintenance:view",
        "asset:maintenance:create",
        "asset:maintenance:approve",
        "asset:maintenance:repair",
        "asset:maintenance:accept",
        "asset:maintenance:cancel",
        "asset:contract:view",
        "asset:contract:create",
        "asset:contract:edit",
        "asset:contract:terminate",
        "asset:report:view",
        "asset:report:export",
        "asset:reminder:view",
        "asset:reminder:scan",
    },
    "DEPT_ADMIN": {
        "dashboard:view",
        "asset:todo:view",
        "asset:view",
        "asset:category:view",
        "asset:ledger:view",
        "asset:ledger:update",
        "asset:inbound:view",
        "asset:stock:view",
        "asset:requisition:view",
        "asset:requisition:create",
        "asset:requisition:cancel",
        "asset:mine:view",
        "asset:return:create",
        "asset:request:review",
        "asset:request:approve",
        "asset:transfer:view",
        "asset:transfer:approve",
        "asset:scrap:view",
        "asset:scrap:approve",
        "asset:inventory:view",
        "asset:inventory:manage",
        "asset:maintenance:view",
        "asset:maintenance:create",
        "asset:maintenance:approve",
        "asset:maintenance:accept",
        "asset:contract:view",
        "asset:contract:create",
        "asset:contract:edit",
        "asset:report:view",
        "asset:report:export",
        "asset:reminder:view",
    },
    "EMPLOYEE": {
        "dashboard:view",
        "asset:todo:view",
        "asset:view",
        "asset:ledger:view",
        "asset:requisition:view",
        "asset:requisition:create",
        "asset:requisition:cancel",
        "asset:mine:view",
        "asset:return:create",
        "asset:request:review",
        "asset:request:approve",
        "asset:maintenance:view",
        "asset:maintenance:create",
        "asset:reminder:view",
    },
    "AUDITOR": {
        "dashboard:view",
        "asset:todo:view",
        "asset:view",
        "asset:category:view",
        "asset:ledger:view",
        "asset:inbound:view",
        "asset:stock:view",
        "asset:transfer:view",
        "asset:scrap:view",
        "asset:inventory:view",
        "asset:maintenance:view",
        "asset:contract:view",
        "asset:report:view",
        "asset:report:export",
        "asset:reminder:view",
        "system:view",
        "system:audit:view",
    },
    "REPAIRER": {
        "dashboard:view",
        "asset:todo:view",
        "asset:view",
        "asset:ledger:view",
        "asset:maintenance:view",
        "asset:maintenance:create",
        "asset:maintenance:repair",
        "asset:reminder:view",
    },
}


async def _assign_role_menus(
    session: AsyncSession,
    role_map: dict[str, Role],
    menus: list[Menu],
    created_role_ids: set[int],
) -> None:
    existing = set(
        (await session.execute(select(role_menus.c.role_id, role_menus.c.menu_id))).all()
    )
    for role in role_map.values():
        if role.id not in created_role_ids:
            continue
        default_codes = DEFAULT_ROLE_MENUS.get(role.code)
        targets = (
            menus
            if default_codes is None
            else [menu for menu in menus if menu.permission_code in default_codes]
        )
        for menu in targets:
            if (role.id, menu.id) not in existing:
                await session.execute(
                    insert(role_menus).values(role_id=role.id, menu_id=menu.id)
                )


async def _assign_admin_role(session: AsyncSession, user: User, role: Role) -> None:
    existing = set(
        (
            await session.execute(
                select(user_roles.c.role_id).where(user_roles.c.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    if role.id not in existing:
        await session.execute(
            insert(user_roles).values(user_id=user.id, role_id=role.id)
        )


async def _ensure_request_settings(session: AsyncSession) -> None:
    request_settings = (
        await session.execute(
            select(AssetRequestSetting).order_by(AssetRequestSetting.id).limit(1)
        )
    ).scalar_one_or_none()
    if request_settings is None:
        session.add(AssetRequestSetting(dept_approval_required=True))
        await session.flush()


async def seed_initial_data(session: AsyncSession) -> None:
    dept_map: dict[str, Dept] = {}
    category_map: dict[str, AssetCategory] = {}
    fields_created = 0
    model_map: dict[str, AssetModel] = {}

    if settings.SEED_SAMPLE_DATA:
        dept_map = await _ensure_departments(session)
        category_map = await _ensure_categories(session)
        fields_created = await _ensure_category_fields(session, category_map)
        model_map = await _ensure_models(session, category_map)

    await _ensure_domains(session)
    role_map, created_role_ids = await _ensure_roles(session)
    menus = await _ensure_menus(session)
    await _assign_role_menus(session, role_map, menus, created_role_ids)
    await _ensure_request_settings(session)

    admin = await _ensure_admin(session, dept_map)
    await _assign_admin_role(session, admin, role_map[SUPER_ADMIN_ROLE])
    await session.commit()
    logger.info(
        "Seed finished: %s departments, %s roles, %s menus, %s categories, "
        "%s fields, %s models (sample data: %s)",
        len(dept_map),
        len(role_map),
        len(menus),
        len(category_map),
        fields_created,
        len(model_map),
        settings.SEED_SAMPLE_DATA,
    )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    async with AsyncSessionLocal() as session:
        await seed_initial_data(session)


if __name__ == "__main__":
    asyncio.run(main())
