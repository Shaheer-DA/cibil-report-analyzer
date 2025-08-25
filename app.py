import streamlit as st
import json
from datetime import datetime, timedelta
import pandas as pd
import base64

def analyze_cibil_report(data, reference_date):
    """
    Analyzes the CIBIL JSON data and returns a dictionary of all key metrics.
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
    enquiries = credit_report.get('Enquiries', [])

    active_accounts_count, active_sanction_total, total_existing_emi = 0, 0, 0
    loans_availed_last_3m, pl_bl_availed_last_6m = 0, 0
    written_off_accounts = set()
    active_auto_loans = []
    total_missed_payments = 0
    missed_payments_details = []
    
    loan_portfolio = {
        "Personal Loan": 0, "Business Loan": 0, "Auto Loan": 0,
        "Credit Card": 0, "Loan on Credit Card": 0, "Housing Loan": 0,
        "Two Wheeler Loan": 0, "Gold Loan": 0, "Other": 0
    }
    auto_loan_types = ["Auto Loan (Personal)", "Used Car Loan", "P2P Auto Loan"]
    
    active_loan_portfolio_details = []

    for acc in accounts:
        acc_type = acc.get('AccountType', 'Other')
        if acc_type in auto_loan_types:
            loan_portfolio["Auto Loan"] += 1
        elif acc_type in loan_portfolio:
            loan_portfolio[acc_type] += 1
        else:
            loan_portfolio["Other"] += 1

        for month_history in acc.get('History48Months', []):
            try:
                payment_status_dpd = int(month_history.get('PaymentStatus', 0))
                if payment_status_dpd > 0:
                    total_missed_payments += 1
                    missed_payments_details.append({
                        "Financer": acc.get('Institution', 'N/A'),
                        "Account Type": acc.get('AccountType', 'N/A'),
                        "Month/Year": month_history.get('key', 'N/A'),
                        "Days Past Due": payment_status_dpd,
                        "Current Overdue": f"₹{int(acc.get('PastDueAmount', 0)):,}"
                    })
            except (ValueError, TypeError):
                continue
                
        if acc.get('Open') == 'Yes':
            active_accounts_count += 1
            active_sanction_total += int(acc.get('SanctionAmount', 0))
            installment_str = acc.get('InstallmentAmount')
            installment_amount = int(installment_str) if installment_str and installment_str.isdigit() else 0
            last_payment_str = acc.get('LastPayment')
            last_payment_amount = int(last_payment_str) if last_payment_str and last_payment_str.isdigit() else 0
            emi_for_this_account = installment_amount if installment_amount > 0 else last_payment_amount
            total_existing_emi += emi_for_this_account

            active_loan_portfolio_details.append({
                "Financer": acc.get('Institution', 'N/A'),
                "Account Type": acc.get('AccountType', 'N/A'),
                "Date Opened": acc.get('DateOpened', 'N/A'),
                "Sanction Amount": f"₹{int(acc.get('SanctionAmount', 0)):,}",
            })
            
            if acc_type in auto_loan_types:
                active_auto_loans.append({
                    "Financer": acc.get('Institution', 'N/A'),
                    "Sanction Amount": f"₹{int(acc.get('SanctionAmount', 0)):,}",
                    "Date Opened": acc.get('DateOpened', 'N/A'),
                    "Installment Amount": f"₹{emi_for_this_account:,}"
                })
        
        date_opened_str = acc.get('DateOpened')
        if date_opened_str:
            date_opened = datetime.strptime(date_opened_str, '%Y-%m-%d').date()
            if date_opened >= (report_date - timedelta(days=90)):
                loans_availed_last_3m += 1
            if date_opened >= (report_date - timedelta(days=180)) and ('Personal Loan' in acc_type or 'Business Loan' in acc_type):
                 pl_bl_availed_last_6m += 1
        
        if any(h.get('AssetClassificationStatus') == 'LSS' for h in acc.get('History48Months', [])):
            written_off_accounts.add(acc.get('AccountNumber'))

    enquiries_last_3_months = 0
    for enq in enquiries:
        enq_date = datetime.strptime(enq['enquiryDate'], '%Y-%m-%d').date()
        if enq_date >= (report_date - timedelta(days=90)):
            enquiries_last_3_months += 1
            
    all_accounts_details = []
    for acc in accounts:
        all_accounts_details.append({
            "Financer": acc.get('Institution', 'N/A'), "Account Type": acc.get('AccountType', 'N/A'),
            "Status": "Open" if acc.get('Open') == 'Yes' else "Closed", "Date Opened": acc.get('DateOpened', 'N/A'),
            "SanctionAmountInt": int(acc.get('SanctionAmount', 0)), "Sanction Amount": f"₹{int(acc.get('SanctionAmount', 0)):,}",
            "Current Balance": f"₹{int(acc.get('Balance', 0)):,}", "Amount Overdue": f"₹{int(acc.get('PastDueAmount', 0)):,}"
        })
        
    return {
        "Customer Name": personal_info.get('Name', {}).get('FullName', 'N/A'),
        "CIBIL Score": data['reportData'].get('credit_score', 'N/A'),
        "Total Overdue": int(summary.get('TotalPastDue', 0)),
        "Active Loans / Sanctioned": f"{active_accounts_count} / ₹{active_sanction_total:,}",
        "Last 3 months Enquiry": enquiries_last_3_months, "Total Existing EMI": total_existing_emi,
        "Total Missed Payments": total_missed_payments, "Missed Payments Details": missed_payments_details,
        "Active Auto Loans": active_auto_loans, "Settled/Write-off count": len(written_off_accounts),
        "All Accounts Details": all_accounts_details, "PL/BL Availed in last 6m": pl_bl_availed_last_6m,
        "Loan Availed in last 3m": loans_availed_last_3m, "Loan Portfolio": loan_portfolio,
        "Active Loan Portfolio Details": active_loan_portfolio_details
    }

# --- 3. STREAMLIT UI ---
st.set_page_config(page_title="CIBIL Report Analyzer", layout="wide")

st.markdown("""
<style>
    .custom-header { display: flex; align-items: center; gap: 1rem; padding: 1rem 0; }
    .custom-header .logo { font-size: 2.5rem; }
    .custom-header .title-text { font-size: 2rem; font-weight: bold; color: #FAFAFA; }
    .metric-card { padding: 1rem; border-radius: 0.5rem; background-color: #2C2C38; border: 1px solid #2C2C38; text-align: center; }
    .metric-card .metric-label { font-size: 1rem; color: #BDBDBD; }
    .metric-card .metric-value { font-size: 2.5rem; font-weight: bold; color: white; }
    .metric-card .metric-value.green { color: #28a745; }
    .metric-card .metric-value.red { color: #dc3545; }
</style>
""", unsafe_allow_html=True)

if 'analysis_done' not in st.session_state: st.session_state.analysis_done = False
if 'widget_key' not in st.session_state: st.session_state.widget_key = 0
def reset_app():
    st.session_state.analysis_done = False
    if 'summary' in st.session_state: del st.session_state['summary']
    st.session_state.widget_key += 1

st.markdown("""
<div class="custom-header">
    <div class="logo">📊</div>
    <div class="title-text">CIBIL Report Analyzer</div>
</div>
""", unsafe_allow_html=True)
st.markdown("Upload your CIBIL JSON file or paste the content below to get an instant summary.")

input_method = st.radio("Choose Input Method:", ["File Upload", "Paste JSON Text"], horizontal=True, key=f"radio_{st.session_state.widget_key}")
data = None

if input_method == "File Upload":
    uploaded_file = st.file_uploader("Choose your CIBIL JSON file", type="json", key=f"uploader_{st.session_state.widget_key}")
    if uploaded_file: data = json.load(uploaded_file)
else:
    json_text = st.text_area("Paste the entire JSON content here:", height=250, key=f"textarea_{st.session_state.widget_key}")
    if json_text:
        try: data = json.loads(json_text)
        except json.JSONDecodeError:
            st.error("Invalid JSON format.")
            data = None

if data and not st.session_state.analysis_done:
    st.markdown("---")
    st.subheader("🗓️ Select Analysis Date")
    selected_date = st.date_input("Choose the date for which to run the analysis:", value=datetime.now().date())
    if st.button("Analyze Report"):
        st.session_state.summary = analyze_cibil_report(data, selected_date)
        st.session_state.analysis_done = True
        st.rerun()

if st.session_state.analysis_done:
    summary = st.session_state.get('summary')
    if summary:
        st.markdown("---")
        st.header(f"Credit Summary for {summary['Customer Name']}")
        
        tab1, tab2, tab3, tab4 = st.tabs(["📊 Credit Summary", "🗂️ Complete Account History", "🔍 Missed Payment Details", "💼 Portfolio Summary"])

        with tab1:
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
            summary_data = {
                "Key Metric": [
                    "Active Loans / Sanctioned", "Total Existing EMI", "Total Missed Payments (in 48 Mths)",
                    "Settled/Write-off Count", "PL/BL Availed in last 6m", "Loan Availed in last 3m"
                ],
                "Value": [
                    str(summary["Active Loans / Sanctioned"]), f"₹{summary['Total Existing EMI']:,}",
                    str(summary["Total Missed Payments"]), str(summary["Settled/Write-off count"]),
                    str(summary["PL/BL Availed in last 6m"]), str(summary["Loan Availed in last 3m"])
                ]
            }
            summary_df = pd.DataFrame(summary_data)
            st.table(summary_df.style.hide(axis="index"))
            if summary["Active Auto Loans"]:
                st.markdown("---")
                st.subheader("Active Auto Loan Details")
                st.table(pd.DataFrame(summary["Active Auto Loans"]))

        with tab2:
            if summary["All Accounts Details"]:
                df_all_accounts = pd.DataFrame(summary["All Accounts Details"])
                st.write("Filter accounts by status:")
                status_filter = st.radio("Status", ["All", "Open", "Closed"], horizontal=True, label_visibility="collapsed")
                if status_filter == "Open": df_display = df_all_accounts[df_all_accounts['Status'] == 'Open']
                elif status_filter == "Closed": df_display = df_all_accounts[df_all_accounts['Status'] == 'Closed']
                else: df_display = df_all_accounts
                df_display = df_display.sort_values(by="SanctionAmountInt", ascending=False)
                df_to_show = df_display.drop(columns=["SanctionAmountInt"])
                def highlight_overdue(row):
                    is_overdue = int(str(row["Amount Overdue"]).replace("₹", "").replace(",", "")) > 0
                    return ['background-color: #4a2c2c'] * len(row) if is_overdue else [''] * len(row)
                st.dataframe(df_to_show.style.apply(highlight_overdue, axis=1), use_container_width=True)
        
        with tab3:
            st.subheader("Log of All Missed Payments (48-Month History)")
            if summary["Missed Payments Details"]:
                df_missed = pd.DataFrame(summary["Missed Payments Details"])
                try:
                    df_missed['SortableDate'] = pd.to_datetime(df_missed['Month/Year'], format='%m-%y')
                    df_missed = df_missed.sort_values(by='SortableDate', ascending=False).drop(columns=['SortableDate'])
                except (ValueError, TypeError): pass
                df_missed.insert(0, 'Sr. No.', range(1, 1 + len(df_missed)))
                df_display = df_missed[['Sr. No.', 'Financer', 'Account Type', 'Month/Year', 'Days Past Due', 'Current Overdue']]
                st.dataframe(df_display, use_container_width=True)
            else:
                st.success("No missed payments found in the 48-month history.")

        with tab4:
            st.subheader("Customer Loan Portfolio (Lifetime)")
            portfolio_data = {key: val for key, val in summary["Loan Portfolio"].items() if val > 0}
            if portfolio_data:
                portfolio_df = pd.DataFrame(list(portfolio_data.items()), columns=['Loan Type', 'Total Count'])
                st.table(portfolio_df.style.hide(axis="index"))
            else:
                st.info("No loan history found in the report.")
            if summary["Active Loan Portfolio Details"]:
                st.markdown("---")
                st.subheader("Details of Active Loans")
                active_loans_df = pd.DataFrame(summary["Active Loan Portfolio Details"])
                st.dataframe(active_loans_df, use_container_width=True)

        st.markdown("---")
        if st.button("Analyze Another Report"):
            reset_app()
            st.rerun()