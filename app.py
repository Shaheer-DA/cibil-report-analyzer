import streamlit as st
import json
from datetime import datetime, timedelta

def analyze_cibil_report(data, reference_date):
    """
    Analyzes the CIBIL JSON data and extracts details of active auto loans.
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
    written_off_accounts = set()
    
    # --- CHANGE: Create a list to hold auto loan details ---
    active_auto_loans = []

    for acc in accounts:
        if acc.get('Open') == 'Yes':
            active_accounts_count += 1
            active_sanction_total += int(acc.get('SanctionAmount', 0))
            total_existing_emi += int(acc.get('InstallmentAmount', 0))
            
            # --- CHANGE: If an active auto loan is found, capture its details ---
            if 'Auto Loan' in acc.get('AccountType', ''):
                loan_details = {
                    "Financer": acc.get('Institution', 'N/A'),
                    "SanctionAmount": int(acc.get('SanctionAmount', 0)),
                    "DateOpened": acc.get('DateOpened', 'N/A'),
                    "InstallmentAmount": int(acc.get('InstallmentAmount', 0))
                }
                active_auto_loans.append(loan_details)

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
    
    active_loans_summary = f"{active_accounts_count} / ₹{active_sanction_total:,}"
    
    return {
        "Customer Name": personal_info.get('Name', {}).get('FullName', 'N/A'),
        "CIBIL Score": data['reportData'].get('credit_score', 'N/A'),
        "Total Overdue": int(summary.get('TotalPastDue', 0)),
        "Active Loans Summary": active_loans_summary,
        "Last 3 months Enquiry": enquiries_last_3_months,
        "Total Existing EMI": total_existing_emi,
        "PL/BL Availed in last 6m": pl_bl_availed_last_6m,
        "Loan Availed in last 3m": loans_availed_last_3m,
        "Active Auto Loans": active_auto_loans, # New field with detailed list
        "Settled/Write-off count": len(written_off_accounts)
    }

# --- STREAMLIT UI ---
st.set_page_config(page_title="CIBIL Report Analyzer", layout="wide")

# (CSS styling and Custom Header remain the same)
st.markdown("""<style>...</style>""", unsafe_allow_html=True)
st.markdown("""<div class="custom-header">...</div>""", unsafe_allow_html=True)
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
            
            # (Metric cards remain the same)
            col1, col2, col3 = st.columns(3)
            # ...
            
            st.markdown("<br>", unsafe_allow_html=True)
            col4, col5, col6 = st.columns(3)
            with col4:
                st.subheader("Account Details")
                st.text(f"Active Loans / Sanctioned: {summary['Active Loans Summary']}")
                
                # --- CHANGE: Conditionally display auto loan details ---
                if summary["Active Auto Loans"]:
                    st.markdown("---")
                    st.write("**Active Auto Loan Details:**")
                    for loan in summary["Active Auto Loans"]:
                        st.text(f"  Financer: {loan['Financer']}")
                        st.text(f"  Sanction Amount: ₹{loan['SanctionAmount']:,}")
                        st.text(f"  Date Opened: {loan['DateOpened']}")
                        st.text(f"  Installment Amount: ₹{loan['InstallmentAmount']:,}")
                else:
                    st.text("Has Active Auto Loan?: No")

            with col5:
                # (Payment Details column remains the same)
                st.subheader("Payment Details")
                # ...
            with col6:
                # (Recent Activity column remains the same)
                st.subheader("Recent Activity")
                # ...
            
            st.info("Note: 'Total Bounces' information is not available in a standard CIBIL report.")