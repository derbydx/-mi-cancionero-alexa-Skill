import logging
import os
import sys

from dotenv import load_dotenv
load_dotenv()

# Ensure backend/ directory is on the path for intra-package imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from ask_sdk_webservice_support.verifier import (
    RequestVerifier,
    TimestampVerifier,
    VerificationException,
)

from config import settings
from alexa_handler import handle_alexa_request
from audio_proxy import stream_audio
from music_service import init_ytmusic

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Alexa Music Streaming")

_verifiers = [RequestVerifier(), TimestampVerifier()]


@app.on_event("startup")
async def startup():
    try:
        init_ytmusic()
        logger.info("YTMusic initialized")
    except Exception as e:
        logger.warning(f"YTMusic init warning: {e}")


@app.post("/alexa")
async def alexa_endpoint(request: Request):
    body_bytes = await request.body()
    if not settings.skip_signature_verification:
        try:
            for verifier in _verifiers:
                verifier.verify(
                    dict(request.headers),
                    body_bytes.decode("utf-8"),
                    body_bytes.decode("utf-8"),
                )
        except VerificationException as e:
            logger.warning(f"Firma de Alexa invalida: {e}")
            return JSONResponse(status_code=400, content={"error": "Invalid signature"})
    else:
        logger.debug("Verificacion de firma DESACTIVADA (modo desarrollo)")

    try:
        body = await request.json()
        logger.info(f"Alexa request type: {body.get('request', {}).get('type')}")
        response = handle_alexa_request(body)
        return JSONResponse(content=response)
    except Exception as e:
        logger.error(f"Error handling Alexa request: {e}")
        return JSONResponse(content={
            "version": "1.0",
            "response": {
                "outputSpeech": {"type": "PlainText", "text": "Hubo un error."},
                "shouldEndSession": True,
            }
        })


@app.get("/proxy/audio/{video_id}")
async def proxy_audio(video_id: str, request: Request):
    return await stream_audio(video_id, request)


@app.get("/health")
async def health():
    return {"status": "ok"}
