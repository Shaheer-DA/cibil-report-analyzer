# app.py
# ------------------------------
# CIBIL Report Analyzer (Red/White Pro UI)
# ------------------------------

import io
import json
from datetime import datetime, timedelta
from collections import Counter, defaultdict

import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import xlsxwriter

# For PDF export
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
)

# ==============================
# ---------- Helpers ----------
# ==============================

def safe_int(x, default=0):
    try:
        if isinstance(x, str):
            x = x.replace("₹", "").replace("Rs.", "").replace(",", "").strip()
        return int(float(x))
    except Exception:
        return default

def r(x):
    # Rupee formatting (use Rs. instead of ₹ for PDF safety)
    try:
        xi = safe_int(x, 0)
        return f"Rs.{xi:,}"
    except Exception:
        return "Rs.0"

def to_date(d):
    for fmt in ("%Y-%m-%d", "%Y-%m", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(d), fmt).date()
        except Exception:
            pass
    return None

def col(df, name, default=None):
    return df[name] if name in df.columns else default

def convert_df_to_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")

def convert_df_to_excel(df: pd.DataFrame) -> bytes:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Accounts")
    return out.getvalue()

# ==============================
# ---- Core Analysis Logic ----
# ==============================
# Loan Type Abbreviation Mapping
def abbreviate_account_type(account_type: str) -> str:
    mapping = {
        "Personal Loan": "PL",
        "Business Loan – Secured": "BL Secured",
        "Business Loan – Priority Sector – Agriculture": "BL Agri",
        "Business Loan – Priority Sector – Others": "BL PS Other",
        "Credit Card": "CC",
        "Auto Loan": "AL",
        "Education Loan": "EL",
        "Home Loan": "HL",
        "Loan Against Property": "LAP",
        "Gold Loan": "GL",
        "Consumer Loan": "CL",
    }
    return mapping.get(account_type, account_type[:12] + "…") if account_type else "NA"


def analyze_report(data: dict, reference_date: datetime.date):
    report_date = reference_date
    accounts = []
    enquiries = []
    score = None
    total_past_due_summary = 0
    person_name = "N/A"

    try:
        credit_report = data.get("reportData", {}).get("credit_report", {})
        score = data.get("reportData", {}).get("credit_score", None)
        response = credit_report.get("CCRResponse", {})
        cir_list = response.get("CIRReportDataLst", [])
        if cir_list:
            cir = cir_list[0]
            cir_data = cir.get("CIRReportData", {})
            accounts = cir_data.get("RetailAccountDetails", []) or []
            total_past_due_summary = safe_int(
                cir_data.get("RetailAccountsSummary", {}).get("TotalPastDue", 0), 0
            )
            person_name = (
                cir_data.get("IDAndContactInfo", {})
                .get("PersonalInfo", {})
                .get("Name", {})
                .get("FullName", "N/A")
            )
        enquiries = credit_report.get("Enquiries", []) or []
    except Exception:
        pass

    active_count, active_sanction_total, total_emi = 0, 0, 0
    dpd30_6m, dpd30_12m, max_dpd_12m = 0, 0, 0
    missed_count = 0
    write_off_accounts = set()
    portfolio = defaultdict(int)
    util_ratios = []
    lender_exposure = Counter()
    all_accounts_rows = []
    missed_rows = []
    # --- NEW: Initialize counters ---
    loans_availed_last_3m, pl_bl_availed_last_6m = 0, 0

    for acc in accounts:
        acc_type = acc.get("AccountType") or acc.get("Type") or "Other"
        lender = acc.get("Institution") or acc.get("Financer") or acc.get("BankName") or "N/A"
        is_open = (acc.get("Open") == "Yes") or (acc.get("Status") or "").lower() == "open"
        status = "Open" if is_open else "Closed"

        installment_amt = safe_int(acc.get("InstallmentAmount"), 0)
        last_payment_amt = safe_int(acc.get("LastPayment"), 0)
        emi = installment_amt if installment_amt > 0 else last_payment_amt if last_payment_amt > 0 else 0

        row = {
            "Financer": str(lender),
            "Account Type": str(acc_type),
            "Status": status,
            "Date Opened": acc.get("DateOpened") or acc.get("DateOpenedOrDisbursed") or "-",
            "Sanction Amount": r(acc.get("SanctionAmount")),
            "Installment / Last Payment": r(emi),
            "Current Balance": r(acc.get("Balance")),
            "Overdue": r(acc.get("PastDueAmount"))
        }
        all_accounts_rows.append(row)

        portfolio[acc_type] += 1
        
        # --- NEW: Logic for recent loans ---
        date_opened_str = acc.get('DateOpened')
        if date_opened_str:
            date_opened = datetime.strptime(date_opened_str, '%Y-%m-%d').date()
            if date_opened >= (report_date - timedelta(days=90)):
                loans_availed_last_3m += 1
            if date_opened >= (report_date - timedelta(days=180)) and ('Personal Loan' in acc_type or 'Business Loan' in acc_type):
                 pl_bl_availed_last_6m += 1

        if is_open:
            active_count += 1
            active_sanction_total += safe_int(acc.get("SanctionAmount"), 0)
            total_emi += emi
            lender_exposure[lender] += safe_int(acc.get("SanctionAmount"), 0)

        for h in acc.get("History48Months", []):
            try:
                dpd = safe_int(h.get("PaymentStatus"), 0)
                dkey = h.get("key")
                d = to_date(dkey) or to_date(f"{dkey}-01")
                if d is None:
                    continue
                if dpd > 0:
                    missed_count += 1
                    missed_rows.append({
                        "Financer": lender,
                        "Account Type": acc_type,
                        "Month/Year": d.strftime("%Y-%m"),
                        "Days Past Due": dpd,
                        "Current Overdue": r(acc.get("PastDueAmount"))
                    })
                if d >= (reference_date - timedelta(days=365)):
                    max_dpd_12m = max(max_dpd_12m, dpd)
                    if dpd >= 30:
                        dpd30_12m += 1
                        if d >= (reference_date - timedelta(days=180)):
                            dpd30_6m += 1
            except Exception:
                continue

        if "credit card" in str(acc_type).lower():
            limit_amt = safe_int(acc.get("HighCredit"), 0)
            bal = safe_int(acc.get("Balance"), 0)
            if limit_amt > 0:
                util_ratios.append(bal / limit_amt)

        try:
            if any(h.get("AssetClassificationStatus") == "LSS" for h in acc.get("History48Months", [])):
                write_off_accounts.add(str(acc.get("AccountNumber")))
        except Exception:
            pass

    enquiries_last_3m = 0
    enquiry_types = Counter()
    for e in enquiries:
        purpose = e.get("enquiryPurpose") or e.get("purpose") or "NA"
        enquiry_types[purpose] += 1
        d = to_date(e.get("enquiryDate")) or to_date(e.get("date"))
        if d and d >= (reference_date - timedelta(days=90)):
            enquiries_last_3m += 1

    utilization = f"{round(np.mean(util_ratios) * 100, 2)}%" if len(util_ratios) > 0 else "N/A"

    results = {
        "name": person_name,
        "score": score if score is not None else "N/A",
        "total_past_due": safe_int(total_past_due_summary, 0),
        "active_loans": active_count,
        "active_sanction_total": active_sanction_total,
        "total_emi": total_emi,
        "missed_payments": missed_count,
        "dpd30_6m": dpd30_6m,
        "dpd30_12m": dpd30_12m,
        "max_dpd_12m": max_dpd_12m,
        "writeoff_count": len(write_off_accounts),
        "portfolio": dict(portfolio),
        "accounts_df": pd.DataFrame(all_accounts_rows),
        "missed_df": pd.DataFrame(missed_rows),
        "utilization": utilization,
        "top_lenders": lender_exposure.most_common(3),
        "enquiries_last_3m": enquiries_last_3m,
        "enquiry_breakdown": dict(enquiry_types),
        "pl_bl_availed_last_6m": pl_bl_availed_last_6m,
        "loans_availed_last_3m": loans_availed_last_3m,
    }
    return results

# ==============================
# --------- PDF Export ---------
# ==============================

def _portfolio_chart_image(series: pd.Series) -> io.BytesIO:
    buf = io.BytesIO()
    if series.empty:
        series = pd.Series({"NA": 0})

    # Apply abbreviations
    labels = [abbreviate_account_type(x) for x in series.index]
    series.index = labels

    plt.figure(figsize=(8, 4))
    bars = plt.bar(series.index, series.values, color="#E63946", edgecolor="black")

    # Add labels on bars
    for bar in bars:
        height = bar.get_height()
        plt.annotate(
            f"{int(height)}",
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 3),  # offset above bar
            textcoords="offset points",
            ha="center", va="bottom", fontsize=8, color="black", fontweight="bold"
        )

    plt.title("Loan Portfolio Distribution", fontsize=12, fontweight="bold", color="#E63946")
    plt.ylabel("Count of Loans")
    plt.xlabel("Loan Type")
    plt.xticks(rotation=30, ha="right", fontsize=9)
    plt.tight_layout()

    plt.savefig(buf, format="png", dpi=150)
    plt.close()
    buf.seek(0)
    return buf


def export_pdf(results: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Wrap", fontName="Helvetica", fontSize=8, leading=10, wordWrap="CJK"))
    story = []

    header = f"CIBIL Report Summary – {results['name']}"
    story.append(Paragraph(f"<font size=18 color='#E63946'><b>{header}</b></font>", styles["Title"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"<font size=10 color='grey'>Generated on {datetime.today().strftime('%d %b %Y')}</font>", styles["Normal"]))
    story.append(Spacer(1, 16))

    kpis = [
        ("CIBIL Score", results["score"]),
        ("Enquiries (Last 3M)", results["enquiries_last_3m"]),
        ("Total Past Due", r(results["total_past_due"])),
        ("Total EMI", r(results["total_emi"])),
        ("30+ DPD (6M)", results["dpd30_6m"]),
        ("30+ DPD (12M)", results["dpd30_12m"]),
        ("Max DPD (12M)", results["max_dpd_12m"]),
        ("Write-offs", results["writeoff_count"]),
        ("Credit Utilization", results["utilization"]),
    ]
    kpi_tbl = Table(
        [list(x) for x in zip(*[iter([k for k, v in kpis])] * 3)] +
        [list(x) for x in zip(*[iter([str(v) for k, v in kpis])] * 3)],
        colWidths=[160, 160, 160]
    )
    kpi_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#E63946")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
    ]))
    story.append(kpi_tbl)
    story.append(Spacer(1, 16))

    portfolio_series = pd.Series(results["portfolio"])
    if not portfolio_series.empty:
        img_buf = _portfolio_chart_image(portfolio_series)
        story.append(Paragraph("<b>Loan Portfolio Distribution</b>", styles["Heading2"]))
        story.append(Image(img_buf, width=5.5*inch, height=2.7*inch))
        story.append(Spacer(1, 12))

    accounts = results["accounts_df"].copy()
    accounts = accounts[accounts["Status"] =="Open"].head(30)
    if not accounts.empty:
        story.append(Paragraph("<b>Accounts (sample)</b>", styles["Heading2"]))
        account_data = [list(accounts.columns)]
        for row in accounts.astype(str).values.tolist():
            wrapped_row = []
            for idx, cell in enumerate(row):
                if idx == 1:  # Account Type column
                    wrapped_row.append(Paragraph(cell, styles["Wrap"]))
                else:
                    wrapped_row.append(Paragraph(cell, styles["Normal"]))
            account_data.append(wrapped_row)

        acct_tbl = Table(account_data, colWidths=[100, 140, 60, 80, 90, 110, 90, 80])
        acct_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#E63946")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
            ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
        ]))
        story.append(acct_tbl)
        story.append(Spacer(1, 12))

    story.append(Spacer(1, 18))
    story.append(Paragraph(
        "<font size=8 color='grey'>Report generated by CIBIL Report Analyzer – Confidential</font>",
        styles["Normal"]
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

# ==============================
# ----------- UI/UX -----------
# ==============================

st.set_page_config(page_title="CIBIL Report Analyzer", layout="wide")

# Pro red & white theme with better typography + cards
st.markdown(
    """
<style>
/* Google Fonts */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=Manrope:wght@600;700&display=swap');

:root{
  --accent:#E63946;
  --accent-600:#D62839;
  --ink:#1a1a1a;
  --muted:#6b6b6b;
  --bg:#ffffff;
  --card:#fafafa;
  --ring:#ffd4d7;
}
html, body, [class*="css"]  {
  font-family: 'Inter', system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
  color: var(--ink);
}
section.main > div { padding-top: 12px; }
h1, h2, h3 { font-family: 'Manrope', 'Inter', sans-serif; letter-spacing: .2px; }
.stTabs [role="tablist"] {
  gap: 6px;
}
.stTabs [role="tab"] {
  background: #ffffff;
  color: var(--ink);
  border: 1px solid #eee;
  border-bottom: 2px solid transparent;
  border-radius: 12px 12px 0 0;
  padding: 10px 16px;
  font-weight: 600;
}
.stTabs [aria-selected="true"] {
  border-bottom: 2px solid var(--accent) !important;
  color: var(--accent) !important;
}
.card {
  border: 1px solid #eee; border-radius: 16px; padding: 18px 18px;
  background: var(--card);
  box-shadow: 0 1px 0 rgba(0,0,0,.02), 0 8px 24px -20px rgba(0,0,0,.2);
}
.kpi {
  display: flex; align-items: center; gap: 12px;
}
.kpi .dot {
  width: 12px; height: 12px; border-radius: 50%; background: var(--accent);
  box-shadow: 0 0 0 6px var(--ring);
}
.kpi .title {
  color: #6b6b6b;       /* Dark gray for labels */
  font-size: .85rem;
  font-weight: 500;
}

.kpi .value {
  color: #E63946;       /* Red accent for values */
  font-size: 1.6rem;
  font-weight: 700;
  letter-spacing: .3px;
}
.stButton>button {
  background: var(--accent); color: white; border: none; border-radius: 10px;
  padding: 10px 14px; font-weight: 600;
}
.stButton>button:hover { background: var(--accent-600); }
thead th { background: var(--accent) !important; color: white !important; }
</style>
""",
    unsafe_allow_html=True,
)

st.title("CIBIL Report Analyzer")

# --- Sidebar: upload/paste + reset
st.sidebar.header("Upload or Paste Report")
uploaded = st.sidebar.file_uploader("Upload CIBIL JSON", type=["json"])
pasted = st.sidebar.text_area("Or paste JSON here")

if st.sidebar.button("🔄 Analyze Another Report"):
    # Clear and hard rerun (replaces deprecated experimental_rerun)
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()

# Load data
data = None
if uploaded:
    data = json.load(uploaded)
elif pasted.strip():
    try:
        data = json.loads(pasted)
    except Exception:
        st.error("Invalid JSON pasted. Please check the content and try again.")

if not data:
    st.info("Upload a CIBIL JSON file or paste the JSON in the sidebar to get started.")
    st.stop()

# Analyze
today = datetime.today().date()
res = analyze_report(data, today)

# ==============================
# ---- Summary (Cards Row) ----
# ==============================

c1, c2, c3, c4 = st.columns([1.2, 1, 1, 1])
with c1:
    st.markdown(
        f"""
        <div class="card kpi">
          <div class="dot"></div>
          <div>
            <div class="title">Customer</div>
            <div class="value">{res['name']}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with c2:
    st.markdown(
        f"""
        <div class="card kpi">
          <div class="dot"></div>
          <div>
            <div class="title">CIBIL Score</div>
            <div class="value">{res['score']}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with c3:
    st.markdown(
        f"""
        <div class="card kpi">
          <div class="dot"></div>
          <div>
            <div class="title">Enquiries (Last 3M)</div>
            <div class="value">{res['enquiries_last_3m']}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with c4:
    st.markdown(
        f"""
        <div class="card kpi">
          <div class="dot"></div>
          <div>
            <div class="title">Total Past Due</div>
            <div class="value">{r(res['total_past_due'])}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("&nbsp;")

# ==============================
# ----------- Tabs ------------
# ==============================

tab1, tab2, tab3, tab4 = st.tabs(
    [
        "📌 Credit Summary",
        "📂 Complete Account History",
        "⚠️ Missed Payment Details",
        "📊 Portfolio & Exports",
    ]
)

with tab1:
    # --- UPDATED: Added new metrics to summary table ---
    summary_pairs = [
        ("Active Loans", str(res["active_loans"])),
        ("Sanctioned on Active Loans", r(res["active_sanction_total"])),
        ("Total EMI Obligations", r(res["total_emi"])),
        ("Missed Payments", str(res["missed_payments"])),
        ("30+ DPD in Last 6M", str(res["dpd30_6m"])),
        ("30+ DPD in Last 12M", str(res["dpd30_12m"])),
        ("Max DPD (12M)", str(res["max_dpd_12m"])),
        ("Write-offs", str(res["writeoff_count"])),
        ("Credit Utilization", str(res["utilization"])),
        ("PL/BL Availed in last 6m", str(res["pl_bl_availed_last_6m"])),
        ("Loan Availed in last 3m", str(res["loans_availed_last_3m"])),
    ]
    df_summary = pd.DataFrame(summary_pairs, columns=["Metric", "Value"]).astype(
        {"Metric": "string", "Value": "string"}
    )
    st.table(df_summary)

with tab2:
    st.subheader("Complete Account History")
    acc_df = res["accounts_df"].copy()

    # Filters
    colA, colB = st.columns([1, 2])
    with colA:
        status = st.radio(
            "Filter by Status:", ["All", "Open", "Closed"], horizontal=True
        )
    with colB:
        query = st.text_input("🔍 Search by Lender Name")

    df_f = acc_df.copy()
    if status != "All":
        df_f = df_f[df_f["Status"] == status]
    if query:
        df_f = df_f[df_f["Financer"].str.contains(query, case=False, na=False)]

    # Show nice, wide table
    st.dataframe(df_f, use_container_width=True, height=520)

    st.markdown("#### Export filtered results")
    ccsv, cxl = st.columns(2)
    with ccsv:
        st.download_button(
            "⬇️ Download CSV",
            data=convert_df_to_csv(df_f),
            file_name="account_history_filtered.csv",
            mime="text/csv",
        )
    with cxl:
        st.download_button(
            "⬇️ Download Excel",
            data=convert_df_to_excel(df_f),
            file_name="account_history_filtered.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

with tab3:
    st.subheader("Missed Payment Details")
    missed_df = res["missed_df"].copy()
    if missed_df.empty:
        st.info("No missed payments recorded.")
    else:
        st.dataframe(missed_df, use_container_width=True, height=520)

with tab4:
    st.subheader("Portfolio Summary + PDF Export")

    portfolio_series = pd.Series(res["portfolio"])
    if portfolio_series.empty:
        st.info("No portfolio data available.")
    else:
        # Apply abbreviations
        portfolio_series.index = [abbreviate_account_type(x) for x in portfolio_series.index]

        st.write("### Loan Portfolio Distribution")
        
        import altair as alt
        df_chart = pd.DataFrame({
            "Loan Type": portfolio_series.index,
            "Count of Loans": portfolio_series.values
        })

        chart = (
            alt.Chart(df_chart)
            .mark_bar(color="#E63946")
            .encode(
                x=alt.X("Loan Type:N", sort="-y", title="Loan Type"),
                y=alt.Y("Count of Loans:Q", title="Count of Loans"),
                tooltip=["Loan Type", "Count of Loans"]
            )
            .properties(width=700, height=400)
            .interactive()
        )

        text = chart.mark_text(
            align="center", baseline="bottom", dy=-5, color="white", fontWeight="bold"
        ).encode(text="Count of Loans:Q")

        st.altair_chart(chart + text, use_container_width=True)

        # Abbreviation legend table
        st.write("### Loan Abbreviation Legend")
        mapping_df = pd.DataFrame([
            ("PL", "Personal Loan"),
            ("BL Secured", "Business Loan – Secured"),
            ("BL Agri", "Business Loan – Priority Sector – Agriculture"),
            ("BL PS Other", "Business Loan – Priority Sector – Others"),
            ("CC", "Credit Card"),
            ("AL", "Auto Loan"),
            ("EL", "Education Loan"),
            ("HL", "Home Loan"),
            ("LAP", "Loan Against Property"),
            ("GL", "Gold Loan"),
            ("CL", "Consumer Loan"),
        ], columns=["Abbreviation", "Full Name"])
        st.table(mapping_df)

    # Enquiry breakdown
    eb = pd.DataFrame(list(res["enquiry_breakdown"].items()), columns=["Purpose", "Count"])
    if not eb.empty:
        st.write("### Enquiry Breakdown")
        st.table(eb.astype({"Purpose": "string", "Count": "string"}))

    # Build PDF payload
    pdf_bytes = export_pdf(res)
    st.download_button(
        "🧾 Download Full PDF (Summary + Chart + Accounts)",
        data=pdf_bytes,
        file_name="cibil_report_summary.pdf",
        mime="application/pdf"
    )