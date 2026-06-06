from fastapi import FastAPI
import time, random, os
from opencensus.ext.azure.log_exporter import AzureLogHandler
import logging

app = FastAPI()

# Add basic logging that will be captured by Azure Container Apps automatically
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.get("/health")
def health(): 
    return {"status": "ok"}

@app.get("/leak")
def leak():
    logger.error("Memory leak endpoint hit! Allocating 100MB.")
    _ = [bytearray(10**6) for _ in range(100)]  # allocate 100MB
    return {"status": "leaked"}

@app.get("/spike")
def spike():
    logger.error("CPU spike endpoint hit! Burning CPU for 5 seconds.")
    start = time.time()
    while time.time() - start < 5:   # burn CPU for 5 seconds
        pass
    return {"status": "spiked"}

@app.get("/crash")
def crash():
    logger.critical("Crash endpoint hit! Raising unhandled exception.")
    raise Exception("Simulated internal server error")

@app.get("/slow")
def slow():
    logger.warning("Slow endpoint hit! Sleeping for a few seconds.")
    time.sleep(random.uniform(3, 8))
    return {"status": "slow"}
