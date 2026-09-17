#!/bin/bash
cd "$(dirname "$0")"
[ -f datos/panel_ni.parquet ] || python3 preparar_datos.py
exec streamlit run app.py
