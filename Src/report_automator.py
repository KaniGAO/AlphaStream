"""
AlphaStream - Report Automation Module
Handles scheduled jobs, Excel generation, and email delivery
"""

import os
from pathlib import Path

import pandas as pd
import smtplib
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for server/headless environments
import matplotlib.pyplot as plt
import io
import schedule
import time


# ===============================================
# Credentials: never hardcode them in source
# ===============================================

_SRC_DIR = Path(__file__).resolve().parent


def _load_local_env() -> None:
    """Load Src/.env when python-dotenv is installed (optional dependency)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(_SRC_DIR / ".env")


def require_env(name: str) -> str:
    """Return a required environment variable, or fail with setup guidance."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing environment variable {name!r}. Put it in Src/.env "
            f"(template: Src/.env.example) or export it before running. "
            f"Never commit credentials to the repository."
        )
    return value


_load_local_env()


class AlphaStreamReporter:
    """AlphaStream Report Automation Core Class"""

    def __init__(self, sender_email, sender_password):
        self.sender_email = sender_email
        self.sender_password = sender_password

    def generate_excel(self, weights_series, filepath="AlphaStream_Report.xlsx"):
        """Generate a formatted Excel report using openpyxl and Pandas"""
        df = weights_series.to_frame(name="Optimal_Weight").reset_index()
        df.columns = ["Ticker", "Optimal_Weight"]

        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Portfolio Allocation', index=False)

            worksheet = writer.sheets['Portfolio Allocation']
            worksheet.column_dimensions['A'].width = 20
            worksheet.column_dimensions['B'].width = 20

            # Apply percentage format
            for cell in worksheet['B']:
                if cell.row > 1:  # skip header
                    cell.number_format = '0.00%'

        print(f"[+] Excel report generated: {filepath}")
        return filepath

    def generate_chart_buffer(self, weights_series):
        """Generate a horizontal bar chart in memory for inline email embedding"""
        plt.figure(figsize=(8, 4))
        # Only plot stocks with weight > 0.1%
        active_weights = weights_series[weights_series > 0.001].sort_values()
        active_weights.plot(kind='barh', color='#8DA0CB')
        plt.title('Optimal Portfolio Weights')
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100)
        buf.seek(0)
        plt.close()
        return buf.read()

    def send_email(self, receiver_email, excel_path, chart_bytes):
        """Assemble and send an HTML email with inline chart and Excel attachment"""
        # ============================================================
        # MIME structure:
        #   multipart/mixed
        #     ├── multipart/related  (body + inline image)
        #     │   ├── text/html
        #     │   └── image/png (inline, Base64)
        #     └── application/xlsx   (attachment)
        # ============================================================

        # Top-level: mixed (wraps body + attachment)
        msg = MIMEMultipart('mixed')
        msg['Subject'] = '[AlphaStream] Daily Minimum Idiosyncratic Risk Portfolio Report'
        msg['From'] = self.sender_email
        msg['To'] = receiver_email

        # Inner: related (wraps HTML body + inline image)
        related_part = MIMEMultipart('related')

        # Embed chart as Base64 in HTML — Outlook-compatible, no CID dependency
        image_base64 = base64.b64encode(chart_bytes).decode('utf-8')
        html_content = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <h2>AlphaStream Daily Computation Complete</h2>
                <p>Dear Investor,</p>
                <p>Below is the <b>global minimum idiosyncratic risk portfolio</b> computed
                   based on today's closing data.</p>
                <p>Target position allocation:</p>
                <img src="data:image/png;base64,{image_base64}"
                     alt="Portfolio Weights"
                     style="max-width: 600px; border: 1px solid #ddd;">
                <p>Please refer to the <b>attached Excel file</b> for detailed position
                   data and the formatted tear sheet.</p>
                <hr>
                <p style="font-size: 12px; color: #888;">
                   This email was automatically generated and sent by AlphaStream The Automator.
                </p>
            </body>
        </html>
        """

        related_part.attach(MIMEText(html_content, 'html', 'utf-8'))

        # Also attach the image via CID as a fallback (some clients prefer this)
        img_part = MIMEImage(chart_bytes, _subtype='png')
        img_part.add_header('Content-ID', '<portfolio_chart>')
        img_part.add_header('Content-Disposition', 'inline', filename='portfolio.png')
        related_part.attach(img_part)

        # Attach the related block to the top-level mixed message
        msg.attach(related_part)

        # Attach the Excel file at the mixed level
        with open(excel_path, 'rb') as f:
            excel_data = f.read()

        excel_part = MIMEApplication(
            excel_data,
            _subtype='vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        excel_part.add_header(
            'Content-Disposition', 'attachment',
            filename='AlphaStream_Daily_Report.xlsx'
        )
        msg.attach(excel_part)

        # Send via Gmail SMTP (requires App Password enabled)
        try:
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
                smtp.login(self.sender_email, self.sender_password)
                smtp.send_message(msg)
            print(f"[+] Email sent successfully to: {receiver_email}")
        except Exception as e:
            print(f"[!] Failed to send email: {e}")


# ===============================================
# Batch Job Scheduler
# ===============================================

def daily_batch_job():
    """Daily batch job: compute optimal weights, generate report, send email"""
    print("[*] Triggering daily batch job...")

    # 1. Run AlphaStreamEngine to get optimal weights (placeholder data)
    final_weights = pd.Series({
        "3288 HK Equity": 0.30,
        "3328 HK Equity": 0.19,
        "363 HK Equity": 0.15
    })

    # 2. Instantiate reporter (credentials come from the environment, never source)
    reporter = AlphaStreamReporter(
        sender_email=require_env("GMAIL_USER"),
        sender_password=require_env("GMAIL_APP_PASSWORD"),
    )

    # 3. Generate Excel report and chart
    excel_file = reporter.generate_excel(final_weights)
    chart_bytes = reporter.generate_chart_buffer(final_weights)

    # 4. Send email
    reporter.send_email("target_investor@example.com", excel_file, chart_bytes)


# Run daily at 17:00
schedule.every().day.at("17:00").do(daily_batch_job)


if __name__ == "__main__":
    # Daemon loop
    while True:
        schedule.run_pending()
        time.sleep(60)
