#!/usr/bin/env bash
# הפעלת Construction Audit System - Linux/Mac
set -e
mkdir -p data/projects output/cache output/reports
streamlit run app.py --server.port 8501 --server.headless true
