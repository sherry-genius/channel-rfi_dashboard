import streamlit as st
import pandas as pd
import datetime
import json
import os
import re
import io
import zipfile
import xml.etree.ElementTree as ET
import urllib.request
import urllib.parse
from supabase import create_client

# ========== 币种选项 ==========
CURRENCY_OPTIONS = [
    "USD", "ARS", "AUD", "BHD", "BWP", "BRL", "GBP", "BND", "BGN", "CAD",
    "CLP", "CNY", "COP", "CZK", "DKK", "AED", "EUR", "HKD", "HUF", "ISK",
    "INR", "IDR", "IRR", "ILS", "JPY", "KZT", "KWD", "LYD", "MYR", "MUR",
    "MXN", "NPR", "NZD", "NOK", "OMR", "PKR", "PHP", "PLN", "QAR", "RON",
    "RUB", "SAR", "SGD", "ZAR", "KRW", "LKR", "SEK", "CHF", "TWD", "THB",
    "TTD", "TRY", "VES", "VND", "CNH", "MTR",
]

# ========== 调单分类选项 ==========
STAT_TYPE_OPTIONS = ["Recall", "Personal Information", "Retrieval Request"]
CONTENT_CATEGORIES = ["", "KYC问询", "单笔交易问询", "账户调查", "结汇", "警方协查", "Recall"]
TRANSACTION_TYPE_OPTIONS = ["入账", "出款"]
TRANSACTION_STATUS_OPTIONS = ["已到账", "未到账", "渠道退款", "商户退款"]

# ========== 页面配置 ==========
st.set_page_config(page_title="调单管理系统", layout="wide")
st.title("📋 调单管理系统")
st.warning("✅ 测试版本 v1.0.14 - 2026-07-24（通讯录加载修复）")

# ========== 初始化 Supabase 连接 ==========
try:
    SUPABASE_URL = st.secrets["connections"]["supabase"]["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["connections"]["supabase"]["SUPABASE_KEY"]
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    st.success("✅ Supabase 连接成功")
except Exception as e:
    st.error(f"❌ Supabase 连接失败：{e}")
    st.stop()

# ========== 数据库字段映射 ==========
APP_DATA_FIELDS = [
    "收件日期", "商户ID", "商户名称", "调单类型", "金额", "币种",
    "业务线", "渠道", "邮件标题", "调单内容分类", "调单内容详情", "登记时间",
]
FIELD_ALIASES = {
    "收件日期": ["收件日期", "receive_date", "received_date", "date"],
    "商户ID": ["商户ID", "merchant_id", "merchantid", "merchant_no"],
    "商户名称": ["商户名称", "merchant_name", "merchantname"],
    "调单类型": ["调单类型", "order_type", "type", "stat_type", "diaodan_type"],
    "金额": ["金额", "amount", "money"],
    "币种": ["币种", "currency"],
    "业务线": ["业务线", "business_line", "biz_line"],
    "渠道": ["渠道", "channel"],
    "邮件标题": ["邮件标题", "email_title", "email_subject", "subject", "mail_title"],
    "调单内容分类": ["调单内容分类", "content_category", "content_type"],
    "调单内容详情": ["调单内容详情", "content_detail", "content_details", "details"],
    "登记时间": ["登记时间", "created_at", "register_time", "registration_time"],
}
SUPABASE_ALTER_SQL = """
-- 在 Supabase → SQL Editor 中运行，为 diaodan 表补全中文字段
ALTER TABLE diaodan ADD COLUMN IF NOT EXISTS "收件日期" TEXT;
ALTER TABLE diaodan ADD COLUMN IF NOT EXISTS "商户ID" TEXT;
ALTER TABLE diaodan ADD COLUMN IF NOT EXISTS "商户名称" TEXT;
ALTER TABLE diaodan ADD COLUMN IF NOT EXISTS "调单类型" TEXT;
ALTER TABLE diaodan ADD COLUMN IF NOT EXISTS "金额" DOUBLE PRECISION;
ALTER TABLE diaodan ADD COLUMN IF NOT EXISTS "币种" TEXT;
ALTER TABLE diaodan ADD COLUMN IF NOT EXISTS "业务线" TEXT;
ALTER TABLE diaodan ADD COLUMN IF NOT EXISTS "渠道" TEXT;
ALTER TABLE diaodan ADD COLUMN IF NOT EXISTS "邮件标题" TEXT;
ALTER TABLE diaodan ADD COLUMN IF NOT EXISTS "调单内容分类" TEXT;
ALTER TABLE diaodan ADD COLUMN IF NOT EXISTS "调单内容详情" TEXT;
ALTER TABLE diaodan ADD COLUMN IF NOT EXISTS "登记时间" TEXT;
""".strip()

SUPABASE_CREATE_SQL = """
-- 如果 diaodan 表不存在，在 Supabase → SQL Editor 中运行此脚本
CREATE TABLE IF NOT EXISTS public.diaodan (
    id BIGSERIAL PRIMARY KEY,
    "收件日期" TEXT,
    "商户ID" TEXT,
    "商户名称" TEXT,
    "调单类型" TEXT,
    "金额" DOUBLE PRECISION DEFAULT 0,
    "币种" TEXT DEFAULT 'USD',
    "业务线" TEXT,
    "渠道" TEXT,
    "邮件标题" TEXT,
    "调单内容分类" TEXT,
    "调单内容详情" TEXT,
    "登记时间" TEXT
);

ALTER TABLE public.diaodan ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "allow_all_diaodan" ON public.diaodan;
CREATE POLICY "allow_all_diaodan" ON public.diaodan
    AS PERMISSIVE FOR ALL TO public
    USING (true) WITH CHECK (true);

GRANT ALL ON public.diaodan TO anon, authenticated, service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;
""".strip()

SUPABASE_RLS_FIX_SQL = """
-- 修复「row-level security policy」写入失败
-- 在 Supabase → SQL Editor 中整段运行

-- 1. 删除 diaodan 表上所有旧策略（避免冲突）
DO $$
DECLARE pol record;
BEGIN
  FOR pol IN
    SELECT policyname FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'diaodan'
  LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.diaodan', pol.policyname);
  END LOOP;
END $$;

-- 2. 重新开启 RLS 并创建允许读写策略
ALTER TABLE public.diaodan ENABLE ROW LEVEL SECURITY;

CREATE POLICY "allow_all_diaodan" ON public.diaodan
    AS PERMISSIVE FOR ALL TO public
    USING (true) WITH CHECK (true);

-- 3. 授予 anon / authenticated 读写权限
GRANT ALL ON public.diaodan TO anon, authenticated, service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;
""".strip()

SUPABASE_RLS_DISABLE_SQL = """
-- 备选方案：内部工具可临时关闭 RLS（更简单）
ALTER TABLE public.diaodan DISABLE ROW LEVEL SECURITY;
GRANT ALL ON public.diaodan TO anon, authenticated, service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;
""".strip()

DEFAULT_APP_TO_DB = {field: field for field in APP_DATA_FIELDS}

def is_rls_error(error):
    text = str(error).lower()
    return "row-level security" in text or "42501" in text

def show_db_error_help(error_samples):
    if not error_samples:
        return
    combined = " ".join(error_samples).lower()
    if "row-level security" in combined or "42501" in combined:
        st.error("❌ 写入被 Supabase 行级安全策略（RLS）拦截。请在 SQL Editor 运行以下脚本：")
        st.code(SUPABASE_RLS_FIX_SQL, language="sql")
        st.markdown("**若仍失败，可改用备选方案（关闭 RLS）：**")
        st.code(SUPABASE_RLS_DISABLE_SQL, language="sql")
        st.info("运行成功后，点击 Streamlit 右上角 **Rerun**，再试「测试写入 1 条」。")
    else:
        st.error("失败详情：")
        for msg in error_samples:
            st.write(f"- {msg}")

def _extract_diaodan_columns_from_openapi(spec):
    candidates = []
    definitions = spec.get("definitions") or {}
    for name, schema in definitions.items():
        if "diaodan" in name.lower():
            candidates.extend(schema.get("properties", {}).keys())
    schemas = spec.get("components", {}).get("schemas", {})
    for name, schema in schemas.items():
        if "diaodan" in name.lower():
            candidates.extend(schema.get("properties", {}).keys())
    paths = spec.get("paths", {})
    for path, methods in paths.items():
        if "diaodan" not in path.lower():
            continue
        for detail in methods.values():
            if not isinstance(detail, dict):
                continue
            for resp in detail.get("responses", {}).values():
                if not isinstance(resp, dict):
                    continue
                schema = resp.get("schema")
                if isinstance(schema, dict) and schema.get("items", {}).get("properties"):
                    candidates.extend(schema["items"]["properties"].keys())
                content = resp.get("content", {})
                json_schema = content.get("application/json", {}).get("schema", {})
                if isinstance(json_schema, dict) and json_schema.get("items", {}).get("properties"):
                    candidates.extend(json_schema["items"]["properties"].keys())
    seen = set()
    ordered = []
    for col in candidates:
        if col not in seen:
            seen.add(col)
            ordered.append(col)
    return ordered

def _fetch_openapi_columns():
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    accept_types = [
        "application/openapi+json",
        "application/vnd.pgrst.openapi+json",
        "application/json",
    ]
    urls = [
        f"{SUPABASE_URL.rstrip('/')}/rest/v1/",
        f"{SUPABASE_URL.rstrip('/')}/rest/v1/diaodan",
    ]
    for url in urls:
        for accept in accept_types:
            try:
                req = urllib.request.Request(url, headers={**headers, "Accept": accept})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    spec = json.loads(resp.read().decode())
                columns = _extract_diaodan_columns_from_openapi(spec)
                if columns:
                    return columns
            except Exception:
                continue
    return []

@st.cache_data(ttl=300)
def get_diaodan_db_columns():
    try:
        response = supabase.table("diaodan").select("*").limit(1).execute()
        if response.data:
            return list(response.data[0].keys())
    except Exception:
        pass
    columns = _fetch_openapi_columns()
    if columns:
        return columns
    return list(DEFAULT_APP_TO_DB.values())

@st.cache_data(ttl=300)
def get_column_mapping():
    db_columns = get_diaodan_db_columns()
    db_col_set = set(db_columns)
    app_to_db = {}
    for app_field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in db_col_set:
                app_to_db[app_field] = alias
                break
    if not app_to_db:
        app_to_db = DEFAULT_APP_TO_DB.copy()
        db_columns = list(DEFAULT_APP_TO_DB.values())
        mapping_mode = "default"
    else:
        mapping_mode = "detected"
    return app_to_db, db_columns, mapping_mode

def to_db_record(app_record):
    app_to_db, _, _ = get_column_mapping()
    db_record = {}
    for app_field, value in app_record.items():
        db_col = app_to_db.get(app_field, app_field if app_field in DEFAULT_APP_TO_DB else None)
        if db_col is not None:
            db_record[db_col] = value
    return db_record

def normalize_dataframe_columns(df):
    if len(df) == 0:
        return df
    app_to_db, _, _ = get_column_mapping()
    db_to_app = {db_col: app_field for app_field, db_col in app_to_db.items()}
    df = df.rename(columns=db_to_app)
    for col in ["id"] + APP_DATA_FIELDS:
        if col not in df.columns:
            df[col] = None
    return df

# ========== 数据读取 ==========
SUPABASE_PAGE_SIZE = 1000

def fetch_diaodan_rows(select_cols="*", order_col="id"):
    """分页读取 diaodan 表，突破 PostgREST 默认 1000 条上限。"""
    all_rows = []
    offset = 0
    while True:
        end = offset + SUPABASE_PAGE_SIZE - 1
        query = supabase.table("diaodan").select(select_cols)
        if order_col:
            query = query.order(order_col)
        response = query.range(offset, end).execute()
        batch = response.data or []
        all_rows.extend(batch)
        if len(batch) < SUPABASE_PAGE_SIZE:
            break
        offset += SUPABASE_PAGE_SIZE
    return all_rows

@st.cache_data(ttl=60)
def load_all_data():
    try:
        rows = fetch_diaodan_rows("*", "id")
        df = pd.DataFrame(rows)
        df = normalize_dataframe_columns(df)
        if len(df) == 0:
            return pd.DataFrame()
        return df
    except Exception as e:
        st.error(f"读取数据失败：{e}")
        return pd.DataFrame()

def save_data(收件日期, 商户ID, 商户名称, 调单类型, 金额, 币种, 业务线, 渠道, 邮件标题, 调单内容分类="", 调单内容详情=""):
    try:
        data = to_db_record({
            "收件日期": str(收件日期),
            "商户ID": str(商户ID),
            "商户名称": str(商户名称),
            "调单类型": str(调单类型),
            "金额": float(金额),
            "币种": str(币种),
            "业务线": str(业务线),
            "渠道": str(渠道),
            "邮件标题": str(邮件标题),
            "调单内容分类": str(调单内容分类),
            "调单内容详情": str(调单内容详情),
            "登记时间": datetime.datetime.now().isoformat(),
        })
        if not data:
            st.error("保存失败：没有可写入的数据。")
            return False
        supabase.table("diaodan").insert(data).execute()
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"保存数据失败：{e}")
        return False

def clean_import_str(value, default=""):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    text = str(value).strip()
    if text.lower() in ("nan", "none", "nat"):
        return default
    return text

def format_import_date(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    dt = pd.to_datetime(value, errors="coerce")
    if pd.isna(dt):
        return ""
    return dt.strftime("%Y-%m-%d")

def clean_import_amount(value):
    if value is None or value == "" or (isinstance(value, float) and pd.isna(value)):
        return 0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = value.replace(",", "")
        parts = value.split(".")
        if len(parts) > 2:
            value = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0

def _excel_file_bytes(file_obj):
    file_obj.seek(0)
    return file_obj.getvalue()

XLSX_MAIN_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
XLSX_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

def _xlsx_col_to_index(col_letters):
    idx = 0
    for ch in col_letters:
        idx = idx * 26 + (ord(ch.upper()) - ord("A") + 1)
    return idx - 1

def _xlsx_parse_cell_ref(ref):
    col = "".join(ch for ch in ref if ch.isalpha())
    row = "".join(ch for ch in ref if ch.isdigit())
    return int(row) - 1, _xlsx_col_to_index(col)

def _xlsx_read_shared_strings(zf):
    path = "xl/sharedStrings.xml"
    if path not in zf.namelist():
        return []
    root = ET.fromstring(zf.read(path))
    shared_strings = []
    for si in root.findall(f"{XLSX_MAIN_NS}si"):
        text_parts = []
        t = si.find(f"{XLSX_MAIN_NS}t")
        if t is not None:
            text_parts.append(t.text or "")
        else:
            for node in si.findall(f".//{XLSX_MAIN_NS}t"):
                text_parts.append(node.text or "")
        shared_strings.append("".join(text_parts))
    return shared_strings

def _xlsx_get_sheet_paths(file_bytes):
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        if "xl/workbook.xml" not in zf.namelist():
            raise ValueError("不是有效的 xlsx 文件")
        wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
        rels_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_map = {}
        for rel in rels_root:
            if rel.tag.endswith("Relationship"):
                rel_map[rel.attrib["Id"]] = rel.attrib["Target"]
        sheets = []
        for sheet in wb_root.findall(f"{XLSX_MAIN_NS}sheets/{XLSX_MAIN_NS}sheet"):
            rid = sheet.attrib.get(XLSX_REL_NS + "id") or sheet.attrib.get("r:id")
            target = rel_map[rid]
            if not target.startswith("xl/"):
                target = "xl/" + target.lstrip("/")
            sheets.append({"name": sheet.attrib["name"], "path": target.replace("\\", "/")})
        return sheets

def _xlsx_read_sheet_xml(file_bytes, sheet_name):
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        sheets = _xlsx_get_sheet_paths(file_bytes)
        sheet_info = next((s for s in sheets if s["name"] == sheet_name), None)
        if sheet_info is None:
            raise ValueError(f"找不到工作表：{sheet_name}")
        shared_strings = _xlsx_read_shared_strings(zf)
        sheet_root = ET.fromstring(zf.read(sheet_info["path"]))
        rows_data = {}
        max_row = 0
        max_col = 0
        for row in sheet_root.findall(f".//{XLSX_MAIN_NS}sheetData/{XLSX_MAIN_NS}row"):
            for cell in row.findall(f"{XLSX_MAIN_NS}c"):
                ref = cell.attrib.get("r")
                if not ref:
                    continue
                row_idx, col_idx = _xlsx_parse_cell_ref(ref)
                max_row = max(max_row, row_idx)
                max_col = max(max_col, col_idx)
                cell_type = cell.attrib.get("t")
                value = None
                v = cell.find(f"{XLSX_MAIN_NS}v")
                if cell_type == "s" and v is not None and v.text is not None:
                    idx = int(v.text)
                    value = shared_strings[idx] if idx < len(shared_strings) else v.text
                elif cell_type == "inlineStr":
                    t = cell.find(f".//{XLSX_MAIN_NS}t")
                    value = t.text if t is not None else ""
                elif v is not None:
                    value = v.text
                rows_data.setdefault(row_idx, {})[col_idx] = value
        table = []
        for r in range(max_row + 1):
            row_vals = [rows_data.get(r, {}).get(c) for c in range(max_col + 1)]
            table.append(row_vals)
        if not table:
            return pd.DataFrame()
        header = table[0]
        data_rows = table[1:] if len(table) > 1 else []
        columns = [str(h).strip() if h is not None else f"列{i + 1}" for i, h in enumerate(header)]
        return pd.DataFrame(data_rows, columns=columns)

def _calamine_available():
    try:
        import calamine  # noqa: F401
        return True
    except ImportError:
        return False

def get_excel_sheet_names(file_obj):
    file_bytes = _excel_file_bytes(file_obj)
    filename = getattr(file_obj, "name", "upload.xlsx").lower()
    errors = []
    if filename.endswith(".xls") and not filename.endswith(".xlsx"):
        try:
            buffer = io.BytesIO(file_bytes)
            excel_file = pd.ExcelFile(buffer, engine="xlrd")
            return excel_file.sheet_names, "xlrd"
        except Exception as exc:
            errors.append(f"xlrd: {exc}")
    if _calamine_available():
        try:
            buffer = io.BytesIO(file_bytes)
            excel_file = pd.ExcelFile(buffer, engine="calamine")
            return excel_file.sheet_names, "calamine"
        except Exception as exc:
            errors.append(f"calamine: {exc}")
    for engine_kwargs in ({"read_only": True, "data_only": True}, {}):
        try:
            buffer = io.BytesIO(file_bytes)
            excel_file = pd.ExcelFile(buffer, engine="openpyxl", engine_kwargs=engine_kwargs)
            return excel_file.sheet_names, "openpyxl"
        except Exception as exc:
            errors.append(f"openpyxl: {exc}")
    try:
        return [s["name"] for s in _xlsx_get_sheet_paths(file_bytes)], "xmlzip"
    except Exception as exc:
        errors.append(f"xmlzip: {exc}")
    raise RuntimeError("无法读取 Excel 工作表列表：\n" + "\n".join(errors))

def read_uploaded_excel(file_obj, sheet_name):
    file_bytes = _excel_file_bytes(file_obj)
    filename = getattr(file_obj, "name", "upload.xlsx").lower()
    errors = []
    if filename.endswith(".xls") and not filename.endswith(".xlsx"):
        try:
            buffer = io.BytesIO(file_bytes)
            df = pd.read_excel(buffer, sheet_name=sheet_name, engine="xlrd")
            return df, "xlrd"
        except Exception as exc:
            errors.append(f"xlrd: {exc}")
    if _calamine_available():
        try:
            buffer = io.BytesIO(file_bytes)
            df = pd.read_excel(buffer, sheet_name=sheet_name, engine="calamine")
            return df, "calamine"
        except Exception as exc:
            errors.append(f"calamine: {exc}")
    for engine_kwargs in ({"read_only": True, "data_only": True}, {}):
        try:
            buffer = io.BytesIO(file_bytes)
            df = pd.read_excel(buffer, sheet_name=sheet_name, engine="openpyxl", engine_kwargs=engine_kwargs)
            return df, engine_kwargs and "openpyxl-readonly" or "openpyxl"
        except Exception as exc:
            errors.append(f"openpyxl: {exc}")
    try:
        df = _xlsx_read_sheet_xml(file_bytes, sheet_name)
        return df, "xmlzip"
    except Exception as exc:
        errors.append(f"xmlzip: {exc}")
    raise RuntimeError("无法读取 Excel 数据：\n" + "\n".join(errors))

def resolve_excel_column(name, all_cols):
    name = clean_import_str(name)
    if not name:
        return None, None
    if name in all_cols:
        return name, None
    lower_map = {str(c).lower().strip(): c for c in all_cols}
    matched = lower_map.get(name.lower())
    if matched:
        return matched, f"已匹配到列：{matched}"
    return None, f"Excel 中找不到列「{name}」，请检查拼写或从下拉列表选择"

def prepare_import_dataframe(df_raw, col_map, col_names, fixed_values=None):
    fixed_values = fixed_values or {}
    df_std = pd.DataFrame()
    for std_col, excel_col in col_map.items():
        df_std[std_col] = df_raw[excel_col].values
    for col in col_names:
        if col not in df_std.columns:
            if col in fixed_values:
                df_std[col] = fixed_values[col]
            else:
                df_std[col] = None
    df_std["收件日期"] = df_std["收件日期"].apply(format_import_date)
    df_std["金额"] = df_std["金额"].apply(clean_import_amount)
    df_std = df_std.fillna({
        "商户ID": "", "商户名称": "", "金额": 0, "币种": "USD",
        "业务线": "其他", "渠道": "", "邮件标题": "",
    })
    for col in ["商户ID", "商户名称", "调单类型", "币种", "业务线", "渠道", "邮件标题"]:
        df_std[col] = df_std[col].apply(clean_import_str)
    return df_std

def normalize_import_fields(row):
    order_type = clean_import_str(row.get("调单类型"))
    business_line = clean_import_str(row.get("业务线"))
    if order_type and order_type not in STAT_TYPE_OPTIONS:
        if not business_line:
            business_line = order_type
        order_type = "Retrieval Request"
    if not order_type:
        order_type = "Retrieval Request"
    if not business_line:
        business_line = "其他"
    return order_type, business_line

def row_to_import_record(row):
    merchant_id = clean_import_str(row.get("商户ID")) or "未填写"
    merchant_name = clean_import_str(row.get("商户名称")) or "未填写"
    receive_date = clean_import_str(row.get("收件日期")) or datetime.date.today().isoformat()
    order_type, business_line = normalize_import_fields(row)
    return {
        "收件日期": receive_date,
        "商户ID": merchant_id,
        "商户名称": merchant_name,
        "调单类型": order_type,
        "金额": float(row["金额"]) if pd.notna(row.get("金额")) else 0,
        "币种": clean_import_str(row.get("币种"), "USD"),
        "业务线": business_line,
        "渠道": clean_import_str(row.get("渠道")),
        "邮件标题": clean_import_str(row.get("邮件标题")),
        "调单内容分类": "",
        "调单内容详情": "",
        "登记时间": datetime.datetime.now().isoformat(),
    }

def import_dedup_key(record):
    email_title = clean_import_str(record.get("邮件标题"))
    if email_title:
        return ("email", email_title)
    return ("basic", record["商户ID"], record["收件日期"], record["调单类型"], record["渠道"], str(record["金额"]))

def import_dataframe(df_to_import):
    existing_df = load_all_data()
    existing_keys = set()
    if len(existing_df) > 0:
        for _, existing_row in existing_df.iterrows():
            existing_keys.add(import_dedup_key({
                "商户ID": clean_import_str(existing_row.get("商户ID")) or "未填写",
                "收件日期": clean_import_str(existing_row.get("收件日期")),
                "调单类型": clean_import_str(existing_row.get("调单类型")),
                "渠道": clean_import_str(existing_row.get("渠道")),
                "金额": existing_row.get("金额", 0),
                "邮件标题": clean_import_str(existing_row.get("邮件标题")),
            }))
    success_count = 0
    skip_count = 0
    fail_count = 0
    error_samples = []
    for row_idx, row in df_to_import.iterrows():
        record = row_to_import_record(row)
        key = import_dedup_key(record)
        if key in existing_keys:
            skip_count += 1
            continue
        try:
            db_record = to_db_record(record)
            supabase.table("diaodan").insert(db_record).execute()
            success_count += 1
            existing_keys.add(key)
        except Exception as e:
            fail_count += 1
            if len(error_samples) < 5:
                error_samples.append(f"第 {row_idx + 2} 行：{e}")
    st.cache_data.clear()
    return {
        "success_count": success_count,
        "skip_count": skip_count,
        "fail_count": fail_count,
        "error_samples": error_samples,
        "total_rows": len(df_to_import),
    }

def delete_data(id):
    try:
        supabase.table("diaodan").delete().eq("id", id).execute()
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"删除失败：{e}")
        return False

def delete_all_data():
    try:
        while True:
            response = supabase.table("diaodan").select("id").order("id").limit(SUPABASE_PAGE_SIZE).execute()
            ids = [row["id"] for row in (response.data or [])]
            if not ids:
                break
            supabase.table("diaodan").delete().in_("id", ids).execute()
        st.cache_data.clear()
        return True, None
    except Exception as e:
        return False, str(e)

def save_edited_records(edited_df):
    if len(edited_df) == 0:
        return 0
    updated_count = 0
    for _, row in edited_df.iterrows():
        try:
            rid = int(row['id'])
            update_data = to_db_record({
                "收件日期": str(row['收件日期']),
                "商户ID": str(row['商户ID']),
                "商户名称": str(row['商户名称']),
                "调单类型": str(row['调单类型']),
                "金额": float(row['金额']) if pd.notna(row['金额']) else 0,
                "币种": str(row['币种']),
                "业务线": str(row['业务线']),
                "渠道": str(row['渠道']),
                "邮件标题": str(row['邮件标题']),
                "调单内容分类": str(row['调单内容分类']) if pd.notna(row['调单内容分类']) else '',
                "调单内容详情": str(row['调单内容详情']) if pd.notna(row['调单内容详情']) else '',
            })
            if not update_data:
                continue
            supabase.table("diaodan").update(update_data).eq("id", rid).execute()
            updated_count += 1
        except Exception as e:
            st.warning(f"更新 ID {rid} 失败：{e}")
            continue
    st.cache_data.clear()
    return updated_count

def find_transaction_history(商户ID, 汇款方, 收款方):
    df = load_all_data()
    if len(df) == 0:
        return pd.DataFrame()
    matches = []
    for _, row in df.iterrows():
        if str(row.get('商户ID', '')).strip() != 商户ID:
            continue
        detail_str = row.get('调单内容详情', '')
        if not detail_str or pd.isna(detail_str):
            continue
        try:
            detail = json.loads(detail_str)
        except (json.JSONDecodeError, TypeError):
            continue
        if str(detail.get('汇款方', '')).strip() == 汇款方 and str(detail.get('收款方', '')).strip() == 收款方:
            matches.append({
                'ID': row['id'],
                '收件日期': row['收件日期'],
                '调单类型': row['调单类型'],
                '调单内容分类': row.get('调单内容分类', ''),
                '金额': row['金额'],
                '币种': row.get('币种', ''),
                '交易类型': detail.get('交易类型', ''),
                '交易状态': detail.get('交易状态', ''),
                '登记时间': row.get('登记时间', ''),
            })
    return pd.DataFrame(matches)

# ========== 汇率（x-rates.com） ==========
XRATES_URL = "https://www.x-rates.com/table/?from=USD&amount=1"
XRATES_NAME_TO_CODE = {
    "Argentine Peso": "ARS", "Australian Dollar": "AUD", "Bahraini Dinar": "BHD",
    "Botswana Pula": "BWP", "Brazilian Real": "BRL", "Bruneian Dollar": "BND",
    "Canadian Dollar": "CAD", "Chilean Peso": "CLP", "Chinese Yuan Renminbi": "CNY",
    "Colombian Peso": "COP", "Czech Koruna": "CZK", "Danish Krone": "DKK",
    "Euro": "EUR", "Hong Kong Dollar": "HKD", "Hungarian Forint": "HUF",
    "Icelandic Krona": "ISK", "Indian Rupee": "INR", "Indonesian Rupiah": "IDR",
    "Iranian Rial": "IRR", "Israeli Shekel": "ILS", "Japanese Yen": "JPY",
    "Kazakhstani Tenge": "KZT", "South Korean Won": "KRW", "Kuwaiti Dinar": "KWD",
    "Libyan Dinar": "LYD", "Malaysian Ringgit": "MYR", "Mauritian Rupee": "MUR",
    "Mexican Peso": "MXN", "Nepalese Rupee": "NPR", "New Zealand Dollar": "NZD",
    "Norwegian Krone": "NOK", "Omani Rial": "OMR", "Pakistani Rupee": "PKR",
    "Philippine Peso": "PHP", "Polish Zloty": "PLN", "Qatari Riyal": "QAR",
    "Romanian New Leu": "RON", "Russian Ruble": "RUB", "Saudi Arabian Riyal": "SAR",
    "Singapore Dollar": "SGD", "South African Rand": "ZAR", "Sri Lankan Rupee": "LKR",
    "Swedish Krona": "SEK", "Swiss Franc": "CHF", "Taiwan New Dollar": "TWD",
    "Thai Baht": "THB", "Trinidadian Dollar": "TTD", "Turkish Lira": "TRY",
    "Emirati Dirham": "AED", "British Pound": "GBP",
}
CURRENCY_TO_USD_ALIASES = {"CNH": "CNY"}

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_usd_exchange_rates():
    req = urllib.request.Request(XRATES_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read()
    tables = pd.read_html(html)
    table = max(tables, key=len)
    rates = {"USD": 1.0}
    for _, row in table.iterrows():
        code = XRATES_NAME_TO_CODE.get(row["US Dollar"])
        if code:
            rates[code] = float(row["inv. 1.00 USD"])
    text = html.decode("utf-8", errors="ignore")
    updated_match = re.search(r"(\w{3} \d{2}, \d{4} \d{2}:\d{2} UTC)", text)
    updated_at = updated_match.group(1) if updated_match else None
    return rates, updated_at

def add_usd_amount_column(df, rates):
    df = df.copy()
    codes = df["币种"].fillna("USD").astype(str).str.strip().str.upper()
    codes = codes.replace(CURRENCY_TO_USD_ALIASES)
    usd_rates = codes.map(rates)
    missing_mask = usd_rates.isna() & (df["金额"] > 0)
    missing_currencies = sorted(codes[missing_mask].unique().tolist())
    df["金额_USD"] = df["金额"] * usd_rates.fillna(0)
    return df, missing_currencies

def build_biz_type_summary(df):
    type_order = ["Recall", "Retrieval Request", "Personal Information"]
    biz_order = ["B2B", "电商", "服贸汇兑", "其他"]
    if len(df) == 0:
        return pd.DataFrame(columns=["业务线"] + type_order + ["合计"])
    work = df.copy()
    work["业务线"] = work["业务线"].fillna("其他").astype(str).str.strip()
    work.loc[work["业务线"] == "", "业务线"] = "其他"
    pivot = pd.crosstab(work["业务线"], work["调单类型"])
    for t in type_order:
        if t not in pivot.columns:
            pivot[t] = 0
    pivot = pivot[type_order]
    ordered_biz = [b for b in biz_order if b in pivot.index]
    other_biz = sorted(b for b in pivot.index if b not in biz_order)
    pivot = pivot.loc[ordered_biz + other_biz]
    pivot["合计"] = pivot.sum(axis=1)
    total = pivot.sum(axis=0)
    total.name = "合计"
    pivot = pd.concat([pivot, total.to_frame().T])
    pivot = pivot.reset_index()
    pivot.columns.name = None
    if pivot.columns[0] != "业务线":
        pivot = pivot.rename(columns={pivot.columns[0]: "业务线"})
    num_cols = type_order + ["合计"]
    pivot[num_cols] = pivot[num_cols].astype(int)
    return pivot

def apply_all_data_filters(df, range_start, range_end, selected_biz, selected_type, selected_channel, keyword):
    filtered = df.copy()
    if "收件日期" in filtered.columns:
        date_col = pd.to_datetime(filtered["收件日期"], errors="coerce")
        filtered = filtered[date_col.notna() & (date_col.dt.date >= range_start) & (date_col.dt.date <= range_end)]
    if selected_biz != "全部":
        filtered = filtered[filtered["业务线"].fillna("").astype(str).str.strip() == selected_biz.strip()]
    if selected_type != "全部":
        filtered = filtered[filtered["调单类型"].fillna("").astype(str).str.strip() == selected_type.strip()]
    if selected_channel != "全部":
        filtered = filtered[filtered["渠道"].fillna("").astype(str).str.strip() == selected_channel.strip()]
    keyword = keyword.strip()
    if keyword:
        kw = keyword.lower()
        text_cols = ["商户ID", "商户名称", "邮件标题", "渠道", "调单内容分类", "调单内容详情"]
        mask = pd.Series(False, index=filtered.index)
        for col in text_cols:
            if col in filtered.columns:
                mask = mask | filtered[col].fillna("").astype(str).str.lower().str.contains(kw, regex=False)
        filtered = filtered[mask]
    return filtered

def count_by_filters(df, range_start, range_end, selected_biz, selected_type, selected_channel, keyword):
    return len(apply_all_data_filters(df, range_start, range_end, selected_biz, selected_type, selected_channel, keyword))

def build_monthly_count_with_mom_chart(trend_df):
    import altair as alt
    data = trend_df.copy().sort_values("收件日期").reset_index(drop=True)
    data["环比%"] = data["笔数"].pct_change() * 100
    x_sort = data["收件日期"].tolist()
    x_enc = alt.X("收件日期:N", sort=x_sort, title="月份", axis=alt.Axis(labelAngle=-45))
    bars = alt.Chart(data).mark_bar(color="#5470C6", opacity=0.85).encode(
        x=x_enc,
        y=alt.Y("笔数:Q", title="调单笔数"),
        tooltip=[
            alt.Tooltip("收件日期:N", title="月份"),
            alt.Tooltip("笔数:Q", title="笔数", format=","),
        ],
    )
    line = alt.Chart(data.dropna(subset=["环比%"])).mark_line(color="#EE6666", point=alt.OverlayMarkDef(filled=True, size=60)).encode(
        x=x_enc,
        y=alt.Y("环比%:Q", title="环比 (%)", axis=alt.Axis(format="+.1f", orient="right")),
        tooltip=[
            alt.Tooltip("收件日期:N", title="月份"),
            alt.Tooltip("环比%:Q", title="较上月环比", format="+.1f"),
        ],
    )
    return alt.layer(bars, line).resolve_scale(y="independent").properties(height=340)

def build_monthly_amount_bar_chart(amount_trend_df):
    import altair as alt
    data = amount_trend_df.copy().sort_values("收件日期").reset_index(drop=True)
    x_sort = data["收件日期"].tolist()
    return alt.Chart(data).mark_bar(color="#91CC75", opacity=0.85).encode(
        x=alt.X("收件日期:N", sort=x_sort, title="月份", axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("金额(USD):Q", title="金额 (USD)", axis=alt.Axis(format=",.0f")),
        tooltip=[
            alt.Tooltip("收件日期:N", title="月份"),
            alt.Tooltip("金额(USD):Q", title="金额 (USD)", format=",.2f"),
        ],
    ).properties(height=340)

def build_monthly_recall_trend_chart(recall_trend_df):
    import altair as alt
    data = recall_trend_df.copy().sort_values("收件日期").reset_index(drop=True)
    x_sort = data["收件日期"].tolist()
    x_enc = alt.X("收件日期:N", sort=x_sort, title="月份", axis=alt.Axis(labelAngle=-45))
    bars = alt.Chart(data).mark_bar(color="#FAC858", opacity=0.85).encode(
        x=x_enc,
        y=alt.Y("金额(USD):Q", title="Recall 金额 (USD)", axis=alt.Axis(format=",.0f")),
        tooltip=[
            alt.Tooltip("收件日期:N", title="月份"),
            alt.Tooltip("金额(USD):Q", title="Recall 金额 (USD)", format=",.2f"),
        ],
    )
    line = alt.Chart(data).mark_line(color="#EE6666", point=alt.OverlayMarkDef(filled=True, size=60)).encode(
        x=x_enc,
        y=alt.Y("笔数:Q", title="Recall 笔数", axis=alt.Axis(format=",", orient="right")),
        tooltip=[
            alt.Tooltip("收件日期:N", title="月份"),
            alt.Tooltip("笔数:Q", title="Recall 笔数", format=","),
        ],
    )
    return alt.layer(bars, line).resolve_scale(y="independent").properties(height=340)

def format_month_day(d):
    return f"{d.month}月{d.day}日"

def format_date_range_label(start, end):
    if start == end:
        return format_month_day(start)
    return f"{format_month_day(start)}-{format_month_day(end)}"

def normalize_date_range(date_range, fallback_start, fallback_end):
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start, end = date_range
    elif isinstance(date_range, datetime.date):
        start = end = date_range
    else:
        start, end = fallback_start, fallback_end
    if start > end:
        start, end = end, start
    return start, end

def normalize_email_list(value):
    text = clean_import_str(value)
    if not text:
        return ""
    for sep in [";", "；", "，"]:
        text = text.replace(sep, ",")
    emails = [part.strip() for part in text.split(",") if part.strip()]
    return ",".join(emails)

def get_rfi_email_defaults():
    try:
        cfg = st.secrets.get("rfi_email", {})
        return {
            "to": cfg.get("default_to", ""),
            "cc": cfg.get("default_cc", ""),
            "webmail_url": cfg.get("webmail_url", "https://qiye.163.com/login/"),
        }
    except Exception:
        return {"to": "", "cc": "", "webmail_url": "https://qiye.163.com/login/"}

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONTACTS_CSV_NAME = "通讯录导出数据.csv"
CONTACTS_CUSTOM_FILE = os.path.join(APP_DIR, "rfi_contacts_custom.json")

def resolve_contacts_csv_path():
    candidates = [
        os.path.join(APP_DIR, CONTACTS_CSV_NAME),
        os.path.join(os.getcwd(), CONTACTS_CSV_NAME),
    ]
    seen = set()
    for path in candidates:
        norm = os.path.normpath(path)
        if norm in seen:
            continue
        seen.add(norm)
        if os.path.exists(norm):
            return norm
    try:
        cfg = st.secrets.get("rfi_email", {})
        custom_path = clean_import_str(cfg.get("contacts_csv", ""))
        if custom_path and os.path.exists(custom_path):
            return os.path.normpath(custom_path)
    except Exception:
        pass
    return None

def _normalize_csv_header(df):
    df = df.copy()
    df.columns = [str(c).strip().lstrip("\ufeff") for c in df.columns]
    return df

def _detect_contacts_columns(df):
    name_col = None
    email_cols = []
    for col in df.columns:
        col_text = str(col)
        col_lower = col_text.lower()
        if name_col is None and ("姓名" in col_text or col_lower in ("name", "联系人", "名称")):
            name_col = col
        if (
            "邮件地址" in col_text
            or "备用邮箱" in col_text
            or "email" in col_lower
            or col_text.endswith("邮箱")
        ):
            email_cols.append(col)
    if name_col is None and len(df.columns) > 0:
        name_col = df.columns[0]
    if not email_cols and len(df.columns) > 1:
        email_cols = [df.columns[1]]
    return name_col, email_cols

def _read_contacts_csv(csv_path):
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            df = pd.read_csv(csv_path, dtype=str, encoding=encoding)
            return _normalize_csv_header(df.fillna("")), None
        except Exception as exc:
            last_error = str(exc)
    return pd.DataFrame(), last_error

def _parse_contacts_dataframe(df):
    name_col, email_cols = _detect_contacts_columns(df)
    contacts = []
    seen = set()
    for _, row in df.iterrows():
        name = clean_import_str(row.get(name_col, "")) if name_col is not None else ""
        for col in email_cols:
            email = _normalize_contact_email(row.get(col, ""))
            email_key = email.lower()
            if email and email_key not in seen:
                seen.add(email_key)
                contacts.append({"name": name or email.split("@")[0], "email": email, "source": "csv"})
    contacts.sort(key=lambda c: (c["name"].lower(), c["email"].lower()))
    return contacts

def load_contacts_from_csv():
    csv_path = resolve_contacts_csv_path()
    if not csv_path:
        return [], None, f"未找到 {CONTACTS_CSV_NAME}，请与 app.py 放在同一目录并提交到 Git"
    df, read_error = _read_contacts_csv(csv_path)
    if read_error:
        return [], csv_path, f"读取通讯录失败：{read_error}"
    if len(df) == 0:
        return [], csv_path, "通讯录 CSV 为空"
    contacts = _parse_contacts_dataframe(df)
    if not contacts:
        return [], csv_path, "通讯录 CSV 中未识别到有效邮箱列，请检查表头"
    return contacts, csv_path, None

def load_custom_contacts_from_file():
    if not os.path.exists(CONTACTS_CUSTOM_FILE):
        return []
    try:
        with open(CONTACTS_CUSTOM_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        contacts = []
        for item in data:
            email = _normalize_contact_email(item.get("email", ""))
            if not email:
                continue
            contacts.append({
                "name": clean_import_str(item.get("name", "")) or email.split("@")[0],
                "email": email,
                "source": "custom",
            })
        return contacts
    except Exception:
        return []

def save_custom_contacts_to_file(contacts):
    try:
        with open(CONTACTS_CUSTOM_FILE, "w", encoding="utf-8") as f:
            json.dump(contacts, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def _normalize_contact_email(email):
    email = clean_import_str(email)
    if not email or "@" not in email:
        return ""
    return email

def init_rfi_custom_contacts():
    if "rfi_custom_contacts" not in st.session_state:
        st.session_state["rfi_custom_contacts"] = load_custom_contacts_from_file()

def get_rfi_contacts_meta():
    init_rfi_custom_contacts()
    csv_mtime = None
    csv_path = resolve_contacts_csv_path()
    if csv_path:
        try:
            csv_mtime = os.path.getmtime(csv_path)
        except Exception:
            csv_mtime = None
    cache_key = (csv_path, csv_mtime, len(st.session_state["rfi_custom_contacts"]))
    if st.session_state.get("_rfi_contacts_cache_key") != cache_key:
        csv_contacts, loaded_path, csv_error = load_contacts_from_csv()
        merged = []
        seen = set()
        for contact in csv_contacts + st.session_state["rfi_custom_contacts"]:
            email_key = contact["email"].lower()
            if email_key in seen:
                continue
            seen.add(email_key)
            merged.append(contact)
        merged.sort(key=lambda c: (c["name"].lower(), c["email"].lower()))
        st.session_state["_rfi_contacts_cache_key"] = cache_key
        st.session_state["rfi_all_contacts"] = merged
        st.session_state["rfi_contacts_csv_path"] = loaded_path
        st.session_state["rfi_contacts_error"] = csv_error
    return (
        st.session_state.get("rfi_all_contacts", []),
        st.session_state.get("rfi_contacts_csv_path"),
        st.session_state.get("rfi_contacts_error"),
    )

def get_rfi_contacts():
    contacts, _, _ = get_rfi_contacts_meta()
    return contacts

def search_rfi_contacts(query, contacts, limit=20):
    q = clean_import_str(query).lower()
    if not q:
        return []
    results = []
    for contact in contacts:
        haystack = f"{contact['name']} {contact['email']}".lower()
        if q in haystack:
            results.append(contact)
            if len(results) >= limit:
                break
    return results

def get_recipient_search_token(mail_to_value):
    text = mail_to_value or ""
    if "," in text:
        return text.rsplit(",", 1)[-1].strip()
    return text.strip()

def replace_recipient_token(mail_to_value, email):
    text = mail_to_value or ""
    if "," in text:
        prefix = text.rsplit(",", 1)[0].strip()
        return f"{prefix}, {email}" if prefix else email
    return email

def append_email_to_recipients(mail_to_value, email):
    current = normalize_email_list(mail_to_value)
    emails = [part.strip() for part in current.split(",") if part.strip()]
    if email.lower() not in {e.lower() for e in emails}:
        emails.append(email)
    return ",".join(emails)

def add_rfi_custom_contact(name, email):
    email = _normalize_contact_email(email)
    if not email:
        return False, "请输入有效邮箱地址"
    init_rfi_custom_contacts()
    name = clean_import_str(name) or email.split("@")[0]
    for contact in get_rfi_contacts():
        if contact["email"].lower() == email.lower():
            return False, "该邮箱已在通讯录中"
    new_contact = {"name": name, "email": email, "source": "custom"}
    st.session_state["rfi_custom_contacts"].append(new_contact)
    st.session_state.pop("_rfi_contacts_cache_key", None)
    saved = save_custom_contacts_to_file(st.session_state["rfi_custom_contacts"])
    if saved:
        return True, f"已添加：{name} · {email}"
    return True, f"已添加到本次会话：{name} · {email}（云端环境可能无法持久保存到文件）"

def render_rfi_recipient_contact_picker(contacts):
    mail_to_value = st.session_state.get("rfi_mail_to", "")
    token = get_recipient_search_token(mail_to_value)
    matches = search_rfi_contacts(token, contacts) if token else []
    if token and matches:
        labels = [f"{c['name']} · {c['email']}" for c in matches]
        pick_col1, pick_col2 = st.columns([5, 1])
        with pick_col1:
            selected_idx = st.selectbox(
                "通讯录匹配",
                options=list(range(len(matches))),
                format_func=lambda i: labels[i],
                key=f"rfi_contact_match_{token.lower()}",
                label_visibility="collapsed",
            )
        with pick_col2:
            if st.button("填入", key=f"rfi_contact_apply_{token.lower()}", use_container_width=True):
                email = matches[selected_idx]["email"]
                st.session_state["rfi_mail_to"] = replace_recipient_token(
                    st.session_state.get("rfi_mail_to", ""), email
                )
                st.rerun()
        st.caption(f"📇 输入「{token}」匹配到 {len(matches)} 个联系人，选择后点「填入」")
    elif token and not contacts:
        st.warning("通讯录尚未加载，无法匹配。请确认「通讯录导出数据.csv」已与 app.py 一并部署。")
    elif token:
        st.caption(f"📇 未找到包含「{token}」的联系人，可直接手动输入邮箱")

def build_mailto_url(to="", cc="", subject="", body=""):
    params = []
    cc_value = normalize_email_list(cc)
    subject_value = clean_import_str(subject)
    body_value = body or ""
    if cc_value:
        params.append(f"cc={urllib.parse.quote(cc_value, safe=',')}")
    if subject_value:
        params.append(f"subject={urllib.parse.quote(subject_value)}")
    if body_value:
        params.append(f"body={urllib.parse.quote(body_value)}")
    to_value = normalize_email_list(to)
    query = "&".join(params)
    if to_value:
        return f"mailto:{to_value}?{query}" if query else f"mailto:{to_value}"
    return f"mailto:?{query}" if query else "mailto:"

def build_mailto_url_safe(to="", cc="", subject="", body="", max_body_len=1800):
    body_value = body or ""
    if len(body_value) <= max_body_len:
        return build_mailto_url(to, cc, subject, body_value), False
    return build_mailto_url(to, cc, subject, ""), True

# ========== 模板数据 ==========
CHANNEL_TEMPLATES = {
    "DBS": {
        "DBS入账模板": """Dear Team,\n\nPlease kindly check the replies below regarding the transaction-.\n\n[Purpose of transaction / usage of fund]\n▪ What is the purpose of transaction / usage of fund?  \n[Reply: This transaction is a full/partial /deposit balance payment of the PI by the remitter to purchase products with the merchant. Please refer to the PI attached.]\n\n[Customer Background]\n▪ Please state the nature of business of your Customer.\n[Reply: The merchant is a supplier of XXX.]\n▪ Is the transaction within the customer's normal trading/profile?\n[Reply: YES]\n\n[Sanction Related]\nPlease confirm that the transaction or the Remitter / Beneficiary has NO direct or indirect exposure to / affiliate with any OFAC sanction regimes.\n[It is confirmed.]"""
    },
    "SCB": {
        "SCB通用模板": "Dear Team,\n\nPlease check the response highlighted below, thanks!\n\nPlease check the attached files and the responses highlighted below, thanks!"
    },
    "Banking Circle": {
        "BC通用模板": "Dear Team,\n\nPlease check the response highlighted below, thanks!"
    },
    "Citibank": {
        "citi两问": "1. Full detailed purpose of pymt.\n[To purchase products from our merchant.]\n\n2. Please provide the details of product or goods that involve if any.\n[The goods involved are]"
    },
    "GME": {
        "GME KYC": "Please review the following information for the merchant:\n\n- Merchant Name: [Name]\n- Date of Birth: [DOB]\n- Address: [Address]"
    },
    "巴克莱": {
        "巴克莱联系邮箱": "financialinstitutionsservicing@barclays.com\naysha.begum2@barclays.com"
    },
    "Thunes": {
        "Thunes出款说明": "邮件中的Sender = 客户\nTransaction ID [ID] and Transaction External ID [外部ID]"
    },
    "通用": {
        "礼貌感谢": "Thank you for your email.\nThank you for providing this update.\nYour assistance in this matter is much appreciated.",
        "催促邮件": "-May I know whether you are able to provide an update on the below please? Thanks.\n-Any updates on the following transaction? Thanks!",
        "延期邮件": "Hi team,\n\nWe are still waiting for the merchant to provide the material. Could you please extend the deadline?\n\nThank you for your understanding."
    }
}

# ========== 对客RFI模板 ==========
INTERNAL_RFI_TEMPLATES = {
    "电商店铺材料": "- 请提供您/您代理商的在线商店链接\n- 请提供您/您代理商的商店的后台截图\n- 请提供从平台到您/您代理商的银行账户的提现记录",
    "个人汇款方": "-请确认交易对手方为个人，个体工商户还是公司。\n--若交易对手方为个人代表公司交易，请提供该公司全名并解释为何使用个人账户做商业用途。",
    "软件服务": "- 请提供交易对手方全名\n- 请说明业务关系，交易目的，以及涉及的产品或服务\n- 请提供交易相关证明文件",
    "对内RFI通用": "【交易目的】\n请补充交易支持性材料\n-- 若涉及服务贸易，请提供双方合作协议\n-- 若涉及货物贸易，请补充提供采购合同和物流信息"
}

# ========== 侧边栏导航 ==========
page = st.sidebar.radio(
    "📌 功能导航",
    ["📊 调单看板", "📝 登记调单", "📤 导入历史数据", "📄 查看全部数据", "📧 回复渠道调单", "📨 对客RFI"]
)

# ============================================================
# PAGE 1: 调单看板
# ============================================================
if page == "📊 调单看板":
    st.header("📊 调单监控看板")
    df = load_all_data()
    if len(df) == 0:
        st.info("💡 暂无数据，请先「导入历史数据」或「登记调单」")
        st.stop()
    
    df['金额'] = pd.to_numeric(df['金额'], errors='coerce').fillna(0)
    df['收件日期'] = pd.to_datetime(df['收件日期'], errors='coerce')
    valid_dates = df['收件日期'].dropna()
    today = datetime.date.today()
    if len(valid_dates) > 0:
        data_min = valid_dates.min().date()
        data_max = valid_dates.max().date()
    else:
        data_min = data_max = today
    default_end = data_max
    default_start = default_end.replace(day=1)
    if default_start < data_min:
        default_start = data_min
    
    st.subheader("🔎 筛选条件")
    fcol1, fcol2, fcol3, fcol4 = st.columns(4)
    with fcol1:
        date_range = st.date_input("日期范围", value=(default_start, default_end), min_value=data_min, max_value=data_max)
        range_start, range_end = normalize_date_range(date_range, default_start, default_end)
    with fcol2:
        biz_list = ["全部"] + sorted(df['业务线'].dropna().unique().tolist())
        selected_biz = st.selectbox("业务线", biz_list)
    with fcol3:
        type_list = ["全部"] + sorted(df['调单类型'].dropna().unique().tolist())
        selected_type = st.selectbox("调单类型", type_list)
    with fcol4:
        channel_list = ["全部"] + sorted(df['渠道'].dropna().astype(str).str.strip().replace('', pd.NA).dropna().unique().tolist())
        selected_channel = st.selectbox("渠道", channel_list)
    
    filtered = df.copy()
    filtered = filtered[filtered['收件日期'].notna() & (filtered['收件日期'].dt.date >= range_start) & (filtered['收件日期'].dt.date <= range_end)]
    if selected_biz != "全部":
        filtered = filtered[filtered['业务线'] == selected_biz]
    if selected_type != "全部":
        filtered = filtered[filtered['调单类型'] == selected_type]
    if selected_channel != "全部":
        filtered = filtered[filtered['渠道'].astype(str).str.strip() == selected_channel]
    
    rates_error = None
    rates_updated_at = None
    missing_currencies = []
    try:
        rates, rates_updated_at = fetch_usd_exchange_rates()
        filtered, missing_currencies = add_usd_amount_column(filtered, rates)
    except Exception as e:
        rates_error = str(e)
        filtered["金额_USD"] = filtered["金额"]
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📋 总调单笔数", f"{len(filtered):,}")
    with col2:
        st.metric("🏢 涉及商户数", f"{filtered['商户ID'].nunique():,}")
    with col3:
        total_usd = filtered["金额_USD"].sum()
        st.metric("💰 总金额 (USD)", f"${total_usd:,.2f}")
    with col4:
        recall_count = len(filtered[filtered['调单类型'] == "Recall"])
        st.metric("🔄 Recall笔数", f"{recall_count:,}")
    
    with st.expander(f"📋 查看筛选结果明细（共 {len(filtered):,} 条）", expanded=False):
        if len(filtered) > 0:
            detail_df = filtered.copy()
            if '收件日期' in detail_df.columns:
                detail_df['收件日期'] = detail_df['收件日期'].dt.strftime('%Y-%m-%d')
            detail_cols = ['id', '收件日期', '商户ID', '商户名称', '调单类型', '金额', '币种', '金额_USD', '业务线', '渠道', '邮件标题', '登记时间']
            present_cols = [c for c in detail_cols if c in detail_df.columns]
            detail_df = detail_df[present_cols].sort_values('id', ascending=False)
            st.dataframe(detail_df, use_container_width=True, height=450, hide_index=True)
    
    tab1, tab2 = st.tabs(["📈 趋势分析", "📊 分布分析"])
    with tab1:
        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("每月调单笔数")
            trend = filtered.groupby(filtered['收件日期'].dt.strftime('%Y年%m月')).size().reset_index(name='笔数')
            trend.columns = ['收件日期', '笔数']
            if len(trend) > 0:
                try:
                    st.altair_chart(build_monthly_count_with_mom_chart(trend), use_container_width=True)
                    st.caption("柱状图：每月笔数｜折线：较上月环比 %（右轴）")
                except ImportError:
                    import matplotlib.pyplot as plt
                    trend_sorted = trend.sort_values("收件日期").reset_index(drop=True)
                    trend_sorted["环比%"] = trend_sorted["笔数"].pct_change() * 100
                    fig, ax1 = plt.subplots(figsize=(8, 4))
                    ax1.bar(trend_sorted["收件日期"], trend_sorted["笔数"], color="#5470C6", alpha=0.85)
                    ax1.set_ylabel("调单笔数")
                    ax1.tick_params(axis="x", rotation=45)
                    ax2 = ax1.twinx()
                    ax2.plot(trend_sorted["收件日期"], trend_sorted["环比%"], color="#EE6666", marker="o")
                    ax2.set_ylabel("环比 (%)")
                    ax2.axhline(0, color="#999999", linewidth=0.8, linestyle="--")
                    fig.tight_layout()
                    st.pyplot(fig)
        with col_right:
            st.subheader("每月调单金额 (USD)")
            amount_trend = filtered.groupby(filtered['收件日期'].dt.strftime('%Y年%m月'))['金额_USD'].sum().reset_index(name='金额(USD)')
            amount_trend.columns = ['收件日期', '金额(USD)']
            if len(amount_trend) > 0:
                try:
                    st.altair_chart(build_monthly_amount_bar_chart(amount_trend), use_container_width=True)
                except ImportError:
                    import matplotlib.pyplot as plt
                    amount_sorted = amount_trend.sort_values("收件日期")
                    fig, ax = plt.subplots(figsize=(8, 4))
                    ax.bar(amount_sorted["收件日期"], amount_sorted["金额(USD)"], color="#91CC75", alpha=0.85)
                    ax.set_ylabel("金额 (USD)")
                    ax.tick_params(axis="x", rotation=45)
                    fig.tight_layout()
                    st.pyplot(fig)
        st.subheader("Recall 趋势")
        recall_filtered = filtered[filtered['调单类型'] == "Recall"]
        if len(recall_filtered) == 0:
            st.info("当前筛选条件下暂无 Recall 数据")
        else:
            recall_trend = recall_filtered.groupby(recall_filtered['收件日期'].dt.strftime('%Y年%m月')).agg(
                笔数=('金额_USD', 'size'),
                金额_USD=('金额_USD', 'sum'),
            ).reset_index()
            recall_trend.columns = ['收件日期', '笔数', '金额(USD)']
            try:
                st.altair_chart(build_monthly_recall_trend_chart(recall_trend), use_container_width=True)
                st.caption("柱状图：Recall 金额 (USD)｜折线：Recall 笔数（右轴）")
            except ImportError:
                import matplotlib.pyplot as plt
                recall_sorted = recall_trend.sort_values("收件日期")
                fig, ax1 = plt.subplots(figsize=(10, 4))
                ax1.bar(recall_sorted["收件日期"], recall_sorted["金额(USD)"], color="#FAC858", alpha=0.85)
                ax1.set_ylabel("Recall 金额 (USD)")
                ax1.tick_params(axis="x", rotation=45)
                ax2 = ax1.twinx()
                ax2.plot(recall_sorted["收件日期"], recall_sorted["笔数"], color="#EE6666", marker="o")
                ax2.set_ylabel("Recall 笔数")
                fig.tight_layout()
                st.pyplot(fig)
    with tab2:
        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("调单类型分布")
            type_dist = filtered['调单类型'].value_counts()
            if len(type_dist) > 0:
                try:
                    import altair as alt
                    pie_data = type_dist.reset_index()
                    pie_data.columns = ['调单类型', '数量']
                    chart = alt.Chart(pie_data).mark_arc().encode(
                        theta=alt.Theta(field="数量", type="quantitative"),
                        color=alt.Color(field="调单类型", type="nominal"),
                        tooltip=['调单类型', '数量']
                    ).properties(height=300)
                    st.altair_chart(chart, use_container_width=True)
                except ImportError:
                    import matplotlib.pyplot as plt
                    fig, ax = plt.subplots()
                    ax.pie(type_dist.values, labels=type_dist.index, autopct='%1.1f%%')
                    ax.axis('equal')
                    st.pyplot(fig)
        with col_right:
            st.subheader("业务线分布")
            biz_dist = filtered['业务线'].value_counts()
            if len(biz_dist) > 0:
                st.bar_chart(biz_dist)

# ============================================================
# PAGE 2: 登记调单
# ============================================================
elif page == "📝 登记调单":
    st.header("📝 登记新调单")
    调单内容分类 = st.selectbox("调单内容分类", CONTENT_CATEGORIES, format_func=lambda x: "请选择" if x == "" else x)
    if 调单内容分类:
        st.subheader("📋 调单基本信息")
    col1, col2 = st.columns(2)
    with col1:
        收件日期 = st.date_input("收件日期", datetime.date.today())
        商户ID = st.text_input("商户ID *", placeholder="如：5181241025033620258")
        商户名称 = st.text_input("商户名称 *", placeholder="如：宇信數碼有限公司")
        调单类型 = st.selectbox("（统计用）调单类型", STAT_TYPE_OPTIONS)
    with col2:
        金额 = st.number_input("金额", min_value=0.0, step=0.01, value=0.0)
        币种 = st.selectbox("币种", CURRENCY_OPTIONS, index=CURRENCY_OPTIONS.index("USD"))
        业务线 = st.selectbox("业务线", ["电商", "B2B", "服贸汇兑"])
        渠道 = st.text_input("渠道", placeholder="如：Banking Circle / DBS / SCB")
    邮件标题 = st.text_input("邮件标题（可选）", placeholder="调单邮件主题")
    内容详情 = {}
    if 调单内容分类:
        st.markdown("---")
        st.subheader(f"📌 {调单内容分类} - 详细信息")
        if 调单内容分类 == "单笔交易问询":
            detail_col1, detail_col2 = st.columns(2)
            with detail_col1:
                汇款方 = st.text_input("汇款方")
            with detail_col2:
                收款方 = st.text_input("收款方")
            detail_col3, detail_col4 = st.columns(2)
            with detail_col3:
                交易类型 = st.selectbox("交易类型", TRANSACTION_TYPE_OPTIONS)
            with detail_col4:
                交易状态 = st.selectbox("交易状态", TRANSACTION_STATUS_OPTIONS)
            内容详情 = {"汇款方": 汇款方, "收款方": 收款方, "交易类型": 交易类型, "交易状态": 交易状态}
            if 商户ID.strip() and 汇款方.strip() and 收款方.strip():
                history_df = find_transaction_history(商户ID.strip(), 汇款方.strip(), 收款方.strip())
                st.markdown("##### 🔍 历史调单查询（同商户ID + 汇款方 + 收款方）")
                if len(history_df) > 0:
                    st.warning(f"⚠️ 发现 **{len(history_df)}** 条历史调单记录")
                    st.dataframe(history_df, use_container_width=True, hide_index=True)
                else:
                    st.info("✅ 暂无相同商户ID、汇款方、收款方的历史调单")
        else:
            内容详情["详细信息"] = st.text_area("详细信息", placeholder="请填写该调单的相关详情")
    if st.button("✅ 提交调单", type="primary"):
        if not 商户ID or not 商户名称:
            st.error("⚠️ 商户ID和商户名称不能为空")
        else:
            调单内容详情 = json.dumps(内容详情, ensure_ascii=False) if 内容详情 else ""
            if save_data(str(收件日期), 商户ID.strip(), 商户名称.strip(), 调单类型, 金额, 币种, 业务线, 渠道.strip(), 邮件标题.strip(), 调单内容分类, 调单内容详情):
                st.success("✅ 调单登记成功！看板已自动更新")
                st.balloons()

# ============================================================
# PAGE 3: 导入历史数据
# ============================================================
elif page == "📤 导入历史数据":
    st.header("📤 导入历史数据")
    app_to_db, db_columns, mapping_mode = get_column_mapping()
    with st.expander("🗄️ 数据库字段检测", expanded=(mapping_mode == "default")):
        if mapping_mode == "detected":
            st.success("已自动检测到 Supabase 表字段")
        else:
            st.warning("未能自动检测表字段，已使用默认中文字段名。若导入仍失败，请先在 Supabase 建表。")
        st.write("**Supabase 表 `diaodan` 当前字段：**", db_columns)
        st.write("**字段映射模式：**", "自动检测" if mapping_mode == "detected" else "默认中文字段")
        st.write("**已匹配的应用字段：**", app_to_db)
        st.markdown("**如果导入失败，请按顺序在 Supabase → SQL Editor 运行：**")
        st.markdown("1️⃣ 若表不存在，先运行建表脚本：")
        st.code(SUPABASE_CREATE_SQL, language="sql")
        st.markdown("2️⃣ 若表已存在但缺字段，运行补字段脚本：")
        st.code(SUPABASE_ALTER_SQL, language="sql")
        st.markdown("3️⃣ 若提示 RLS / row-level security 错误，运行权限脚本：")
        st.code(SUPABASE_RLS_FIX_SQL, language="sql")
        st.markdown("4️⃣ 运行后点击 Streamlit 右上角 **Rerun**，再试「测试写入 1 条」")
    st.info("""
    📌 使用说明：
    1. 点击「浏览文件」选择你的 Excel 文件
    2. 选择要导入的 Sheet
    3. 如果系统无法自动识别列名，请手动选择对应的列
    4. 点击「开始导入」
    """)
    uploaded_file = st.file_uploader("选择 Excel 文件", type=["xlsx", "xls"], key="import_file")
    if uploaded_file is not None:
        try:
            sheet_names, read_engine = get_excel_sheet_names(uploaded_file)
            default_sheet_index = sheet_names.index("（统计用）6张表数据汇总") if "（统计用）6张表数据汇总" in sheet_names else 0
            selected_sheet = st.selectbox("选择要导入的 Sheet", sheet_names, index=default_sheet_index)
            df_import, read_engine = read_uploaded_excel(uploaded_file, selected_sheet)
            st.caption(f"已使用 **{read_engine}** 引擎读取文件")
            st.write(f"📊 共读取到 **{len(df_import)}** 行数据")
            st.write("**原始列名：**", df_import.columns.tolist())
            st.dataframe(df_import.head(5), use_container_width=True)
            st.subheader("🔧 列名映射（如果自动识别失败，请手动选择）")
            st.caption("可从下拉选择 Excel 列、手动输入列名，或填写固定值（所有行相同）")
            all_cols = df_import.columns.tolist()
            auto_map = {}
            for col in all_cols:
                col_lower = col.lower().strip()
                if '商户id' in col_lower or '商户号' in col_lower:
                    auto_map['商户ID'] = col
                elif '商户名称' in col_lower or '商户名' in col_lower:
                    auto_map['商户名称'] = col
                elif '调单类型' in col_lower:
                    auto_map['调单类型'] = col
                elif '年月' in col and '收件日期' in col:
                    auto_map['收件日期'] = col
                elif '调单单笔金额' in col or ('单笔' in col and '金额' in col):
                    auto_map['金额'] = col
                elif '邮件名称' in col or 'reference id' in col_lower:
                    auto_map['邮件标题'] = col
                elif '收件日期' in col or '调单日期' in col:
                    auto_map['收件日期'] = col
                elif '金额' in col:
                    auto_map['金额'] = col
                elif '币种' in col:
                    auto_map['币种'] = col
                elif '业务线' in col:
                    auto_map['业务线'] = col
                elif '渠道' in col:
                    auto_map['渠道'] = col
                elif '邮件标题' in col:
                    auto_map['邮件标题'] = col
            col_map = {}
            fixed_values = {}
            mapping_errors = []
            col_names = ["商户ID", "商户名称", "调单类型", "收件日期", "金额", "币种", "业务线", "渠道", "邮件标题"]
            col_help = {
                "商户ID": "选填，如：5181241025033620258",
                "商户名称": "选填，如：宇信數碼有限公司",
                "调单类型": "选填，如：Recall / Personal Information / Retrieval Request；若无此列可跳过（默认 Retrieval Request）",
                "收件日期": "选填，日期格式",
                "金额": "选填，数字",
                "币种": "选填，如：USD / CNY / EUR",
                "业务线": "选填，如：电商 / B2B / 服贸汇兑",
                "渠道": "选填",
                "邮件标题": "选填"
            }
            for col_name in col_names:
                default_index = 0
                if col_name in auto_map and auto_map[col_name] in all_cols:
                    default_index = all_cols.index(auto_map[col_name]) + 1
                options = ["（跳过此列）"] + all_cols
                st.markdown(f"**{col_name}** - {col_help[col_name]}")
                map_col1, map_col2, map_col3 = st.columns([2, 1.2, 1.2])
                with map_col1:
                    selected = st.selectbox(
                        "从 Excel 列选择",
                        options,
                        index=default_index,
                        key=f"import_map_{col_name}",
                        label_visibility="collapsed",
                    )
                with map_col2:
                    manual_col = st.text_input(
                        "手动输入 Excel 列名",
                        placeholder="输入列名",
                        key=f"import_map_manual_{col_name}",
                    )
                with map_col3:
                    fixed_val = st.text_input(
                        "固定值（全体相同）",
                        placeholder="如：Recall",
                        key=f"import_map_fixed_{col_name}",
                    )
                if fixed_val.strip():
                    fixed_values[col_name] = fixed_val.strip()
                elif manual_col.strip():
                    resolved, hint = resolve_excel_column(manual_col, all_cols)
                    if resolved:
                        col_map[col_name] = resolved
                        if hint:
                            st.caption(hint)
                    else:
                        mapping_errors.append(f"{col_name}：{hint}")
                elif selected != "（跳过此列）":
                    col_map[col_name] = selected
            required_cols = []
            missing = [c for c in required_cols if c not in col_map and c not in fixed_values]
            if mapping_errors:
                for msg in mapping_errors:
                    st.error(msg)
            elif missing:
                st.error(f"⚠️ 请为以下必填列选择对应的Excel列：{missing}")
            else:
                df_import = prepare_import_dataframe(df_import, col_map, col_names, fixed_values)
                st.success(f"✅ 列名映射完成！共 {len(df_import)} 行数据准备导入")
                st.caption("💡 若 Excel 中没有 Recall 类型列，可将「业务线」映射到「调单类型」；系统会自动识别并修正。")
                preview_df = df_import.copy()
                preview_df["调单类型"], preview_df["业务线"] = zip(*preview_df.apply(normalize_import_fields, axis=1))
                st.dataframe(preview_df.head(10), use_container_width=True)
                with st.expander("🔍 查看即将写入的第 1 条数据"):
                    sample_record = row_to_import_record(preview_df.iloc[0])
                    st.write("**应用字段：**")
                    st.json(sample_record)
                    st.write("**实际写入数据库的字段：**")
                    st.json(to_db_record(sample_record))
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    start_import = st.button("🚀 开始导入", type="primary", key="import_start_btn")
                with btn_col2:
                    test_import = st.button("🧪 测试写入 1 条", key="import_test_btn")
                if test_import:
                    result = import_dataframe(preview_df.head(1))
                    if result["success_count"] > 0:
                        st.success("✅ 测试写入成功！可以开始全量导入。")
                    else:
                        st.error("❌ 测试写入失败")
                        show_db_error_help(result["error_samples"])
                if start_import:
                    result = import_dataframe(preview_df)
                    st.markdown("### 导入结果")
                    st.write(
                        f"- 待导入：**{result['total_rows']}** 条\n"
                        f"- 成功：**{result['success_count']}** 条\n"
                        f"- 跳过重复：**{result['skip_count']}** 条\n"
                        f"- 失败：**{result['fail_count']}** 条"
                    )
                    if result["success_count"] > 0:
                        st.success(f"✅ 已成功导入 {result['success_count']} 条数据")
                        st.balloons()
                    elif result["fail_count"] > 0:
                        st.error("❌ 所有数据写入失败，请查看下方错误信息")
                    elif result["skip_count"] > 0:
                        st.warning("⚠️ 所有数据均已存在，未新增记录")
                    else:
                        st.warning("⚠️ 未写入任何数据")
                    show_db_error_help(result["error_samples"])
        except Exception as e:
            st.error(f"❌ 读取文件失败：{e}")
            st.write("详细错误：", e)

# ============================================================
# PAGE 4: 查看全部数据
# ============================================================
elif page == "📄 查看全部数据":
    st.header("📄 全部调单数据")
    df = load_all_data()
    if len(df) >= SUPABASE_PAGE_SIZE:
        st.caption(f"已从数据库分页加载 **{len(df):,}** 条记录（Supabase 单次最多返回 {SUPABASE_PAGE_SIZE} 条，已自动合并）")
    tab_data, tab_clear = st.tabs(["📋 数据列表", "🗑️ 清空数据"])

    with tab_data:
        if len(df) == 0:
            st.info("暂无数据")
        else:
            work_df = df.copy()
            work_df["金额"] = pd.to_numeric(work_df["金额"], errors="coerce").fillna(0)
            date_series = pd.to_datetime(work_df["收件日期"], errors="coerce")
            valid_dates = date_series.dropna()
            today = datetime.date.today()
            if len(valid_dates) > 0:
                data_min = valid_dates.min().date()
                data_max = valid_dates.max().date()
            else:
                data_min = data_max = today
            default_start = data_min
            default_end = data_max

            st.subheader("🔎 筛选搜索")
            fcol1, fcol2, fcol3, fcol4 = st.columns(4)
            with fcol1:
                date_range = st.date_input(
                    "收件日期",
                    value=(default_start, default_end),
                    min_value=data_min,
                    max_value=data_max,
                    key="all_data_date_range",
                )
                range_start, range_end = normalize_date_range(date_range, default_start, default_end)
            with fcol2:
                biz_list = ["全部"] + sorted(work_df["业务线"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().unique().tolist())
                selected_biz = st.selectbox("业务线", biz_list, key="all_data_biz")
            with fcol3:
                type_list = ["全部"] + sorted(work_df["调单类型"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().unique().tolist())
                selected_type = st.selectbox("调单类型", type_list, key="all_data_type")
            with fcol4:
                channel_list = ["全部"] + sorted(work_df["渠道"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().unique().tolist())
                selected_channel = st.selectbox("渠道", channel_list, key="all_data_channel")
            keyword = st.text_input(
                "关键词搜索",
                placeholder="搜索商户ID、商户名称、邮件标题、渠道、调单内容…",
                key="all_data_keyword",
            )
            filtered_df = apply_all_data_filters(
                work_df, range_start, range_end, selected_biz, selected_type, selected_channel, keyword
            )
            st.write(f"筛选结果：**{len(filtered_df)}** / {len(work_df)} 条")
            if len(filtered_df) == 0:
                st.warning("没有符合筛选条件的数据，请调整筛选条件")
                if selected_type != "全部":
                    full_type_count = count_by_filters(work_df, data_min, data_max, "全部", selected_type, "全部", "")
                    if full_type_count > 0:
                        st.info(f"提示：调单类型「{selected_type}」在全量日期范围内共有 **{full_type_count}** 条，请将「收件日期」扩大到 {data_min} ~ {data_max}")
                st.stop()
            st.info("💡 可直接在下方表格中修改数据，修改完成后点击「保存修改」写入数据库")
            type_options = sorted(set(STAT_TYPE_OPTIONS) | set(work_df['调单类型'].dropna().astype(str)))
            biz_options = sorted(set(["电商", "B2B", "服贸汇兑", "其他"]) | set(work_df['业务线'].dropna().astype(str)))
            content_options = sorted(set([c for c in CONTENT_CATEGORIES if c]) | set(work_df['调单内容分类'].dropna().astype(str)))
            currency_options = sorted(set(CURRENCY_OPTIONS) | set(work_df['币种'].dropna().astype(str)))
            display_df = filtered_df.copy()
            edited_df = st.data_editor(
                display_df,
                use_container_width=True,
                height=500,
                num_rows="fixed",
                disabled=["id", "登记时间"],
                column_config={
                    "id": st.column_config.NumberColumn("ID", disabled=True),
                    "收件日期": st.column_config.TextColumn("收件日期"),
                    "商户ID": st.column_config.TextColumn("商户ID"),
                    "商户名称": st.column_config.TextColumn("商户名称"),
                    "调单类型": st.column_config.SelectboxColumn("调单类型", options=type_options),
                    "金额": st.column_config.NumberColumn("金额", format="%.2f"),
                    "币种": st.column_config.SelectboxColumn("币种", options=currency_options),
                    "业务线": st.column_config.SelectboxColumn("业务线", options=biz_options),
                    "渠道": st.column_config.TextColumn("渠道"),
                    "邮件标题": st.column_config.TextColumn("邮件标题"),
                    "调单内容分类": st.column_config.SelectboxColumn("调单内容分类", options=[""] + content_options),
                    "调单内容详情": st.column_config.TextColumn("调单内容详情", width="large"),
                    "登记时间": st.column_config.TextColumn("登记时间", disabled=True),
                },
                key="all_data_editor",
            )
            btn_col1, btn_col2 = st.columns([1, 1])
            with btn_col1:
                if st.button("💾 保存修改", type="primary"):
                    if len(edited_df) == 0:
                        st.info("没有数据可保存")
                    else:
                        updated = save_edited_records(edited_df)
                        if updated > 0:
                            st.success(f"✅ 已更新 {updated} 条记录")
                            st.rerun()
                        else:
                            st.info("没有检测到变更")
            with btn_col2:
                csv = edited_df.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 导出筛选结果", csv, "调单数据.csv", "text/csv")
            st.markdown("---")
            st.subheader("删除单条记录")
            col1, col2 = st.columns([1, 3])
            with col1:
                delete_id = st.number_input("输入要删除的ID", min_value=1, step=1)
                if st.button("删除所选ID"):
                    if delete_data(delete_id):
                        st.success(f"已删除ID {delete_id}")
                        st.rerun()

    with tab_clear:
        st.write(f"当前数据库共有 **{len(df)}** 条记录")
        if len(df) == 0:
            st.info("暂无数据可清空")
        else:
            st.error("⚠️ 危险操作：将永久删除全部调单记录，不可恢复！")
            st.markdown("建议清空前先到「数据列表」Tab 导出 CSV 备份。")
            confirm_clear = st.checkbox("我已了解风险，确认清空全部数据", key="confirm_clear_all")
            confirm_text = st.text_input("请输入「清空全部」以确认", placeholder="清空全部", key="confirm_clear_text")
            can_clear = confirm_clear and confirm_text.strip() == "清空全部"
            if st.button("🗑️ 一键清空全部数据", type="primary", disabled=not can_clear):
                ok, err = delete_all_data()
                if ok:
                    st.success("✅ 已清空全部数据")
                    st.rerun()
                else:
                    st.error(f"❌ 清空失败：{err}")
                    show_db_error_help([err] if err else [])

# ============================================================
# PAGE 5: 回复渠道调单
# ============================================================
elif page == "📧 回复渠道调单":
    st.header("📧 回复渠道调单")
    st.markdown("""
    📌 使用说明：
    1. 选择渠道 → 自动加载对应的模板列表
    2. 选择模板 → 模板内容会显示在编辑框中
    3. 你可以在编辑框中自由修改内容
    4. 点击「复制到剪贴板」按钮复制最终内容
    """)
    col1, col2 = st.columns([1, 2])
    with col1:
        channel_list = sorted(CHANNEL_TEMPLATES.keys())
        selected_channel = st.selectbox("选择渠道", channel_list)
        if selected_channel in CHANNEL_TEMPLATES:
            template_names = list(CHANNEL_TEMPLATES[selected_channel].keys())
            selected_template_name = st.selectbox("选择模板", template_names)
            if selected_template_name:
                template_content = CHANNEL_TEMPLATES[selected_channel][selected_template_name]
                with st.expander("📄 查看模板预览"):
                    st.text(template_content)
    with col2:
        st.subheader("✏️ 编辑草稿")
        if selected_channel in CHANNEL_TEMPLATES and selected_template_name:
            default_content = CHANNEL_TEMPLATES[selected_channel][selected_template_name]
        else:
            default_content = ""
        edited_content = st.text_area("草稿内容（可直接编辑修改）", value=default_content, height=400, key="channel_draft")
        col_btn1, col_btn2, col_btn3 = st.columns(3)
        with col_btn1:
            if st.button("📋 复制到剪贴板", type="primary"):
                st.write("✅ 请手动按 Ctrl+C 复制上面的内容")
                st.code(edited_content, language="text")
        with col_btn2:
            if st.button("🔄 重置为模板"):
                st.rerun()
        with col_btn3:
            if st.button("💾 保存草稿"):
                st.session_state['channel_draft_saved'] = edited_content
                st.success("✅ 草稿已保存到当前会话（刷新后丢失）")

# ============================================================
# PAGE 6: 对客RFI
# ============================================================
elif page == "📨 对客RFI":
    st.header("📨 对客RFI（对内调单模板）")
    st.caption("选择模板后，在右侧模拟邮箱界面填写并发送")
    email_defaults = get_rfi_email_defaults()
    col1, col2 = st.columns([1, 2])
    with col1:
        rfi_categories = {
            "📁 电商相关": ["电商店铺材料", "PayPal入账", "CNY order", "电商Bene mismatch"],
            "📁 交易对手相关": ["个人汇款方", "个人疑似命中制裁", "PSP入账", "交易目的-Bene mismatch"],
            "📁 服务贸易": ["软件服务", "咨询服务", "广告服务"],
            "📁 在途交易": ["单笔Pyvio incoming", "B2B单笔在途", "驰安汇单笔调单", "HIPAYX调单"],
            "📁 风控调查": ["对内RFI通用", "警方协查", "结汇调单", "欺诈Recall"]
        }
        category_options = []
        for cat, items in rfi_categories.items():
            for item in items:
                category_options.append(f"{cat} - {item}")
        selected_option = st.selectbox("选择调单场景", category_options)
        selected_template = selected_option.split(" - ")[-1] if " - " in selected_option else selected_option
        rfi_type = st.selectbox("调单类型", STAT_TYPE_OPTIONS, key="rfi_type")
        if selected_template in INTERNAL_RFI_TEMPLATES:
            with st.expander("📄 查看模板预览"):
                st.text(INTERNAL_RFI_TEMPLATES[selected_template])
    with col2:
        if selected_template in INTERNAL_RFI_TEMPLATES:
            default_content = INTERNAL_RFI_TEMPLATES[selected_template]
        else:
            default_content = ""
        if "rfi_mail_to" not in st.session_state:
            st.session_state["rfi_mail_to"] = email_defaults["to"]
        if "rfi_mail_cc" not in st.session_state:
            st.session_state["rfi_mail_cc"] = email_defaults["cc"]
        default_subject = f"【RFI】{selected_template} - {rfi_type}"

        st.markdown("""
        <style>
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background: #fafafa;
        }
        </style>
        """, unsafe_allow_html=True)

        with st.container(border=True):
            st.markdown("##### ✉️ 新邮件")
            rfi_contacts, contacts_csv_path, contacts_error = get_rfi_contacts_meta()
            if rfi_contacts:
                source_name = os.path.basename(contacts_csv_path) if contacts_csv_path else CONTACTS_CSV_NAME
                st.caption(f"📇 已加载通讯录 **{len(rfi_contacts)}** 个邮箱（CSV：{source_name} + 手动添加）")
            else:
                st.error(contacts_error or f"通讯录为空，请将「{CONTACTS_CSV_NAME}」与 app.py 放在同一目录并 git push")
                if contacts_csv_path:
                    st.caption(f"检测到文件：{contacts_csv_path}")
            mail_to = st.text_input(
                "收件人",
                placeholder="输入姓名或邮箱关键字匹配通讯录，如 yy；多个收件人用逗号分隔",
                key="rfi_mail_to",
                label_visibility="visible",
            )
            render_rfi_recipient_contact_picker(rfi_contacts)
            with st.expander("➕ 添加联系人到通讯录"):
                add_col1, add_col2, add_col3 = st.columns([1.2, 2, 0.8])
                with add_col1:
                    new_contact_name = st.text_input("姓名", key="rfi_new_contact_name", placeholder="如：张三")
                with add_col2:
                    new_contact_email = st.text_input("邮箱", key="rfi_new_contact_email", placeholder="name@company.com")
                with add_col3:
                    st.write("")
                    st.write("")
                    if st.button("保存", key="rfi_save_contact", use_container_width=True):
                        ok, msg = add_rfi_custom_contact(new_contact_name, new_contact_email)
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
            mail_cc = st.text_input(
                "抄送",
                placeholder="可选，多个用逗号分隔",
                key="rfi_mail_cc",
            )
            mail_subject = st.text_input("主题", value=default_subject, key="rfi_mail_subject")

            edited_content = st.text_area(
                "正文",
                value=default_content,
                height=360,
                key="rfi_draft",
                label_visibility="visible",
            )
            mailto_url, body_truncated = build_mailto_url_safe(
                mail_to, mail_cc, mail_subject, edited_content
            )
            tool_col1, tool_col2, tool_col3, tool_col4, tool_col5, tool_col6 = st.columns([1.4, 1.2, 1, 1, 1, 0.8])
            with tool_col1:
                st.link_button("📧 打开邮件客户端", mailto_url, type="primary", use_container_width=True)
            with tool_col2:
                st.link_button("🌐 网易网页邮箱", email_defaults["webmail_url"], use_container_width=True)
            with tool_col3:
                if st.button("📋 复制正文", use_container_width=True):
                    st.session_state["rfi_copy_hint"] = edited_content
            with tool_col4:
                if st.button("📧 插入类型", use_container_width=True):
                    st.session_state["rfi_draft"] = edited_content + f"\n\n调单类型：{rfi_type}"
                    st.rerun()
            with tool_col5:
                if st.button("💾 存草稿", use_container_width=True):
                    st.session_state["rfi_draft_saved"] = edited_content
                    st.success("已保存")
            with tool_col6:
                if st.button("🔄 重置", use_container_width=True):
                    st.rerun()

        if body_truncated:
            st.warning("正文较长，mailto 仅填入收件人/抄送/主题，正文请点「复制正文」后粘贴。")
        if not normalize_email_list(mail_to):
            st.info("💡 请先填写收件人。")
        st.caption("将网易邮箱大师设为 Windows 默认邮件程序后，「打开邮件客户端」可自动填入各字段。")
        if st.session_state.get("rfi_copy_hint"):
            st.code(st.session_state["rfi_copy_hint"], language="text")
        if "rfi_draft_saved" in st.session_state:
            st.info("💡 已恢复之前保存的草稿")