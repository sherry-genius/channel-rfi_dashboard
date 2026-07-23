import streamlit as st
import pandas as pd
import datetime
import json
import os
import re
import urllib.request
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

# ========== 页面配置 ==========
st.set_page_config(page_title="调单管理系统", layout="wide")
st.title("📋 调单管理系统")
st.warning("✅ 测试版本 v1.0.0 - 2026-07-06")

# ========== 初始化 Supabase 连接 ==========
try:
    SUPABASE_URL = st.secrets["connections"]["supabase"]["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["connections"]["supabase"]["SUPABASE_KEY"]
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    st.success("✅ Supabase 连接成功")
except Exception as e:
    st.error(f"❌ Supabase 连接失败：{e}")
    st.stop()

# ========== 数据读取 ==========
@st.cache_data(ttl=60)
def load_all_data():
    try:
        response = supabase.table("diaodan").select("*").execute()
        df = pd.DataFrame(response.data)
        if len(df) == 0:
            return pd.DataFrame()
        required_cols = ['id', '收件日期', '商户ID', '商户名称', '调单类型', '金额', '币种', '业务线', '渠道', '邮件标题', '调单内容分类', '调单内容详情', '登记时间']
        for col in required_cols:
            if col not in df.columns:
                df[col] = None
        return df
    except Exception as e:
        st.error(f"读取数据失败：{e}")
        return pd.DataFrame()

def save_data(收件日期, 商户ID, 商户名称, 调单类型, 金额, 币种, 业务线, 渠道, 邮件标题, 调单内容分类="", 调单内容详情=""):
    try:
        data = {
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
            "登记时间": datetime.datetime.now().isoformat()
        }
        supabase.table("diaodan").insert(data).execute()
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"保存数据失败：{e}")
        return False

def delete_data(id):
    try:
        supabase.table("diaodan").delete().eq("id", id).execute()
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"删除失败：{e}")
        return False

def save_edited_records(edited_df):
    if len(edited_df) == 0:
        return 0
    updated_count = 0
    for _, row in edited_df.iterrows():
        try:
            rid = int(row['id'])
            update_data = {
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
            }
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

# ========== 侧边栏导航 ==========
page = st.sidebar.radio(
    "📌 功能导航",
    ["📊 调单看板", "📝 登记调单", "📤 导入历史数据", "📄 查看全部数据"]
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
            if len(trend) > 0:
                st.bar_chart(trend.set_index('收件日期'))
        with col_right:
            st.subheader("每月调单金额 (USD)")
            amount_trend = filtered.groupby(filtered['收件日期'].dt.strftime('%Y年%m月'))['金额_USD'].sum().reset_index(name='金额(USD)')
            if len(amount_trend) > 0:
                st.line_chart(amount_trend.set_index('收件日期'))
    with tab2:
        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("调单类型分布")
            type_dist = filtered['调单类型'].value_counts()
            if len(type_dist) > 0:
                st.write(type_dist.to_frame())
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
    with st.form("登记表单", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            收件日期 = st.date_input("收件日期", datetime.date.today())
            商户ID = st.text_input("商户ID *", placeholder="如：5181241025033620258")
            商户名称 = st.text_input("商户名称 *", placeholder="如：宇信數碼有限公司")
            调单类型 = st.selectbox("调单类型", STAT_TYPE_OPTIONS)
        with col2:
            金额 = st.number_input("金额", min_value=0.0, step=0.01, value=0.0)
            币种 = st.selectbox("币种", CURRENCY_OPTIONS, index=CURRENCY_OPTIONS.index("USD"))
            业务线 = st.selectbox("业务线", ["电商", "B2B", "服贸汇兑"])
            渠道 = st.text_input("渠道", placeholder="如：Banking Circle")
        邮件标题 = st.text_input("邮件标题（可选）")
        submitted = st.form_submit_button("✅ 提交调单")
        if submitted:
            if not 商户ID or not 商户名称:
                st.error("⚠️ 商户ID和商户名称不能为空")
            else:
                if save_data(str(收件日期), 商户ID.strip(), 商户名称.strip(), 调单类型, 金额, 币种, 业务线, 渠道.strip(), 邮件标题.strip()):
                    st.success("✅ 调单登记成功！")
                    st.balloons()

# ============================================================
# PAGE 3: 导入历史数据
# ============================================================
elif page == "📤 导入历史数据":
    st.header("📤 导入历史数据")
    st.info("点击「浏览文件」选择你的 Excel 文件，然后选择要导入的 Sheet，点击「开始导入」")
    uploaded_file = st.file_uploader("选择 Excel 文件", type=["xlsx", "xls"], key="import_file")
    if uploaded_file is not None:
        try:
            excel_file = pd.ExcelFile(uploaded_file)
            sheet_names = excel_file.sheet_names
            selected_sheet = st.selectbox("选择要导入的 Sheet", sheet_names, index=0 if "（统计用）6张表数据汇总" in sheet_names else 0)
            df_import = pd.read_excel(uploaded_file, sheet_name=selected_sheet, engine="openpyxl")
            st.write(f"📊 共读取到 **{len(df_import)}** 行数据")
            st.dataframe(df_import.head(5), use_container_width=True)
            if st.button("🚀 开始导入", type="primary"):
                existing_df = load_all_data()
                existing_keys = set(zip(existing_df['商户ID'], existing_df['收件日期'], existing_df['调单类型'])) if len(existing_df) > 0 else set()
                success_count = 0
                skip_count = 0
                for _, row in df_import.iterrows():
                    key = (str(row.get('商户ID', '')), str(row.get('收件日期', '')), str(row.get('调单类型', '')))
                    if key in existing_keys:
                        skip_count += 1
                        continue
                    try:
                        data = {
                            "收件日期": str(row.get('收件日期', '')),
                            "商户ID": str(row.get('商户ID', '')),
                            "商户名称": str(row.get('商户名称', '')),
                            "调单类型": str(row.get('调单类型', '')),
                            "金额": float(row.get('金额', 0)) if pd.notna(row.get('金额', 0)) else 0,
                            "币种": str(row.get('币种', 'USD')),
                            "业务线": str(row.get('业务线', '其他')),
                            "渠道": str(row.get('渠道', '')),
                            "邮件标题": str(row.get('邮件标题', '')),
                            "调单内容分类": "",
                            "调单内容详情": "",
                            "登记时间": datetime.datetime.now().isoformat()
                        }
                        supabase.table("diaodan").insert(data).execute()
                        success_count += 1
                    except Exception as e:
                        continue
                st.cache_data.clear()
                st.success(f"✅ 导入完成！成功导入 {success_count} 条，跳过重复 {skip_count} 条")
                st.balloons()
        except Exception as e:
            st.error(f"❌ 读取文件失败：{e}")

# ============================================================
# PAGE 4: 查看全部数据
# ============================================================
elif page == "📄 查看全部数据":
    st.header("📄 全部调单数据")
    df = load_all_data()
    if len(df) == 0:
        st.info("暂无数据")
        st.stop()
    st.write(f"共 **{len(df)}** 条记录")
    st.dataframe(df, use_container_width=True, height=500)
    csv = df.to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 导出为CSV", csv, "调单数据.csv", "text/csv")