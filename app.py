import streamlit as st
import pandas as pd
import datetime
import json
import os
import re
import urllib.request
from st_supabase_connection import SupabaseConnection

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
st.warning("✅ 测试版本 v1.0 - 2026-07-06")
# ========== 初始化 Supabase 连接 ==========
conn = st.connection("supabase", type=SupabaseConnection)

# ========== 数据读取 ==========
@st.cache_data(ttl=60)
def load_all_data():
    try:
        result = conn.query("*", table="diaodan", ttl="60s")
        df = pd.DataFrame(result.data)
        if len(df) == 0:
            return pd.DataFrame()
        # 确保列存在
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
        conn.table("diaodan").insert(data).execute()
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"保存数据失败：{e}")
        return False

def delete_data(id):
    try:
        conn.table("diaodan").delete().eq("id", id).execute()
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"删除失败：{e}")
        return False

def save_edited_records(edited_df):
    """批量更新编辑后的数据"""
    if len(edited_df) == 0:
        return 0
    updated_count = 0
    for _, row in edited_df.iterrows():
        try:
            rid = int(row['id'])
            # 构建更新数据
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
            conn.table("diaodan").update(update_data).eq("id", rid).execute()
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
    "Argentine Peso": "ARS",
    "Australian Dollar": "AUD",
    "Bahraini Dinar": "BHD",
    "Botswana Pula": "BWP",
    "Brazilian Real": "BRL",
    "Bruneian Dollar": "BND",
    "Canadian Dollar": "CAD",
    "Chilean Peso": "CLP",
    "Chinese Yuan Renminbi": "CNY",
    "Colombian Peso": "COP",
    "Czech Koruna": "CZK",
    "Danish Krone": "DKK",
    "Euro": "EUR",
    "Hong Kong Dollar": "HKD",
    "Hungarian Forint": "HUF",
    "Icelandic Krona": "ISK",
    "Indian Rupee": "INR",
    "Indonesian Rupiah": "IDR",
    "Iranian Rial": "IRR",
    "Israeli Shekel": "ILS",
    "Japanese Yen": "JPY",
    "Kazakhstani Tenge": "KZT",
    "South Korean Won": "KRW",
    "Kuwaiti Dinar": "KWD",
    "Libyan Dinar": "LYD",
    "Malaysian Ringgit": "MYR",
    "Mauritian Rupee": "MUR",
    "Mexican Peso": "MXN",
    "Nepalese Rupee": "NPR",
    "New Zealand Dollar": "NZD",
    "Norwegian Krone": "NOK",
    "Omani Rial": "OMR",
    "Pakistani Rupee": "PKR",
    "Philippine Peso": "PHP",
    "Polish Zloty": "PLN",
    "Qatari Riyal": "QAR",
    "Romanian New Leu": "RON",
    "Russian Ruble": "RUB",
    "Saudi Arabian Riyal": "SAR",
    "Singapore Dollar": "SGD",
    "South African Rand": "ZAR",
    "Sri Lankan Rupee": "LKR",
    "Swedish Krona": "SEK",
    "Swiss Franc": "CHF",
    "Taiwan New Dollar": "TWD",
    "Thai Baht": "THB",
    "Trinidadian Dollar": "TTD",
    "Turkish Lira": "TRY",
    "Emirati Dirham": "AED",
    "British Pound": "GBP",
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

# ========== 模板数据（保持原样，省略以节省空间） ==========
# 由于模板数据非常长，这里保留你原有的 CHANNEL_TEMPLATES 和 INTERNAL_RFI_TEMPLATES
# 请从你原来的 app.py 中复制这两个字典替换此处

# ========== 侧边栏导航 ==========
page = st.sidebar.radio(
    "📌 功能导航",
    ["📊 调单看板", "📝 登记调单", "📤 导入历史数据", "📄 查看全部数据", "📧 回复渠道调单", "📨 对客RFI"]
)

# ============================================================
# PAGE 1: 调单看板
# ============================================================
if page == "📊 调单看板":
    df = load_all_data()

    if len(df) == 0:
        st.header("📊 调单监控看板")
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
        date_range = st.date_input(
            "日期范围",
            value=(default_start, default_end),
            min_value=data_min,
            max_value=data_max,
        )
        range_start, range_end = normalize_date_range(date_range, default_start, default_end)
    with fcol2:
        biz_list = ["全部"] + sorted(df['业务线'].dropna().unique().tolist())
        selected_biz = st.selectbox("业务线", biz_list)
    with fcol3:
        type_list = ["全部"] + sorted(df['调单类型'].dropna().unique().tolist())
        selected_type = st.selectbox("调单类型", type_list)
    with fcol4:
        channel_list = ["全部"] + sorted(
            df['渠道'].dropna().astype(str).str.strip().replace('', pd.NA).dropna().unique().tolist()
        )
        selected_channel = st.selectbox("渠道", channel_list)

    period_label = format_date_range_label(range_start, range_end)
    st.header(f"📊 调单监控看板 · {period_label}")

    filtered = df.copy()
    filtered = filtered[
        filtered['收件日期'].notna()
        & (filtered['收件日期'].dt.date >= range_start)
        & (filtered['收件日期'].dt.date <= range_end)
    ]
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
        if rates_error:
            st.caption("⚠️ 汇率获取失败，暂按原币金额显示")
        else:
            caption = f"汇率来源：[x-rates.com]({XRATES_URL})"
            if rates_updated_at:
                caption += f"，更新于 {rates_updated_at} UTC"
            st.caption(caption)
        if missing_currencies:
            st.warning(f"以下币种暂无汇率，未计入 USD 总金额：{', '.join(missing_currencies)}")
    with col4:
        recall_count = len(filtered[filtered['调单类型'] == "Recall"])
        st.metric("🔄 Recall笔数", f"{recall_count:,}")

    with st.expander(f"📋 查看筛选结果明细（共 {len(filtered):,} 条）", expanded=False):
        if len(filtered) == 0:
            st.info("当前筛选条件下暂无数据")
        else:
            detail_df = filtered.copy()
            if '收件日期' in detail_df.columns:
                detail_df['收件日期'] = detail_df['收件日期'].dt.strftime('%Y-%m-%d')
            if '金额_USD' in detail_df.columns:
                detail_df['金额_USD'] = detail_df['金额_USD'].round(2)
            detail_cols = [
                'id', '收件日期', '商户ID', '商户名称', '调单类型', '调单内容分类',
                '金额', '币种', '金额_USD', '业务线', '渠道', '邮件标题', '调单内容详情', '登记时间',
            ]
            present_cols = [c for c in detail_cols if c in detail_df.columns]
            detail_df = detail_df[present_cols].sort_values('id', ascending=False)
            st.dataframe(detail_df, use_container_width=True, height=450, hide_index=True)
            csv = detail_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                "📥 导出当前筛选结果",
                csv,
                f"调单明细_{datetime.date.today()}.csv",
                "text/csv",
                key="dashboard_filtered_export",
            )

    st.subheader("📊 业务线 × 调单类型汇总")
    biz_type_summary = build_biz_type_summary(filtered)
    if len(biz_type_summary) == 0:
        st.info("当前筛选条件下暂无数据")
    else:
        st.dataframe(biz_type_summary, use_container_width=True, hide_index=True)
    
    tab1, tab2 = st.tabs(["📈 趋势分析", "📊 分布分析"])
    
    with tab1:
        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("每日调单笔数")
            if '收件日期' in filtered.columns and len(filtered) > 0:
                trend = (
                    filtered.groupby(filtered['收件日期'].dt.date)
                    .size()
                    .reset_index(name='笔数')
                )
                trend.columns = ['日期', '笔数']
                trend['日期'] = trend['日期'].apply(format_month_day)
                if len(trend) > 0:
                    st.bar_chart(trend.set_index('日期'))
        with col_right:
            st.subheader("每日调单金额 (USD)")
            if '收件日期' in filtered.columns and '金额_USD' in filtered.columns and len(filtered) > 0:
                amount_trend = (
                    filtered.groupby(filtered['收件日期'].dt.date)['金额_USD']
                    .sum()
                    .reset_index(name='金额(USD)')
                )
                amount_trend.columns = ['日期', '金额(USD)']
                amount_trend['日期'] = amount_trend['日期'].apply(format_month_day)
                if len(amount_trend) > 0:
                    st.line_chart(amount_trend.set_index('日期'))
    
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
            else:
                st.info("暂无数据")

        with col_right:
            st.subheader("业务线分布")
            biz_dist = filtered['业务线'].value_counts()
            if len(biz_dist) > 0:
                st.bar_chart(biz_dist)
            else:
                st.info("暂无数据")

# ============================================================
# PAGE 2: 登记调单
# ============================================================
elif page == "📝 登记调单":
    st.header("📝 登记新调单")

    调单内容分类 = st.selectbox(
        "调单内容分类",
        CONTENT_CATEGORIES,
        format_func=lambda x: "请选择" if x == "" else x,
    )

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
            内容详情 = {
                "汇款方": 汇款方,
                "收款方": 收款方,
                "交易类型": 交易类型,
                "交易状态": 交易状态,
            }

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
            if save_data(
                str(收件日期),
                商户ID.strip(),
                商户名称.strip(),
                调单类型,
                金额,
                币种,
                业务线,
                渠道.strip(),
                邮件标题.strip(),
                调单内容分类,
                调单内容详情,
            ):
                st.success("✅ 调单登记成功！看板已自动更新")
                st.balloons()

# ============================================================
# PAGE 3: 导入历史数据
# ============================================================
elif page == "📤 导入历史数据":
    st.header("📤 导入历史数据")
    
    st.info("""
    📌 使用说明：
    1. 点击「浏览文件」选择你的 Excel 文件
    2. 选择要导入的 Sheet
    3. 如果系统无法自动识别列名，请手动选择对应的列
    4. 点击「开始导入」
    """)
    
    uploaded_file = st.file_uploader("选择 Excel 文件", type=["xlsx", "xls"])
    
    if uploaded_file is not None:
        try:
            excel_file = pd.ExcelFile(uploaded_file)
            sheet_names = excel_file.sheet_names
            selected_sheet = st.selectbox("选择要导入的 Sheet", sheet_names, index=0 if "（统计用）6张表数据汇总" in sheet_names else 0)
            
            df_import = pd.read_excel(uploaded_file, sheet_name=selected_sheet, engine="openpyxl")
            st.write(f"📊 共读取到 **{len(df_import)}** 行数据")
            
            st.write("**原始列名：**", df_import.columns.tolist())
            st.dataframe(df_import.head(5), use_container_width=True)
            
            st.subheader("🔧 列名映射（如果自动识别失败，请手动选择）")
            
            all_cols = df_import.columns.tolist()
            
            auto_map = {}
            for col in all_cols:
                col_lower = col.lower().strip()
                if '商户id' in col_lower or '商户号' in col_lower or 'merchantid' in col_lower or 'merchant_id' in col_lower:
                    auto_map['商户ID'] = col
                elif '商户名称' in col_lower or '商户名' in col_lower or 'merchantname' in col_lower or 'merchant_name' in col_lower:
                    auto_map['商户名称'] = col
                elif '调单类型' in col_lower or '类型' in col_lower or 'type' in col_lower:
                    auto_map['调单类型'] = col
                elif '收件日期' in col_lower or '调单日期' in col_lower or '日期' in col_lower or 'date' in col_lower:
                    auto_map['收件日期'] = col
                elif '金额' in col_lower or 'amount' in col_lower:
                    auto_map['金额'] = col
                elif '币种' in col_lower or 'currency' in col_lower:
                    auto_map['币种'] = col
                elif '业务线' in col_lower or 'business' in col_lower:
                    auto_map['业务线'] = col
                elif '渠道' in col_lower or 'channel' in col_lower:
                    auto_map['渠道'] = col
                elif '邮件标题' in col_lower or '邮件名称' in col_lower or '邮件' in col_lower or 'title' in col_lower:
                    auto_map['邮件标题'] = col
            
            col_map = {}
            col_names = ["商户ID", "商户名称", "调单类型", "收件日期", "金额", "币种", "业务线", "渠道", "邮件标题"]
            col_help = {
                "商户ID": "必填，如：5181241025033620258",
                "商户名称": "必填，如：宇信數碼有限公司",
                "调单类型": "必填，如：Recall / Personal Information / Retrieval Request",
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
                selected = st.selectbox(
                    f"**{col_name}** - {col_help[col_name]}",
                    options,
                    index=default_index
                )
                if selected != "（跳过此列）":
                    col_map[col_name] = selected
            
            required_cols = ['商户ID', '商户名称', '调单类型']
            missing = [c for c in required_cols if c not in col_map]
            
            if missing:
                st.error(f"⚠️ 请为以下必填列选择对应的Excel列：{missing}")
            else:
                rename_dict = {v: k for k, v in col_map.items()}
                df_import = df_import.rename(columns=rename_dict)
                
                keep_cols = list(col_map.values())
                df_import = df_import[keep_cols]
                
                for col in ['收件日期', '金额', '币种', '业务线', '渠道', '邮件标题']:
                    if col not in df_import.columns:
                        df_import[col] = None
                
                df_import['收件日期'] = pd.to_datetime(df_import['收件日期'], errors='coerce').dt.strftime('%Y-%m-%d')
                
                def clean_amount(value):
                    if value is None or value == '' or pd.isna(value):
                        return 0
                    if isinstance(value, (int, float)):
                        return float(value)
                    if isinstance(value, str):
                        value = value.replace(',', '')
                        parts = value.split('.')
                        if len(parts) > 2:
                            value = ''.join(parts[:-1]) + '.' + parts[-1]
                    try:
                        return float(value)
                    except (ValueError, TypeError):
                        return 0
                
                df_import['金额'] = df_import['金额'].apply(clean_amount)
                
                df_import = df_import.fillna({
                    '金额': 0,
                    '币种': 'USD',
                    '业务线': '其他',
                    '渠道': '',
                    '邮件标题': ''
                })
                
                st.success(f"✅ 列名映射完成！共 {len(df_import)} 行数据准备导入")
                st.dataframe(df_import.head(10), use_container_width=True)
                
                if st.button("🚀 开始导入", type="primary"):
                    # 获取现有数据用于去重
                    existing_df = load_all_data()
                    existing_keys = set(zip(existing_df['商户ID'], existing_df['收件日期'], existing_df['调单类型'])) if len(existing_df) > 0 else set()
                    
                    success_count = 0
                    skip_count = 0
                    
                    for _, row in df_import.iterrows():
                        key = (str(row['商户ID']), str(row['收件日期']), str(row['调单类型']))
                        if key in existing_keys:
                            skip_count += 1
                            continue
                        
                        try:
                            data = {
                                "收件日期": str(row['收件日期']),
                                "商户ID": str(row['商户ID']),
                                "商户名称": str(row['商户名称']),
                                "调单类型": str(row['调单类型']),
                                "金额": float(row['金额']) if pd.notna(row['金额']) else 0,
                                "币种": str(row['币种']),
                                "业务线": str(row['业务线']),
                                "渠道": str(row['渠道']),
                                "邮件标题": str(row['邮件标题']),
                                "调单内容分类": "",
                                "调单内容详情": "",
                                "登记时间": datetime.datetime.now().isoformat()
                            }
                            conn.table("diaodan").insert(data).execute()
                            success_count += 1
                        except Exception as e:
                            st.warning(f"导入失败：{e}")
                            continue
                    
                    st.cache_data.clear()
                    st.success(f"✅ 导入完成！成功导入 {success_count} 条，跳过重复 {skip_count} 条")
                    st.balloons()
                    
        except Exception as e:
            st.error(f"❌ 读取文件失败：{e}")
            st.write("详细错误：", e)

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
    st.info("💡 可直接在下方表格中修改数据，修改完成后点击「保存修改」写入数据库")

    type_options = sorted(set(STAT_TYPE_OPTIONS) | set(df['调单类型'].dropna().astype(str)))
    biz_options = sorted(set(["电商", "B2B", "服贸汇兑", "其他"]) | set(df['业务线'].dropna().astype(str)))
    content_options = sorted(set([c for c in CONTENT_CATEGORIES if c]) | set(df['调单内容分类'].dropna().astype(str)))
    currency_options = sorted(set(CURRENCY_OPTIONS) | set(df['币种'].dropna().astype(str)))

    display_df = df.copy()
    display_df['金额'] = pd.to_numeric(display_df['金额'], errors='coerce').fillna(0)

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

    btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 2])
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
        st.download_button("📥 导出为CSV", csv, "调单数据.csv", "text/csv")

    st.markdown("---")
    st.subheader("🗑️ 删除记录")
    col1, col2 = st.columns([1, 3])
    with col1:
        delete_id = st.number_input("输入要删除的ID", min_value=1, step=1)
        if st.button("删除"):
            if delete_data(delete_id):
                st.success(f"已删除ID {delete_id}")
                st.rerun()

elif page == "📧 回复渠道调单":
    st.header("📧 回复渠道调单")
    st.info("该模块模板功能开发中，可参考 Workbook 文档配置渠道回复模板。")

elif page == "📨 对客RFI":
    st.header("📨 对客RFI")
    st.info("该模块模板功能开发中，可参考 Workbook 文档配置对客 RFI 模板。")