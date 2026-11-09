SUPER_ADMIN_ROLE = "SUPER_ADMIN"


class DomainScope:
    ALL = "ALL"
    CUSTOM = "CUSTOM"


class DataScope:
    ALL = "ALL"
    DEPT_AND_CHILD = "DEPT_AND_CHILD"
    DEPT = "DEPT"
    CUSTOM = "CUSTOM"
    ROLE = "ROLE"
    SELF = "SELF"


DATA_SCOPE_LABELS = {
    DataScope.ALL: "全部数据",
    DataScope.DEPT_AND_CHILD: "本部门及下级部门",
    DataScope.DEPT: "本部门",
    DataScope.CUSTOM: "自定义部门",
    DataScope.ROLE: "本角色成员创建",
    DataScope.SELF: "仅本人",
}

SCOPE_PRIORITY = [
    DataScope.ALL,
    DataScope.DEPT_AND_CHILD,
    DataScope.DEPT,
    DataScope.CUSTOM,
    DataScope.ROLE,
    DataScope.SELF,
]

# 按资源划分的数据权限目录：角色可对每个资源单独配置数据范围
DATA_RESOURCE_LABELS: dict[str, str] = {
    "asset": "资产台账",
    "inbound": "入库管理",
    "stock": "库存管理",
    "requisition": "领用与归还",
    "transfer": "资产调拨",
    "scrap": "资产报废",
    "inventory": "资产盘点",
    "maintenance": "维修管理",
    "contract": "合同管理",
    "report": "报表分析",
}

# 字段级权限目录：前端角色授权界面与后端序列化/更新校验共用
ASSET_FIELD_CATALOG = [
    {"field": "name", "label": "资产名称"},
    {"field": "serial_no", "label": "序列号"},
    {"field": "mac_address", "label": "MAC 地址"},
    {"field": "purchase_date", "label": "购置日期"},
    {"field": "supplier", "label": "供应商"},
    {"field": "purchase_price", "label": "采购价格"},
    {"field": "warranty_end", "label": "保修到期"},
    {"field": "location", "label": "存放位置"},
    {"field": "custodian_id", "label": "当前责任人"},
    {"field": "remark", "label": "备注"},
]

FIELD_CATALOG: dict[str, list[dict[str, str]]] = {
    "asset": ASSET_FIELD_CATALOG,
}
