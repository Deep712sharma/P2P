# Start the FastAPI backend inside the paper2ppt conda environment
conda run -n paper2ppt uvicorn app:app --reload --host 0.0.0.0 --port 8000
