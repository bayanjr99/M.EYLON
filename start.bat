@echo off
REM הפעלת Construction Audit System - Windows
if not exist data\projects mkdir data\projects
if not exist output\cache mkdir output\cache
if not exist output\reports mkdir output\reports
streamlit run app.py --server.port 8501 --server.headless true
