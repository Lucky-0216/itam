class AssetStatus:
    PENDING_STOCK = "PENDING_STOCK"
    IN_STOCK = "IN_STOCK"
    IN_USE = "IN_USE"
    BORROWED = "BORROWED"
    IDLE = "IDLE"
    REPAIRING = "REPAIRING"
    PENDING_SCRAP = "PENDING_SCRAP"
    SCRAPPED = "SCRAPPED"
    VOIDED = "VOIDED"


ASSET_STATUS_LABELS = {
    AssetStatus.PENDING_STOCK: "待入库",
    AssetStatus.IN_STOCK: "在库",
    AssetStatus.IN_USE: "在用",
    AssetStatus.BORROWED: "借出",
    AssetStatus.IDLE: "闲置",
    AssetStatus.REPAIRING: "维修中",
    AssetStatus.PENDING_SCRAP: "待报废",
    AssetStatus.SCRAPPED: "已报废",
    AssetStatus.VOIDED: "已作废",
}

ASSET_STATUS_TAG_TYPES = {
    AssetStatus.PENDING_STOCK: "info",
    AssetStatus.IN_STOCK: "success",
    AssetStatus.IN_USE: "primary",
    AssetStatus.BORROWED: "warning",
    AssetStatus.IDLE: "warning",
    AssetStatus.REPAIRING: "warning",
    AssetStatus.PENDING_SCRAP: "danger",
    AssetStatus.SCRAPPED: "info",
    AssetStatus.VOIDED: "info",
}


class CategoryType:
    HARDWARE = "HARDWARE"
    SOFTWARE = "SOFTWARE"
    ACCESSORY = "ACCESSORY"
    CONSUMABLE = "CONSUMABLE"


CATEGORY_TYPE_LABELS = {
    CategoryType.HARDWARE: "硬件",
    CategoryType.SOFTWARE: "软件",
    CategoryType.ACCESSORY: "配件",
    CategoryType.CONSUMABLE: "耗材",
}


class FieldType:
    TEXT = "TEXT"
    NUMBER = "NUMBER"
    DATE = "DATE"
    SELECT = "SELECT"


FIELD_TYPE_LABELS = {
    FieldType.TEXT: "文本",
    FieldType.NUMBER: "数字",
    FieldType.DATE: "日期",
    FieldType.SELECT: "下拉选项",
}
