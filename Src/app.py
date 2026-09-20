"""
AlphaStream - FastAPI 网页后端服务
工业级异步架构：前台秒回 + 后台搬砖解耦
"""

from fastapi import FastAPI, Form, BackgroundTasks
from fastapi.responses import HTMLResponse
from pathlib import Path
import uvicorn

# 导入报告类
from report_automator import AlphaStreamReporter, require_env
import pandas as pd

app = FastAPI(title="AlphaStream", description="Alpha 因子研究与报告系统")

# 获取当前 app.py 所在的绝对目录 (即 Src 目录)
current_dir = Path(__file__).resolve().parent
html_path = current_dir / "templates" / "index.html"


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """路由：直接返回静态 HTML（绕过 Jinja2 3.1.6 + Python 3.14 缓存键哈希 bug）"""
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


# =====================================================================
# 🛠️ 将沉重的"搬砖活"抽离成一个独立的后台工人函数
# =====================================================================

def heavy_quant_pipeline_worker(email: str):
    """这个函数包含了所有耗时漫长的计算和网络发送"""
    print(f"[Worker] 👷 后台工人开始为 {email} 搬砖...")
    
    # 1. 调用 AlphaStream 核心引擎获取最优权重 (模拟数据)
    mock_weights = pd.Series({
        "3288 HK Equity": 0.30,
        "3328 HK Equity": 0.19,
        "66 HK Equity": 0.12
    })
    
    # 2. 生成报表和图表（凭据只从环境变量读取，绝不写进源码）
    reporter = AlphaStreamReporter(
        sender_email=require_env("GMAIL_USER"),
        sender_password=require_env("GMAIL_APP_PASSWORD"),
    )
    excel_file = reporter.generate_excel(mock_weights)
    chart_bytes = reporter.generate_chart_buffer(mock_weights)
    
    # 3. 慢速的网络邮件发送
    reporter.send_email(email, excel_file, chart_bytes)
    print(f"[Worker] 🎉 后台工人大功告成，邮件已送达！")


# =====================================================================
# 🌐 网页接口：只负责接待，绝不搬砖
# =====================================================================

@app.post("/run-pipeline")
async def trigger_pipeline(background_tasks: BackgroundTasks, email: str = Form(...)):
    """接收网页请求 → 秒回响应 → 任务丢给后台线程"""
    print(f"[*] 前台接待员收到请求，目标: {email}")
    
    # 把沉重的任务挂载到后台任务队列中，然后拍拍屁股直接走人
    background_tasks.add_task(heavy_quant_pipeline_worker, email)
    
    # 毫秒级秒回网页，绝不让浏览器转圈等半天！
    return {
        "status": "processing",
        "message": f"🚀 引擎已在后台异步点火！计算矩阵与发送邮件需要一定时间，请稍后直接检查您的邮箱: {email}"
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
