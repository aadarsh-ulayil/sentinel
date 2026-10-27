"""Supported launcher: one worker and loopback only."""
import uvicorn
from .app import create_app

if __name__=='__main__':
    uvicorn.run(create_app(),host='127.0.0.1',port=8000,workers=1)
