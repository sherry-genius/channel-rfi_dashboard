import streamlit as st
import pandas as pd
import sqlite3
import datetime
import json
import os
import re
import urllib.request

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

# ========== 页面配置 ==========
st.set_page_config(page_title="调单管理系统", layout="wide")
st.title("📋 调单管理系统")

# ========== 初始化数据库 ==========
def init_db():
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS diaodan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            收件日期 TEXT,
            商户ID TEXT,
            商户名称 TEXT,
            调单类型 TEXT,
            金额 REAL,
            币种 TEXT,
            业务线 TEXT,
            渠道 TEXT,
            邮件标题 TEXT,
            调单内容分类 TEXT,
            调单内容详情 TEXT,
            登记时间 TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def load_all_data():
    conn = sqlite3.connect('data.db')
    df = pd.read_sql_query("SELECT * FROM diaodan ORDER BY id DESC", conn)
    conn.close()
    return df

def save_data(收件日期, 商户ID, 商户名称, 调单类型, 金额, 币种, 业务线, 渠道, 邮件标题, 调单内容分类="", 调单内容详情=""):
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    c.execute('''
        INSERT INTO diaodan (收件日期, 商户ID, 商户名称, 调单类型, 金额, 币种, 业务线, 渠道, 邮件标题, 调单内容分类, 调单内容详情, 登记时间)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (收件日期, 商户ID, 商户名称, 调单类型, 金额, 币种, 业务线, 渠道, 邮件标题, 调单内容分类, 调单内容详情, datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()

def delete_data(id):
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    c.execute("DELETE FROM diaodan WHERE id = ?", (id,))
    conn.commit()
    conn.close()

EDITABLE_COLUMNS = [
    '收件日期', '商户ID', '商户名称', '调单类型', '金额', '币种',
    '业务线', '渠道', '邮件标题', '调单内容分类', '调单内容详情',
]

def save_edited_records(original_df, edited_df):
    original_df = original_df.set_index('id')
    edited_df = edited_df.set_index('id')
    updated_count = 0
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    for rid in edited_df.index:
        if rid not in original_df.index:
            continue
        orig = original_df.loc[rid]
        edit = edited_df.loc[rid]
        changed = False
        for col in EDITABLE_COLUMNS:
            if col == '金额':
                if float(orig[col] or 0) != float(edit[col] or 0):
                    changed = True
                    break
            elif str(orig[col] if pd.notna(orig[col]) else '') != str(edit[col] if pd.notna(edit[col]) else ''):
                changed = True
                break
        if not changed:
            continue
        row = edit
        c.execute('''
            UPDATE diaodan SET
                收件日期=?, 商户ID=?, 商户名称=?, 调单类型=?, 金额=?, 币种=?,
                业务线=?, 渠道=?, 邮件标题=?, 调单内容分类=?, 调单内容详情=?
            WHERE id=?
        ''', (
            str(row['收件日期']),
            str(row['商户ID']),
            str(row['商户名称']),
            str(row['调单类型']),
            float(row['金额']) if pd.notna(row['金额']) else 0,
            str(row['币种']),
            str(row['业务线']),
            str(row['渠道']),
            str(row['邮件标题']),
            str(row['调单内容分类']) if pd.notna(row['调单内容分类']) else '',
            str(row['调单内容详情']) if pd.notna(row['调单内容详情']) else '',
            int(rid),
        ))
        updated_count += 1
    conn.commit()
    conn.close()
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

# ========== 模板数据 ==========
CHANNEL_TEMPLATES = {
    "DBS": {
        "DBS入账模板": """Dear Team,

Please kindly check the replies below regarding the transaction-.

[Purpose of transaction / usage of fund]
▪ What is the purpose of transaction / usage of fund?  
[Reply: This transaction is a full/partial /deposit balance payment of the PI by the remitter to purchase products with the merchant. Please refer to the PI attached.]

▪ If the transaction involves in underlying goods, please supplement:
detail of underlying goods, and what's the end use of this underlying goods?
[Reply: The underlying goods are ]
[For more product details, please refer to the attached invoice, product images and this web page:]
[The target end user of the underlying goods "XXX" is the Remitter himself/itself.]
[The origin of the goods is China.]

▪ shipment / transportation detail, e.g. origin & destination, port of loading / discharge, vessel / flight involved etc.
[Reply: The products haven't been shipped yet, and the products are expected to be shipped from China to RUSSIA.]
[Reply: The goods will be shipped by our merchant directly to the buyer, from China to Belarus by express.]

▪ If the transaction involves in providing service(s) (e.g. investment / capital injection / loan / consultation etc.), please elaborate in detail.
[Reply: N/A]

▪ If the Remitter / Beneficiary is an individual, please also supplement and provide the supporting documents if any:
[Reply: Please refer to the attached driving license /passport of remitter.]
[Full name:]
[Gender: Female Male]
[Date of Birth:]
[ID / Passport no.：]
[Nationality:]

Relationship between the Remitter & Beneficiary
[Reply: Buyer and supplier.]

▪ Please provide any information which may find relevant to current transaction/customer (e.g. invoice, contract, bill of lading, loan document etc.)
[Reply: Please check the PI attached.]
[The remitter is a supplier of electronic components. ()]
[Reply: Please refer to the attachments for more details. The transaction is consistent with the remitter's business.()]

[Customer Background]
▪ Please state the nature of business of your Customer.
[Reply: The merchant is a supplier of XXX.()]
▪ Is the transaction within the customer's normal trading/profile?
[Reply: YES]

[Sanction Related]
Please confirm that the transaction or the Remitter / Beneficiary has NO direct or indirect exposure to / affiliate with any OFAC sanction regimes, Iran, North Korea, Cuba, Syria or Crimea/ LNR / DNR of Ukraine.
[It is confirmed that the transaction or the Remitter / Beneficiary has NO direct or indirect exposure to / affiliate with any OFAC sanction regimes, Iran, North Korea, Cuba, Syria or Crimea/ LNR / DNR of Ukraine.]""",
        "DBS账户调查": """Dear team,

Please check the attached files and the response highlighted below regarding RFI No- RFIXXXXXX, thanks!

> Please provide the details of the Originator and Beneficiary, including nature of business, Chinese name, any supporting document to supporting their business nature and please provide links if there is any web presence.

[Below are the company details for Beneficiary/Originator:]
> [Nature of business:]
> [Chinese name:]
> [Supporting document to supporting their business nature:]
> [Web presence:]
>
> Kindly advise on the relationship between Originator and Beneficiary, and advise on the purpose of transactions.

[Buyer and supplier.]
[These transactions are partial payments of the invoices by the remitter to purchase products from our merchant(beneficiary).]
[The products involved in these transactions are .]

> Please provide supporting documents to above transactions. For example, contract/agreement, invoice and receipts, proof of shipment/delivery (e.g. Bill of lading, airway bills), customs clearing papers, etc.

[Please refer to the attached proforma invoices and bills of lading.]""",
        "DBS代付解释": """The transaction from LLC NTC was on behalf of LLC OFK-KOMLEKT to purchase furniture wrenches with the PI attached, and it is related to the buyer's business. ()""",
        "DBS VA KYC": """Hi,

该商户收到渠道调单：

请提供：
1、请确认 XX是否有银行业和保险业的从业经历。如有，请告知从业时间和职位。

请务必于 2025 年 XX 月 XX 日 15 点之前配合提供上述订单资料。""",
        "DBS DA Letter": """→林琪琪签字DA letter→打印了签字的版本最后交给陈雯梦寄回DBS"""
    },
    "SCB": {
        "SCB通用模板": """Dear Team,

Please check the response highlighted below, thanks!

Please check the attached files and the responses highlighted below, thanks!

For further information you need, please check the response highlighted below, thanks!""",
        "SCB账户调查": """Dear team,

Please check the attached files and the response highlighted below regarding RFI No- RFIXXXXXX, thanks!

> Please provide the details of the Originator and Beneficiary, including nature of business, annual revenue, net worth, location of operations, Cert of incorp and other KYC certifications; and please provide links if there is any web presence.

[Below are the company details for the Beneficiary/Originator:]
[Full name:]
[Nature of business:]
[Annual revenue:]
[Net worth:]
[Location of operations:]
[Cert of incorp: Its business license/registration certificate is attached.]
[Web presence:]

> Kindly advise on the relationship between Originator and Beneficiary, and advise on the purpose of transactions.

[Supplier and Buyer]
[These transactions are partial payments of the invoices by the remitter to purchase products from our merchant(beneficiary). The products involved in these transactions are .]

> Please provide supporting documents to above transactions. For example, contract/agreement, invoice and receipts, proof of shipment/delivery (e.g. Bill of lading, airway bills), customs clearing papers, etc.

[Please refer to the attached proforma invoices and bills of lading.]"""
    },
    "Banking Circle": {
        "BC通用模板": """Dear Team,

Please check the response highlighted below, thanks!

Please check the attached files and the responses highlighted below, thanks!""",
        "BC警方协查": """Hi Team,

Thank you for your inquiry.

Regarding account [IBAN], the account holder is [Company Name] and sole beneficial owner is [UBO Name]. This business account has been in a frozen status and the account balance is zero. The remittance was from the buyers of our merchant for goods trade and then our merchant made payments to their suppliers.

The detailed entry payments records, business registration documents and identity documents are provided in the attached file for your reference.""",
        "BC KYC": """Hi Team,

Thank you for your inquiry.

Regarding account [IBAN], the account holder is [Company Name] and sole beneficial owner is [UBO Name] (Chinese name: [中文名]). Payful has terminated the relationship with [Company Name] as of [Date]. The account balance was zero at the time of closure.

The information for the beneficial owner is as follows:
Full name: [Name]
Date of birth: [DOB]
Address: [Address]

For your reference, we have attached copies of the last available KYC documents held in our records for this entity."""
    },
    "Citibank": {
        "citi两问": """1. Full detailed purpose of pymt.
[To purchase products from our merchant.]

2. Please provide the details of product or goods that involve if any.
[The goods involved are]

1. Please obtain the detailed purpose of payment (please avoid generic words / languages like luxury goods, consumer goods, business payments, etc.)
2. Please specify the goods / services involved, if any""",
        "citi入账拦截KYC": """Full detailed purpose of payment.
Please confirm whether the remitter has any nexus, relationship, affiliation with or owned by the entity XXX (AKA - ) located in XXX.
Please obtain full name of remitter
Full physical address INCLUDING country of location.
Please obtain remitter's company website, if any.
Please advise the ownership information(name and percentage) of
Remitter line of business.""",
        "citi疑似OFAC": """1. Complete purpose of payment
Payment for led lighting products.

2. Copy of related invoice and related contract between the two parties
Please refer to the attached PI.

3. Confirmation of the OFAC Specific or General License applies to the activity
As you can see the swift code shown in F52 BAGAGE22XXX, it is the SWIFT code of JSC Bank of Georgia, not the OFAC sanctioned bank UGEBGE22XXX.

VTB bank in F72 is subject to the OFAC regimes.
Please reject this transaction. Thanks.""",
        "citi账户调查": """1. the details of the beneficiary of the Payer ID number (such as, the name of beneficiary, Company registry no., date & place of incorporation, business nature, Address, Tel No., Email address and the details of the owner of the company (surname & first name, gender, DOB, ID No., country of the ID document and etc.)),

[Full Chinese & English name of beneficiary:]
[Company registry no.:]
[Date & place of incorporation:]
[Business nature:]
[Address:]
[Tel No.:]
[Email address:]
[The details of the owner of the company (surname & first name, gender, DOB, ID No., country of the ID document and etc.): Chinese]
[The beneficiary's business license and its owner's ID are attached.]

2. the details of the ultimate originator
[Full name:]
[Address:]
[Business nature: ]

3. how many Payer IDs for this beneficiary have,
[Only one]

4. how long of this beneficiary being a client of XTransfer,
[since]

5. the purpose of transaction,
[To purchase products from our merchant(the beneficiary). The goods involved are .]

6. please provide the business proof (invoice, contract, bill of lading, customs clearance document and etc.),
[Please refer to the attached proforma invoice and bills of lading.]

7. XTransfer's assessment for the transaction & beneficiary (whether XTransfer has noticed any suspicion on the transaction and beneficiary)
[This transaction is related to our merchant's normal trading.]
[The transaction is within the customer's normal trading/profile.]
[The activity is consistent with the expected activity of the customer profile.]

8. please advise the status of Payer ID /merchant with XTransfer. If the relationship was terminated, please provide the screen shot shown the date of exit.
[Still active.]"""
    },
    "GME": {
        "GME KYC": """Please review the following information for the merchant:

- Merchant Name: [Name]
- Date of Birth: [DOB]
- Address: [Address]

The merchant's ID photo attached to this email for your reference.
Please be advised that we have frozen the associated account.
Should you require any additional materials, please do not hesitate to contact us.""",
        "GME警方协查": """Thanks for your email.

We have taken immediate action to freeze the account and suspend all transactions as a precautionary measure. However, please be advised that the available balance is currently zero, as the funds were already withdrawn by the merchant.

Account information:
- IBAN: [IBAN]
- Account holder: [Company Name]
- 100% UBO: [UBO Name]
- Account opening date: [Date]
- Current balance: Zero
- Address: [Address]

For your reference, the relevant KYC documents and transaction details have been included in the attachment."""
    },
    "巴克莱": {
        "巴克莱联系邮箱": """financialinstitutionsservicing@barclays.com
aysha.begum2@barclays.com
karen.palmer@barclays.com
waihang.chan@barclays.com
kit.lin@barclays.com"""
    },
    "Thunes": {
        "Thunes出款说明": """邮件中的Sender = 客户
Transaction ID [ID] and Transaction External ID [外部ID]
用【Transaction ID】>> 【渠道流水号】
用【Transaction External ID】>> 【付款批次号】"""
    },
    "通用": {
        "礼貌感谢": """Thank you for your email.
Thank you for providing this update./ Thank you for your update.
Thank you for providing this information./ Thank you for this information. I sincerely appreciate it.
Thank you for confirming. / Thanks in advance for the confirmation.
Thank you for getting back to us so quickly.
Your assistance in this matter is much appreciated./Your assistance on this matter is highly appreciated.
Thank you for your update again. We will rely the details to our compliance team for further review accordingly.
Have a nice weekend ahead!
Thank you so much for the details. Highly appreciated!
Thank you for your assistance and we look forward to your prompt response.""",
        "催促邮件": """-May I know whether you are able to provide an update on the below please? Thanks.
-May I know any updates on the following transaction? Thanks!
-Any updates on the following transaction? Thanks!
-Any updates on this inquiry? Could you help confirm if the holding fund has been released? Thanks!
-As the beneficiary has not received the fund yet, Could you help to update the latest status of this transaction? Thanks!
-As the beneficiary has not received the fund yet, Could you help to reject this transaction? If you have rejected this payment, could you inform us at the same time?
Looking forward to your reply. Thanks!
-Could you help to check the latest status of this payment? Looking forward to your reply. Thanks!
-As the remitter still has not received the returned funds, there is a dispute between the merchant and the remitter, could you help to provide the MT202 to prove that the fund had been returned? Thanks!
-As the fund has been pending for four months, we are under tremendous pressure from the merchant. Could you help to update the latest status of this transaction? Thanks!
-Could you please check the status of this transaction or when it will be processed?
-Sorry to bother you again. Could you please assist to update status of below payment? Since it has been pending for more than a week, the merchant is very anxious about this fund.""",
        "延期邮件": """Hi team,

Thank you for your email.

We are still waiting for the merchant to provide the material. Could you please extend the deadline? We will continue to contact our merchant and reply to the email as soon as we get the materials from the merchant.

Thank you for your understanding.

[周末延期]
Since [Date] falls on the weekend, our merchant hasn't been able to prepare the required materials in time. Would it be possible to request an extension on the deadline?

[节假日延期]
We would like to inform you that our merchant is currently on holiday for the [Holiday] and will be back on [Date]. Once they return, we will ask them to prepare the necessary documents and provide you with an update as soon as possible.

Thank you very much for your understanding.""",
        "退款监控": """Our investigation concluded that the merchant did not actively participate in the fraud awareness, and the merchant also agreed to refund.
The merchant has truthfully provided part of the communication records. The reason for the subsequent uncooperation is that the merchant is afraid of disclosing the buyer's information.
Based on the above, we have decided not to terminate our relationship with the merchant for the time being, and have sent the merchant a warning email. At the same time, we will continue to monitor the merchant more strictly and terminate the relationship with the merchant in the next case of non-compliance.""",
        "无法定位商户": """Regarding RFI No- RFIXXXXXX, as we could not find the beneficiary's name and id in our system, could you assist to re-confirm the beneficiary id for this inquiry? Thank you.""",
        "退款销户": """Therefore, we have suspended the merchant's account on [Date].
Due to the internal policy, the transaction is prohibited and we decided to close the merchant's account.
Actually, the transaction was rejected immediately, when we found it is not acceptable by following our internal policy after the merchant claimed the fund. We closed the merchant's account as we found he is not our target customer, and even didn't gather more information about the buyer.

For your query, please find the response highlighted below. Hope it helps.""",
        "前次邮件有误需重发": """Please disregard my previous email and refer to this one instead. I apologize for any confusion this may have caused. Thanks for your time.""",
        "预期管理": """For RFIXXXXXX, We are still awaiting the merchant to reply some related materials. We will keep you updated about the status and reply to the email as soon as we get the materials from the merchant. Our merchant has indicated that due to family matters, he cannot provide us with materials this week, and expect to be able to respond by next Wednesday.

Thank you ahead for your understanding.

[节假日自动回复]
Dear Team,
Thank you for your email. Please be informed that our team are currently OOO for the [Holiday] from [Date] to [Date].
We will reply to your email as soon as possible after returning to office.
Thank you for your understanding!""",
        "GEP交易监测官话": """(1)KYC/KYB Procedures: We perform Know Your Customer (KYC) and Know Your Business (KYB) checks on all merchants during the onboarding phase to verify their identity and ensure compliance with legal and regulatory requirements.
(2)Transaction Monitoring: Our automated systems continuously track transaction activities, flagging any unusual or suspicious behavior that deviates from the merchant's expected business profile or operational norms. If any abnormalities are detected, we request additional information and necessary supporting evidence from the merchant.
(3)Ongoing Merchant Reviews: We conduct regular reviews and maintain communication with merchants through our sales and account management teams to ensure continuous compliance.""",
        "GEP Sanction监测": """We have effective measures in place for sanctions compliance. We conduct real-time sanctions screening as part of our ongoing transaction monitoring and perform daily updates to our database. Our systems are designed to automatically block transactions if the counterparty is on any sanctions list at the time of processing.

For existing customers, screening is performed when the list database is updated, or screening is performed regularly according to the customer's risk rating. All existing GEP customers' names, including those of individuals, entities, beneficial owners, and authorised persons, are screened daily via an automated screening system.""",
        "GEP Fraud Controls": """I would like to highlight some of the Anti-Fraud control measures that GEP is currently implementing:

Information Verification: Customers register through the GEP official website and provide the requested related identification information/documents. The collected information/documents will be delivered to the compliance operations system. Compliance analysts will verify documents, data, and information through reliable and independent sources, such as governmental bodies and authorised databases.

Biometric and liveness solutions: GEP has implemented a Biometric facial recognition process during the customer onboarding process. Customers (Natural Persons), company authorised persons, UBOs, directors, or legal representatives must undergo facial recognition via a computer or mobile device equipped with a camera.

GeoIP detection: GEP has developed an IP verification tool to detect abnormal customer logins based on IP address detection rules.

Ongoing Transaction Monitoring: When the transaction monitoring system identifies a transaction that contravenes a rule or threshold within the system, an alert would automatically be generated. The alert shall be manually analysed by a Compliance AML Analyst."""
    }
}

# ========== 对客RFI模板 ==========
INTERNAL_RFI_TEMPLATES = {
    "电商店铺材料": """- 请提供您/您代理商的在线商店链接，如您有代理商，请同时提供代理协议
- 请提供您/您代理商的商店的后台截图，其中应显示用于从平台接收销售收入的银行账户信息，包括但不限于银行名称、分行名称、账号和您/您代理商的公司/商户名称
- 请提供从平台到您/您代理商的银行账户的提现记录，其中应包括您/您代理商的公司/商家名称
- 请提供从您/您代理商的银行账户到GEP账户的提款记录，其中应包括上述提到的您/您代理商的银行账户信息，以及该银行账户近1到2个月内的完整账单""",
    "个人汇款方": """-请确认交易对手方为个人，个体工商户还是公司。
--[若交易对手方为个人代表公司交易，请提供该公司全名并解释为何使用个人账户做商业用途。
--若交易对手方为个人交易，请解释他/她如何与其商业伙伴建立合作关系""",
    "软件服务": """- 请提供交易对手方全名
- 请说明业务关系，交易目的，以及涉及的产品或服务
- 请提供交易相关证明文件
-- 若涉及服务交易（例如：投资、注资、贷款或咨询、网页或软件服务、广告服务等)，请提供: 相关服务(或代理)合同以及发票
-- 若涉及网页或软件服务，请提供过程文件或测试文件，URL等""",
    "咨询服务": """- 请提供交易对手方全名
- 请说明业务关系，交易目的，以及涉及的产品或服务
- 请提供交易相关证明文件
-- 若涉及服务交易（例如：投资、注资、贷款或咨询、网页或软件服务、广告服务等)，请提供: 相关服务(或代理)合同以及发票
-- 若涉及咨询服务，请提供具体服务内容及相关服务介绍材料或交付物样本""",
    "广告服务": """- 请提供交易对手方全名
- 请说明业务关系，交易目的，以及涉及的产品或服务
- 请提供交易相关证明文件
-- 若涉及服务交易（例如：投资、注资、贷款或咨询、网页或软件服务、广告服务等)，请提供: 相关服务(或代理)合同以及发票，同时请提供的广告服务业务支持文件，例如，广告收费标准或广告账户充值截图（截图应该能体现客户和交易方的名字）""",
    "PayPal入账": """- 店铺网站
- PayPal提现记录(有账户持有人的名字)
- 请解释您和打款人之间的关系并提供符合商业情理的相关服务(或代理)合同/代运营协议(签署日期须在打款日期之前且甲乙双方的权责须符合业务关系)""",
    "交易目的-Bene mismatch": """- 请说明交易目的，以及涉及的产品或服务
- 请说明付款方，收款方和您的三方关系
- 请提供交易相关证明材料
-- 若涉及货物交易，请提供合同，发票，货运证明（物流信息或报关单）
-- 若涉及电商交易，请同时提供销售网站
-- 若涉及服务贸易，请同时提供服务协议或代理协议。""",
    "CNY order": """- 请提供商品页面的截图或商品链接
- 请提供包含全部金额的完整客户订单截图
- 请提供货运单号及货运跟踪信息截图""",
    "PSP入账": """- 请确认实际付款方的全名
-- 若实际付款方与您的Airwallex账户名相同，请提供汇款账户近3个月的对账单
-- 若为第三方汇款，请提供交易水单、涉及的产品或服务以及相关证明，例如：合同及发票""",
    "对内RFI通用": """【交易目的】
请补充交易支持性材料
-- 若涉及服务贸易，请提供双方合作协议
-- 若涉及货物贸易，请补充提供采购合同和物流信息

请补充以下材料：
1. 请说明业务关系，交易目的，以及涉及的产品或服务
2. 收款方为支付机构，请提供实际收款方的后台收款记录截图
3. 请提供交易相关证明文件
-- 若涉及货物交易，请提供合同，发票，货运证明（物流信息或报关单）
-- 若涉及服务交易（例如：投资、注资、贷款或咨询、网页或软件服务、广告服务等)，请提供相关服务(或代理)合同，发票，服务交付材料（广告平台后台截图/软件设计过程文件或测试文件等）
-- 若涉及电商交易，请同时提供销售网站，订单截图（含物流信息）等""",
    "个人疑似命中制裁": """Hi,

该商户以下在途入账收到渠道调单：
汇款人：XXX
金额：XXX

请提供：
1、护照或ID；
2、请填写以下信息：
(i) Date of birth*
(ii) Citizenship
(iii) Country of Residence
(iv) Nationality*
(v) Unique identification number and type of identity document*
(vi) Place of birth
(vii) Gender*

为确保客户及时收到该笔资金，请务必于 2025 年 XX 月 XX 日 12 点之前配合提供上述订单资料。为防止邮件遗漏，回复邮件后烦请企业微信提醒，感谢配合！""",
    "单笔Pyvio incoming": """Hi,

以下在途资金收到渠道调单：
汇款方：
金额：

请补充以下材料：

1. 请确认付款方为个人，个体工商户还是公司
-- 若为个体工商户或公司，请提供更多背景信息，如网站/注册证明书
-- 若为个人，请确认付款方是代表公司付款还是自用，如代表公司请提供公司名称以及个人与公司的关系

2. 请提供该笔入账对应订单PI/CI/采购合同（发票金额需与此笔入账款项金额一致；如不一致，需在PI/CI说明对应的汇款安排），invoice中买卖双方信息需分别对应贵司及汇款人；

3. 请提供物流信息。若该笔订单已发货，请提供相应的出境段物流单据；若本次暂未发货，则提供贵司与买家关于货运物流安排、买家指定收货人的沟通记录截图；若是老买家可将历史出境段物流单据一并补充；

4. 请提供该笔订单与买家沟通询盘下单记录（需要展示沟通时间、双方身份、订单细节的沟通）；

5. 请提供该笔款项的买家提供的汇款水单以及买家发送该水单的沟通记录截图，或者买家确认汇款的沟通记录截图；

为确保客户及时收到该笔资金，请务必于 2025 年 XX 月 XX 日 17 点之前配合提供上述订单资料。

如客户未能在截止时间提供或超时提供订单资料，将会导致银行审查时间进一步延长，或者可能导致此笔转账被银行退回，请知悉。""",
    "B2B单笔在途": """Hi,

该客户以下在途XX收到渠道调单：
对手方：
金额：

请补充以下材料：
1、请告知该批货物的最终用途；
2、请提供采购合同或发票（发票金额需与抽查的入账款项金额一致；如不一致，需在PI/CI说明对应的汇款安排），发票中买卖双方信息需分别对应贵司及汇款人；
3、请提供物流信息：（1）海运提单/空运提单；（2）报关单【两者务必都要提供】

为确保客户及时收到该笔资金，请务必于 2025 年 XX 月 XX 日 17 点之前配合提供上述订单资料。为防止邮件遗漏，回复邮件后烦请企业微信提醒，感谢配合！""",
    "电商Bene mismatch": """Hi,

该客户以下在途入账收到渠道调单：
对手方：
金额：
收款方：

请补充以下材料：
1、请解释汇款方、贵司与收款方的三方关系，并提供相关证明；
2、关于收款方XXX，请提供：
（1）全称；
（2）公司注册号；
（3）地址。

为确保客户及时收到该笔资金，请务必于 2025 年 3 月 10 日 12 点之前配合提供上述订单资料。""",
    "驰安汇单笔调单": """Hi,

以下在途付款收到渠道调单：
金额：XXX
收款方：XXX

请提供：
（1）学生汇款方的全名；
（2）学生汇款方的出生年月日

为确保客户及时收到该笔资金，请务必于 2025 年 XX 月 XX 日 17 点之前配合提供上述订单资料。""",
    "HIPAYX调单": """Hi,

该商户现收到渠道调单，调单涉及交易如下：

烦请协助核实补充以下内容：
1、提供汇款人在HIPAYX的Onboarding界面，以及其注册证书+股东、法人等身份信息资料；
2、提供对应交易双签的合作协议；
3、佐证本单贸易背景的其他补充资料：

#若为货物贸易：
①提供对应订单完整的沟通记录，包括不限于：询盘议价传递PI、确认收货地址、沟通付款传递水单等等
②告知货物原产地，货物的用途，最终用户，并提供对应的物流单证。
A、若本单尚未发货，提供发买家近期的物流单证；
B、若是历史没有任何发货记录，则提供本次订单安排物流发货细节的沟通记录，包括不限于：沟通发货方式(海运、陆运、空运)、预计运输路线(始发港卸货港、始发中转机场等)、预计发货时间等等

#若为服务贸易：
①告知提供服务的地点②对应服务验收相关的资料等等

（注：邮件谈单，需展示邮箱域名信息、邮件落款、时间日期、头像昵称等；聊天软件沟通，需展示双方头像，邮箱，电话，简介等，请勿只截取部分）

以上，请务必于 2025 年 XX 月 XX 日 15 点之前配合反馈上述资料。若超时回复我部可能将采取风控措施，渠道调单请注意时效！""",
    "警方协查": """Hi,

商户【xxxxxxxxxx】因交易涉及重大风险，今收到境外警方协查，账户已暂时冻结。警方协查信息完成前，商户结算暂时关闭，请知悉。

VA： xxxxxx + 名称

请配合提供上述账户持有人的如下信息：
1. pictures of the ID card/passport
2. phone numbers
3. name
4. birthday
5. birthplace
6. addresses

请务必于2025年XX月XX日17：00之前配合提供以上信息，警方协查请注意所提供信息的完整性和真实性。""",
    "结汇调单": """Hi，

以下X笔交易收到汇付调单：

[商户ID/名称] [交易订单号] [收款方名称] [文件批次号]
请补充以下文件：

【广告订单部分】
1、请提供对应订单的广告平台的广告消耗和广告结算截图（截图应该能体现客户和交易方的名字，广告组消耗金额应能对上实际交易金额）。

【与收款方部分】
1、请提供与收款方的合作协议（含签章和日期）。

请于明天 2025 年 XX 月 XX 日 16：00 前提供相应材料，渠道调单请注意时效，感谢配合！""",
    "欺诈Recall": """Hi,

渠道风险调单，请联系商户提供以下材料：
1. 本笔贸易对应PI，物流面单，报关单等物流运输材料
2. 下单询盘沟通记录
3. 汇款司网站，联系方式等信息
4. 请确认是否同意召回，对方发起召回的原因，以及双方关于款项召回事宜的沟通记录截图

下单询盘请包含关于双方身份，产品细节，单价，总金额，运输方式，打款方式等信息，截图请包括双方头像/邮箱域名/买家信息页截图，日期等。

【当前已冻结账户内对应的XXX的金额，请知悉。】

紧急调单，请于 XX 年 XX 月 XX 日之前提供材料，期间该账户所有出款pending，谢谢配合！"""
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
    df['年月'] = df['收件日期'].dt.strftime('%Y年%m月')

    st.subheader("🔎 筛选条件")
    fcol1, fcol2, fcol3, fcol4 = st.columns(4)
    with fcol1:
        month_list = ["全部"] + sorted(df['年月'].dropna().unique().tolist(), reverse=True)
        selected_month = st.selectbox("年月", month_list)
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

    filtered = df.copy()
    if selected_month != "全部":
        filtered = filtered[filtered['年月'] == selected_month]
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
            st.subheader("每月调单笔数")
            if '收件日期' in filtered.columns:
                trend = filtered.groupby('年月').size().reset_index(name='笔数')
                if len(trend) > 0:
                    st.bar_chart(trend.set_index('年月'))
        with col_right:
            st.subheader("每月调单金额 (USD)")
            if '收件日期' in filtered.columns and '金额_USD' in filtered.columns:
                amount_trend = filtered.groupby('年月')['金额_USD'].sum().reset_index(name='金额(USD)')
                if len(amount_trend) > 0:
                    st.line_chart(amount_trend.set_index('年月'))
    
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
            save_data(
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
            )
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
                    conn = sqlite3.connect('data.db')
                    c = conn.cursor()
                    
                    existing = pd.read_sql_query("SELECT 商户ID, 收件日期, 调单类型 FROM diaodan", conn)
                    existing_keys = set(zip(existing['商户ID'], existing['收件日期'], existing['调单类型']))
                    
                    success_count = 0
                    skip_count = 0
                    
                    for _, row in df_import.iterrows():
                        key = (str(row['商户ID']), str(row['收件日期']), str(row['调单类型']))
                        if key in existing_keys:
                            skip_count += 1
                            continue
                        
                        c.execute('''
                            INSERT INTO diaodan (收件日期, 商户ID, 商户名称, 调单类型, 金额, 币种, 业务线, 渠道, 邮件标题, 登记时间)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            str(row['收件日期']),
                            str(row['商户ID']),
                            str(row['商户名称']),
                            str(row['调单类型']),
                            float(row['金额']) if pd.notna(row['金额']) else 0,
                            str(row['币种']),
                            str(row['业务线']),
                            str(row['渠道']),
                            str(row['邮件标题']),
                            datetime.datetime.now().isoformat()
                        ))
                        success_count += 1
                    
                    conn.commit()
                    conn.close()
                    
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
            updated = save_edited_records(display_df, edited_df)
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
            delete_data(delete_id)
            st.success(f"已删除ID {delete_id}")
            st.rerun()

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
        # 渠道选择
        channel_list = sorted(CHANNEL_TEMPLATES.keys())
        selected_channel = st.selectbox("选择渠道", channel_list)
        
        # 模板选择（根据渠道动态加载）
        if selected_channel in CHANNEL_TEMPLATES:
            template_names = list(CHANNEL_TEMPLATES[selected_channel].keys())
            selected_template_name = st.selectbox("选择模板", template_names)
            
            # 如果选择了模板，显示模板内容
            if selected_template_name:
                template_content = CHANNEL_TEMPLATES[selected_channel][selected_template_name]
                
                # 显示模板预览
                with st.expander("📄 查看模板预览"):
                    st.text(template_content)
    
    with col2:
        st.subheader("✏️ 编辑草稿")
        
        # 获取当前模板内容
        if selected_channel in CHANNEL_TEMPLATES and selected_template_name:
            default_content = CHANNEL_TEMPLATES[selected_channel][selected_template_name]
        else:
            default_content = ""
        
        # 可编辑的文本框
        edited_content = st.text_area(
            "草稿内容（可直接编辑修改）",
            value=default_content,
            height=400,
            key="channel_draft"
        )
        
        # 按钮行
        col_btn1, col_btn2, col_btn3 = st.columns(3)
        with col_btn1:
            if st.button("📋 复制到剪贴板", type="primary"):
                st.write("✅ 请手动按 Ctrl+C 复制上面的内容")
                st.code(edited_content, language="text")
        with col_btn2:
            if st.button("🔄 重置为模板"):
                st.rerun()
        with col_btn3:
            # 保存草稿到session_state
            if st.button("💾 保存草稿"):
                st.session_state['channel_draft_saved'] = edited_content
                st.success("✅ 草稿已保存到当前会话（刷新后丢失）")

# ============================================================
# PAGE 6: 对客RFI
# ============================================================
elif page == "📨 对客RFI":
    st.header("📨 对客RFI（对内调单模板）")
    
    st.markdown("""
    📌 使用说明：
    1. 选择调单场景 → 自动加载对应的模板
    2. 在编辑框中删减或增加内容
    3. 选择调单类型后，可直接复制发给销售
    """)
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        # 场景分类（按大类分组）
        rfi_categories = {
            "📁 电商相关": ["电商店铺材料", "PayPal入账", "CNY order", "电商Bene mismatch"],
            "📁 交易对手相关": ["个人汇款方", "个人疑似命中制裁", "PSP入账", "交易目的-Bene mismatch"],
            "📁 服务贸易": ["软件服务", "咨询服务", "广告服务"],
            "📁 在途交易": ["单笔Pyvio incoming", "B2B单笔在途", "驰安汇单笔调单", "HIPAYX调单"],
            "📁 风控调查": ["对内RFI通用", "警方协查", "结汇调单", "欺诈Recall"]
        }
        
        # 展平分类选择
        category_options = []
        for cat, items in rfi_categories.items():
            for item in items:
                category_options.append(f"{cat} - {item}")
        
        selected_option = st.selectbox("选择调单场景", category_options)
        
        # 提取实际模板名
        selected_template = selected_option.split(" - ")[-1] if " - " in selected_option else selected_option
        
        # 显示模板预览
        if selected_template in INTERNAL_RFI_TEMPLATES:
            with st.expander("📄 查看模板预览"):
                st.text(INTERNAL_RFI_TEMPLATES[selected_template])
    
    with col2:
        st.subheader("✏️ 编辑草稿")
        
        # 获取当前模板内容
        if selected_template in INTERNAL_RFI_TEMPLATES:
            default_content = INTERNAL_RFI_TEMPLATES[selected_template]
        else:
            default_content = ""
        
        # 调单类型选择（对客RFI额外）
        rfi_type = st.selectbox("调单类型（选择后插入模板）", STAT_TYPE_OPTIONS, key="rfi_type")
        
        # 可编辑的文本框
        edited_content = st.text_area(
            "草稿内容（可直接编辑修改）",
            value=default_content,
            height=400,
            key="rfi_draft"
        )
        
        # 快捷操作按钮
        col_btn1, col_btn2, col_btn3, col_btn4 = st.columns(4)
        with col_btn1:
            if st.button("📋 复制", type="primary"):
                st.write("✅ 请手动按 Ctrl+C 复制上面的内容")
                st.code(edited_content, language="text")
        with col_btn2:
            if st.button("🔄 重置"):
                st.rerun()
        with col_btn3:
            if st.button("💾 保存草稿"):
                st.session_state['rfi_draft_saved'] = edited_content
                st.success("✅ 草稿已保存")
        with col_btn4:
            if st.button("📧 插入调单类型"):
                # 在内容末尾插入调单类型
                new_content = edited_content + f"\n\n调单类型：{rfi_type}"
                st.session_state['rfi_draft'] = new_content
                st.rerun()
        
        # 如果session_state中有草稿，恢复它
        if 'rfi_draft_saved' in st.session_state:
            st.info("💡 已恢复之前保存的草稿")