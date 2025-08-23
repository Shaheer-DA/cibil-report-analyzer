import streamlit as st
import json
from datetime import datetime, timedelta

def analyze_cibil_report(data, reference_date):
    """
    Analyzes the CIBIL JSON data using a specific reference date.
    """
    try:
        credit_report = data['reportData']['credit_report']
        report_container = credit_report['CCRResponse']['CIRReportDataLst'][0]
    except (KeyError, IndexError):
        st.error("Error: The JSON structure is not recognized. Please upload a valid CIBIL report.")
        return None

    report_date = reference_date
    accounts = report_container.get('CIRReportData', {}).get('RetailAccountDetails', [])
    summary = report_container.get('CIRReportData', {}).get('RetailAccountsSummary', {})
    personal_info = report_container.get('CIRReportData', {}).get('IDAndContactInfo', {}).get('PersonalInfo', {})
    inquiry_header = credit_report.get('CCRResponse', {}).get('InquiryResponseHeader', {})
    enquiries = credit_report.get('Enquiries', [])

    active_accounts_count, active_sanction_total, total_existing_emi = 0, 0, 0
    loans_availed_last_3m, pl_bl_availed_last_6m = 0, 0
    has_active_auto_loan = "No"
    written_off_accounts = set()

    for acc in accounts:
        if acc.get('Open') == 'Yes':
            active_accounts_count += 1
            active_sanction_total += int(acc.get('SanctionAmount', 0))
            total_existing_emi += int(acc.get('InstallmentAmount', 0))
            if 'Auto Loan' in acc.get('AccountType', ''):
                has_active_auto_loan = "Yes"
        date_opened_str = acc.get('DateOpened')
        if date_opened_str:
            date_opened = datetime.strptime(date_opened_str, '%Y-%m-%d').date()
            if date_opened >= (report_date - timedelta(days=90)):
                loans_availed_last_3m += 1
            if date_opened >= (report_date - timedelta(days=180)) and 'Personal Loan' in acc.get('AccountType', ''):
                 pl_bl_availed_last_6m += 1
        if any(h.get('AssetClassificationStatus') == 'LSS' for h in acc.get('History48Months', [])):
            written_off_accounts.add(acc.get('AccountNumber'))

    enquiries_last_3_months = 0
    for enq in enquiries:
        enq_date = datetime.strptime(enq['enquiryDate'], '%Y-%m-%d').date()
        if enq_date >= (report_date - timedelta(days=90)):
            enquiries_last_3_months += 1
    
    # --- CHANGE: Combine Active Loans and Sanctioned Amount into one field ---
    active_loans_summary = f"{active_accounts_count} / ₹{active_sanction_total:,}"

    return {
        "Customer Name": personal_info.get('Name', {}).get('FullName', 'N/A'),
        "CIBIL Score": data['reportData'].get('credit_score', 'N/A'),
        "Total Overdue": int(summary.get('TotalPastDue', 0)),
        "Active Loans Summary": active_loans_summary, # New combined field
        "Last 3 months Enquiry": enquiries_last_3_months,
        "Total Existing EMI": total_existing_emi,
        "PL/BL Availed in last 6m": pl_bl_availed_last_6m,
        "Loan Availed in last 3m": loans_availed_last_3m,
        "Has Active Auto Loan?": has_active_auto_loan,
        "Settled/Write-off count": len(written_off_accounts)
    }

# --- STREAMLIT UI ---
st.set_page_config(page_title="CIBIL Report Analyzer", layout="wide")

st.markdown("""
<style>
    .custom-header { display: flex; align-items: center; gap: 1rem; padding: 1rem 0; }
    .custom-header .logo { font-size: 2.5rem; }
    .custom-header .title-text { font-size: 2rem; font-weight: bold; color: #FAFAFA; }
    .metric-card { padding: 1rem; border-radius: 0.5rem; background-color: #2C2C38; border: 1px solid #2C2C38; }
    .metric-card .metric-label { font-size: 1rem; color: #BDBDBD; }
    .metric-card .metric-value { font-size: 2rem; font-weight: bold; color: white; }
    .metric-card .metric-value.green { color: #28a745; }
    .metric-card .metric-value.red { color: #dc3545; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="custom-header">
    <div class="logo">📊</div>
    <div class="title-text">CIBIL Report Analyzer</div>
</div>
""", unsafe_allow_html=True)
st.markdown("Upload your CIBIL JSON file to get an instant, easy-to-read summary of your credit report.")

uploaded_file = st.file_uploader("Choose your CIBIL JSON file", type="json")

if uploaded_file is not None:
    data = json.load(uploaded_file)
    st.markdown("---")
    st.subheader("🗓️ Select Report Date")
    
    auto_date_str = data.get('reportData', {}).get('credit_report', {}).get('CCRResponse', {}).get('InquiryResponseHeader', {}).get('Date')
    
    default_date = datetime.strptime(auto_date_str, '%Y-%m-%d').date() if auto_date_str else datetime.now().date()
    if not auto_date_str:
        st.warning("Could not automatically detect the report date. Please select it manually.")

    selected_date = st.date_input("Choose the date on which the report was generated:", value=default_date)

    if st.button("Analyze Report"):
        summary = analyze_cibil_report(data, selected_date)
        if summary:
            st.markdown("---")
            st.header(f"Credit Summary for {summary['Customer Name']}")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.markdown(f'<div class="metric-card"><div class="metric-label">CIBIL Score</div><div class="metric-value">{summary["CIBIL Score"]}</div></div>', unsafe_allow_html=True)
            with col2:
                overdue_color = "red" if summary['Total Overdue'] > 0 else "green"
                st.markdown(f'<div class="metric-card"><div class="metric-label">Total Overdue</div><div class="metric-value {overdue_color}">₹{summary["Total Overdue"]:,}</div></div>', unsafe_allow_html=True)
            with col3:
                enquiry_color = "red" if summary['Last 3 months Enquiry'] > 5 else "green"
                st.markdown(f'<div class="metric-card"><div class="metric-label">Last 3 months Enquiry</div><div class="metric-value {enquiry_color}">{summary["Last 3 months Enquiry"]}</div></div>', unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            col4, col5, col6 = st.columns(3)
            with col4:
                st.subheader("Account Details")
                # --- CHANGE: Display the new combined field ---
                st.text(f"Active Loans / Sanctioned: {summary['Active Loans Summary']}")
                st.text(f"Has Active Auto Loan?: {summary['Has Active Auto Loan?']}")
            with col5:
                st.subheader("Payment Details")
                st.text(f"Total Existing EMI: ₹{summary['Total Existing EMI']:,}")
                settled_color = "red" if summary['Settled/Write-off count'] > 0 else "green"
                st.markdown(f"Settled/Write-off Count: <span style='color:{settled_color}; font-weight:bold;'>{summary['Settled/Write-off count']}</span>", unsafe_allow_html=True)
            with col6:
                st.subheader("Recent Activity")
                st.text(f"PL/BL Availed in last 6m: {summary['PL/BL Availed in last 6m']}")
                st.text(f"Loan Availed in last 3m: {summary['Loan Availed in last 3m']}")
            
            st.info("Note: 'Total Bounces' information is not available in a standard CIBIL report.")